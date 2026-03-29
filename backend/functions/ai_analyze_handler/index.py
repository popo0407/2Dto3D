"""Step Functions Step 2: AI analysis via Amazon Bedrock.

Sends parsed file data and images to Claude for 3D model generation.
"""
from __future__ import annotations

import json
import logging
import os
import time

import boto3
from common.ws_notify import send_progress

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
    raw_response = client.invoke_multimodal(
        prompt=prompt,
        image_bytes=image_bytes,
        image_media_type=image_media_type,
        context_json=context_json,
    )

    # Parse AI response
    ai_output = _parse_ai_response(raw_response)
    cadquery_script = ai_output.get("cadquery_script", "")

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
        UpdateExpression="SET cadquery_script = :script",
        ExpressionAttributeValues={
            ":script": cadquery_script,
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

【穴・貫通穴の方向 ― 最重要ルール】
- 穴の方向は必ず図面のビューから判断すること
- 正面図で円が見える → その穴は「奥行き方向（Z軸）」に貫通
- 平面図（上面図）で円が見える → その穴は「高さ方向（Y軸）」に貫通
- 側面図で円が見える → その穴は「幅方向（X軸）」に貫通
- CadQuery の `.hole()` はデフォルトで Z 方向に穴を開ける
  - X方向の穴: `.faces(">X")` or `.faces("<X")` のワークプレーンで `.hole()`
  - Y方向の穴: `.faces(">Y")` or `.faces("<Y")` のワークプレーンで `.hole()`
  - Z方向の穴: `.faces(">Z")` or `.faces("<Z")` のワークプレーンで `.hole()`
- 穴を開ける面を間違えると形状が全く異なるので、必ず図面と照合すること

【CadQuery 座標系】
- X: 幅（横方向）、Y: 高さ（縦方向）、Z: 奥行き（厚み方向）
- `cq.Workplane("XY")` で始めた場合、`.box(W, H, D)` は W=X, H=Y, D=Z
- `.extrude()` は現在のワークプレーンの法線方向に押し出す

【スクリプト作成ルール】
- `import cadquery as cq` から始まる完全に実行可能なコードを書く
- 各フィーチャーに `# Feature-NNN: 説明` コメントを付ける（穴には方向も記載: 例 `# Feature-002: Φ30穴 Z方向貫通`）
- すべての寸法を先頭に定数として定義する（マジックナンバー禁止）
- 最終結果を `result` 変数に代入する
- 穴の位置は図面の寸法から正確に計算する
- show_object() は使用禁止（ヘッドレス実行環境のため）
- `import math` は使用可能

【出力フォーマット】
JSONのみを出力してください。他の説明文は不要です。
```json
{{
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

【穴・貫通穴の方向 ― 最重要ルール】
- 穴の方向は必ず図面のビューから判断すること
- 正面図で円が見える → その穴は「奥行き方向（Z軸）」に貫通
- 平面図（上面図）で円が見える → その穴は「高さ方向（Y軸）」に貫通
- 側面図で円が見える → その穴は「幅方向（X軸）」に貫通
- CadQuery の `.hole()` はデフォルトで Z 方向に穴を開ける
  - X方向の穴: `.faces(">X")` or `.faces("<X")` のワークプレーンで `.hole()`
  - Y方向の穴: `.faces(">Y")` or `.faces("<Y")` のワークプレーンで `.hole()`
  - Z方向の穴: `.faces(">Z")` or `.faces("<Z")` のワークプレーンで `.hole()`

【スクリプト作成ルール】
- `import cadquery as cq` から始まる完全に実行可能なコードを書く
- 各フィーチャーに `# Feature-NNN:` コメントを付ける（穴には方向も記載）
- すべての数値は意味のある定数として抽出する（マジックナンバー禁止）
- 最終結果を `result` 変数に代入する
- 点線は内部形状として解釈する
- show_object() は使用禁止（ヘッドレス実行環境のため）
- `import math` は使用可能

【出力フォーマット(JSON)】
{{
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
