"""Step Functions Step 2: AI analysis via Amazon Bedrock.

Sends parsed file data and images to Claude for 3D model generation.
"""
from __future__ import annotations

import json
import logging
import os
import time

import boto3
from common.ws_notify import send_progress, send_token_usage

logger = logging.getLogger()
logger.setLevel(logging.INFO)

NODES_TABLE = os.environ.get("NODES_TABLE", "")
SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "")
UPLOADS_BUCKET = os.environ.get("UPLOADS_BUCKET", "")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "ap-northeast-1")

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")


def lambda_handler(event: dict, context) -> dict:
    """Invoke Bedrock to generate CadQuery script from parsed data.

    Input:
        {"session_id": "...", "node_id": "...", "parsed_data": {...}}
    Output:
        {"session_id": "...", "node_id": "...", "cadquery_script": "...", "confidence_map": {...}}
    """
    session_id = event["session_id"]
    node_id = event["node_id"]
    parsed_data = event.get("parsed_data", {})
    logger.info("AI analyzing session %s, node %s", session_id, node_id)

    # チャット編集による再実行: 既存ノードのスクリプトをそのまま利用してスキップ
    if event.get("restart_from_cadquery"):
        logger.info("restart_from_cadquery=True — skipping AI for node %s", node_id)
        nodes_table = dynamodb.Table(NODES_TABLE)
        resp = nodes_table.get_item(Key={"node_id": node_id})
        existing_node = resp.get("Item", {})
        return {
            "session_id": session_id,
            "node_id": node_id,
            "cadquery_script": existing_node.get("cadquery_script", ""),
        }

    send_progress(session_id, "AI_ANALYZING", 30, "AI図面解釈中...")

    # Update session status
    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET #s = :status, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "AI_ANALYZING",
            ":now": int(time.time()),
        },
    )

    # Load first image for multimodal analysis
    image_bytes = None
    image_media_type = "image/png"
    image_keys = parsed_data.get("image_keys", [])
    if image_keys:
        try:
            obj = s3_client.get_object(Bucket=UPLOADS_BUCKET, Key=image_keys[0])
            image_bytes = obj["Body"].read()
            # Detect media type from extension
            ext = image_keys[0].rsplit(".", 1)[-1].lower() if "." in image_keys[0] else "png"
            media_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "tiff": "image/tiff", "tif": "image/tiff"}
            image_media_type = media_map.get(ext, "image/png")
        except Exception as e:
            logger.warning("Failed to load image %s: %s", image_keys[0], e)

    # Build prompt (image-specific when raster input)
    has_image = image_bytes is not None
    has_dxf = any(f.get("type") == "vector_cad" for f in parsed_data.get("files", []))
    prompt = _build_image_prompt() if has_image and not has_dxf else _build_prompt(parsed_data)

    # Invoke AI
    from common.bedrock_client import get_bedrock_client

    client = get_bedrock_client(region=BEDROCK_REGION)
    context_json = parsed_data.get("files") if has_dxf else None
    invoke_result = client.invoke_multimodal(
        prompt=prompt,
        image_bytes=image_bytes,
        image_media_type=image_media_type,
        context_json=context_json,
    )
    send_token_usage(session_id, "AI_ANALYZING", invoke_result.input_tokens, invoke_result.output_tokens)

    # Parse AI response
    ai_output = _parse_ai_response(invoke_result.text)
    cadquery_script = ai_output.get("cadquery_script", "")
    ai_reasoning = ai_output.get("reasoning", "")

    # Validate script
    from common.script_validator import validate_cadquery_script, ScriptValidationError

    try:
        validate_cadquery_script(cadquery_script)
    except ScriptValidationError as e:
        logger.error("Script validation failed: %s", e)
        raise RuntimeError(f"AI generated script failed validation: {e}") from e

    # Update node with AI results
    nodes_table = dynamodb.Table(NODES_TABLE)
    nodes_table.update_item(
        Key={"node_id": node_id},
        UpdateExpression="SET cadquery_script = :script, ai_reasoning = :reason",
        ExpressionAttributeValues={
            ":script": cadquery_script,
            ":reason": ai_reasoning,
        },
    )

    logger.info(
        "AI analysis complete for node %s, script length=%d",
        node_id,
        len(cadquery_script),
    )

    return {
        "session_id": session_id,
        "node_id": node_id,
        "cadquery_script": cadquery_script,
        "ai_reasoning": ai_reasoning,
    }


def _build_image_prompt() -> str:
    """Image-only analysis prompt: let the AI focus on reading the drawing visually."""
    return """添付の2D図面画像を正確に読み取り、3Dモデルを生成するCadQueryスクリプトを作成してください。

【図面読み取りの指示】
① まず図面上のすべての寸法値を一つずつ読み取ってリスト化してください
② 図面中のビュー（正面図・平面図・側面図）を各々識別してください
③ 円の数とサイズを正確に数えてください。「2x」「3x」などの表記は複数個を意味します
④ Φ記号は直径、Rは半径です
⑤ 点線（破線）は隠れ線（内部形状）、一点鎖線は中心線です
⑥ 表題欄の情報（SCALE, DWG NO等）も参照してください

【穴の方向と面指定 ― 最重要ルール】
- 穴の方向は必ず図面のビューから判断すること
- 正面図で円が見える → その穴は「奥行き方向（Z軸）」に進む
- 平面図（上面図）で円が見える → その穴は「高さ方向（Y軸）」に進む
- 側面図で円が見える → その穴は「幅方向（X軸）」に進む
- 貫通穴か止まり穴かは、他のビューの破線（隠れ線）で判断する:
  - 破線が反対面まで届いている → 貫通穴
  - 破線が途中で止まっている → 止まり穴（深さを読み取る）
  - 判断できない場合は「貫通穴と仮定」と明記する
- **穴を開ける面（ドリル面）を必ず指定すること**
  - Z方向の穴: `.faces(">Z").workplane()` で `.hole()` (上面から) or `.faces("<Z")`
  - Y方向の穴: `.faces(">Y").workplane()` or `.faces("<Y").workplane()` で `.hole()`
  - X方向の穴: `.faces(">X").workplane()` or `.faces("<X").workplane()` で `.hole()`
- **`.faces("...").workplane()` を省略すると穴の位置・方向が狂うので絶対に省略しないこと**

【穴のグループ化ルール】
- 同じドリル面・同じ径・同じ深さ（貫通/止まり）の穴はグループにまとめる
- グループ化した穴は `.pushPoints()` で一括処理する
- 穴が1個でも `.pushPoints([(x, y)]).hole(d)` の形式で統一する

【CadQueryコードパターン ― 穴あけは必ずこの形式に従うこと】
```python
# 寸法定数
WIDTH = 120.0
HEIGHT = 80.0
DEPTH = 15.0

# Feature-001: ベースボックス
result = cq.Workplane("XY").box(WIDTH, HEIGHT, DEPTH)

# Hole Group A: 上面(>Z)からΦ12貫通穴 x2
# Hole-001: Φ12 Z方向貫通 ドリル面:>Z (CQ: X=-40, Y=-10)
# Hole-002: Φ12 Z方向貫通 ドリル面:>Z (CQ: X=+40, Y=-10)
result = result.faces(">Z").workplane().pushPoints([(-40, -10), (40, -10)]).hole(12)

# Hole Group B: 上面(>Z)からΦ30貫通穴 x1
# Hole-003: Φ30 Z方向貫通 ドリル面:>Z (CQ: X=-10, Y=-10)
result = result.faces(">Z").workplane().pushPoints([(-10, -10)]).hole(30)
```
**穴あけは必ず `.faces("...").workplane().pushPoints([...]).hole(d)` の形式で書くこと。**
**`.center().hole()` や `.workplane()` なしの `.hole()` は使用禁止。**

【CadQuery 座標系 ― 超重要】
- X: 幅（横方向）、Y: 高さ（縦方向）、Z: 奥行き（厚み方向）
- `cq.Workplane("XY")` で始めた場合、`.box(W, H, D)` は W=X, H=Y, D=Z
- **`.box()` は原点中心に生成される**（左端 = -W/2、右端 = +W/2、下端 = -H/2、上端 = +H/2）
- 図面の寸法は通常「左端からXmm」「下端からYmm」のように片端基準で記載される
- したがって、図面上の座標 (Xd, Yd) → CadQuery座標は **(Xd - W/2, Yd - H/2)** に変換が必要
  - 例: 120×80の箱で「左端から20mm, 下端から30mm」→ CadQuery座標 = (20-60, 30-40) = (-40, -10)
- `.extrude()` は現在のワークプレーンの法線方向に押し出す
- 穴位置は必ずこの座標変換を適用してから `.center()` で指定すること

【スクリプト作成ルール】
- `import cadquery as cq` から始まる完全に実行可能なコードを書く
- 各フィーチャーに `# Feature-NNN: 説明` コメントを付ける
- 穴は通し番号で管理する: `# Hole-001: Φ30 Z方向貫通 ドリル面:>Z (CQ: X=0, Y=0)` のように番号・径・方向・貫通/止まり・ドリル面・中心座標を記載
- 同一面・同一径・同一深さの穴はグループ化: `# Hole Group A: 上面(>Z)からΦ12貫通穴 x2`
- 穴あけは必ず `.faces("...").workplane().pushPoints([...]).hole(d)` 形式（例外なし）
- すべての寸法を先頭に定数として定義する（マジックナンバー禁止）
- 最終結果を `result` 変数に代入する
- 穴の位置は図面の寸法から正確に計算し、CadQuery中心原点座標に変換する
- show_object() は使用禁止（ヘッドレス実行環境のため）
- `import math` は使用可能

【reasoning フィールド ― 必須】
以下の内容を日本語で stepごとに記述してください:
1. 図面から識別したビュー（正面図・平面図・側面図）とその寸法
2. 識別した各フィーチャー（穴・溝・段差等）とその判断根拠
3. 穴一覧表（Hole-001, Hole-002...の番号・径・方向・貫通/止まり・ドリル面・図面上の位置・CadQuery座標変換後の位置・グループ名）
4. 寸法の解釈（基準点と相対位置、座標変換の計算式）
5. 最終的な3D形状の概要

【出力フォーマット】
JSONのみを出力してください。他の説明文は不要です。
```json
{{
  "reasoning": "## 図面解析\\n\\n### 識別ビュー\\n- ...",
  "cadquery_script": "import cadquery as cq\\n..."
}}
```"""


def _build_prompt(parsed_data: dict) -> str:
    """DXF-based analysis prompt with entity data."""
    files = parsed_data.get("files", [])
    file_desc = []
    for f in files:
        desc = f"- {f.get('s3_key', 'unknown')}: type={f.get('type', 'unknown')}"
        entities = f.get("entities", {})
        if entities and "entity_counts" in entities:
            desc += f", entities={entities['entity_counts']}"
        file_desc.append(desc)

    file_summary = "\n".join(file_desc) if file_desc else "ファイル情報なし"

    return f"""以下の2D図面情報から3Dモデルを生成するCadQueryスクリプトを作成してください。

【入力ファイル】
{file_summary}

【穴の方向判断ルール】
- 穴の方向は必ず図面のビューから判断すること
- 正面図で円が見える → その穴は「奥行き方向（Z軸）」に進む
- 平面図（上面図）で円が見える → その穴は「高さ方向（Y軸）」に進む
- 側面図で円が見える → その穴は「幅方向（X軸）」に進む
- 貫通穴か止まり穴かは、他のビューの破線（隠れ線）で判断する:
  - 破線が反対面まで届いている → 貫通穴
  - 破線が途中で止まっている → 止まり穴
  - 判断できない場合は「貫通穴と仮定」と明記する
- **穴を開ける面（ドリル面）を必ず指定すること**
  - Z方向の穴: `.faces(">Z").workplane()` で `.hole()` (上面から) or `.faces("<Z")`
  - Y方向の穴: `.faces(">Y").workplane()` or `.faces("<Y").workplane()` で `.hole()`
  - X方向の穴: `.faces(">X").workplane()` or `.faces("<X").workplane()` で `.hole()`
- **`.faces("...").workplane()` を省略すると穴の位置・方向が狂うので絶対に省略しないこと**

【穴のグループ化ルール】
- 同じドリル面・同じ径・同じ深さ（貫通/止まり）の穴はグループにまとめる
- グループ化した穴は `.pushPoints()` で一括処理する
- 穴が1個でも `.pushPoints([(x, y)]).hole(d)` の形式で統一する

【CadQueryコードパターン ― 穴あけは必ずこの形式に従うこと】
```python
# Hole Group A: 上面(>Z)からΦ12貫通穴 x2
result = result.faces(">Z").workplane().pushPoints([(-40, -10), (40, -10)]).hole(12)
# Hole Group B: 上面(>Z)からΦ30貫通穴 x1
result = result.faces(">Z").workplane().pushPoints([(-10, -10)]).hole(30)
```
**穴あけは必ず `.faces("...").workplane().pushPoints([...]).hole(d)` の形式で書くこと。**

【CadQuery 座標系 ― 超重要】
- X: 幅（横方向）、Y: 高さ（縦方向）、Z: 奥行き（厚み方向）
- **`.box()` は原点中心に生成される**（左端 = -W/2、右端 = +W/2、下端 = -H/2、上端 = +H/2）
- 図面の寸法は通常「左端からXmm」「下端からYmm」のように片端基準で記載される
- したがって、図面上の座標 (Xd, Yd) → CadQuery座標は **(Xd - W/2, Yd - H/2)** に変換が必要
  - 例: 120×80の箱で「左端から20mm, 下端から30mm」→ CadQuery座標 = (20-60, 30-40) = (-40, -10)

【スクリプト作成ルール】
- `import cadquery as cq` から始まる完全に実行可能なコードを書く
- 各フィーチャーに `# Feature-NNN:` コメントを付ける
- 穴は通し番号で管理する: `# Hole-001: Φ30 Z方向貫通 ドリル面:>Z (CQ: X=0, Y=0)` のように番号・径・方向・貫通/止まり・ドリル面・中心座標を記載
- 同一面・同一径・同一深さの穴はグループ化: `# Hole Group A: 上面(>Z)からΦ12貫通穴 x2`
- 穴あけは必ず `.faces("...").workplane().pushPoints([...]).hole(d)` 形式（例外なし）
- すべての数値は意味のある定数として抽出する（マジックナンバー禁止）
- 最終結果を `result` 変数に代入する
- 穴位置は必ず座標変換（図面座標→CadQuery中心原点座標）を適用する
- 点線は内部形状として解釈する
- show_object() は使用禁止（ヘッドレス実行環境のため）
- `import math` は使用可能

【reasoning フィールド ― 必須】
以下の内容を日本語で stepごとに記述してください:
1. 図面から識別したビュー（正面図・平面図・側面図）とその寸法
2. 識別した各フィーチャー（穴・溝・段差等）とその判断根拠
3. 穴一覧表（Hole-001, Hole-002...の番号・径・方向・貫通/止まり・ドリル面・図面上の位置・CadQuery座標変換後の位置・グループ名）
4. 寸法の解釈（基準点と相対位置、座標変換の計算式）
5. 最終的な3D形状の概要

【出力フォーマット(JSON)】
{{
  "reasoning": "## 図面解析\n\n### 識別ビュー\n- ...",
  "cadquery_script": "import cadquery as cq\\n..."
}}"""


def _parse_ai_response(raw: str) -> dict:
    """Parse AI response as JSON, with fallback for code block extraction."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from markdown code blocks
    import re

    json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", raw, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to extract CadQuery code block
    code_match = re.search(r"```(?:python)?\s*\n(.*?)\n```", raw, re.DOTALL)
    script = code_match.group(1) if code_match else ""

    return {
        "cadquery_script": script,
    }
