"""Step Functions Step 2: AI analysis via Amazon Bedrock.

Sends parsed file data and images to Claude for 3D model generation.
"""
from __future__ import annotations

import json
import logging
import os
import time
from decimal import Decimal

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


def _to_decimal(obj):
    """DynamoDB は float 非対応のため再帰的に Decimal へ変換する。"""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(v) for v in obj]
    return obj


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
            "confidence_map": existing_node.get("confidence_map", {}),
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
    image_keys = parsed_data.get("image_keys", [])
    if image_keys:
        try:
            obj = s3_client.get_object(Bucket=UPLOADS_BUCKET, Key=image_keys[0])
            image_bytes = obj["Body"].read()
        except Exception as e:
            logger.warning("Failed to load image %s: %s", image_keys[0], e)

    # Build prompt
    prompt = _build_prompt(parsed_data)

    # Invoke AI
    from common.bedrock_client import get_bedrock_client

    client = get_bedrock_client(region=BEDROCK_REGION)
    raw_response = client.invoke_multimodal(
        prompt=prompt,
        image_bytes=image_bytes,
        context_json=parsed_data.get("files"),
    )

    # Parse AI response
    ai_output = _parse_ai_response(raw_response)
    cadquery_script = ai_output.get("cadquery_script", "")
    confidence_map = ai_output.get("confidence_map", {})
    questions = ai_output.get("questions", [])

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
        UpdateExpression="SET cadquery_script = :script, confidence_map = :conf, ai_questions = :q",
        ExpressionAttributeValues={
            ":script": cadquery_script,
            ":conf": _to_decimal(confidence_map),
            ":q": _to_decimal(questions),
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
        "confidence_map": confidence_map,
    }


def _build_prompt(parsed_data: dict) -> str:
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

【設計意図推論の指示】
1. 対称性の利用: 記載されていない半分は対称と扱い、完全形状を推定する
2. 標準フィーチャー認識: ネジ穴は規格寸法（JIS/ISO）に補正する
3. 製造制約の考慮: ドリル穴の底面は118°コーン底として処理する
4. Water-tight保証: 全面が閉じたソリッドになるよう補完する
5. 隠れ線処理: 点線は内部形状として解釈する
6. 寸法の優先順位: 記入寸法 > 計算寸法（スケールから算出）

【エンティティ解決（Entity Resolution）の指示】
- 画像上の「円」とエンティティJSON内の「CIRCLE」を紐付け、同一形状かどうか判定する
- 矛盾検出: 三面図（正面・平面・側面）の寸法が一致しない場合は質問リストに追加する
- 判読不能箇所: OCRで読み取れない寸法は確度スコア0.5以下で記録し、質問を生成する

【スクリプト作成ルール】
- 各フィーチャーは `# Feature-NNN:` コメントで識別可能に記述する
- すべての数値は意味のある定数として抽出する（マジックナンバー禁止）
- コメントで出典図面・座標を記録する（トレーサビリティ）
- 修正は定数書き換えのみで対応可能な構造にする

【出力要件】
1. CadQueryスクリプト（`import cadquery as cq` から始まる実行可能コード）
2. 各Feature の確度スコア（0.0～1.0）
3. 不明箇所への質問（最大5件、priority: high/medium/low付き）

【出力フォーマット(JSON)】
{{
  "cadquery_script": "import cadquery as cq\\n...",
  "confidence_map": {{"Feature-001": 0.95, "Feature-002": 0.80}},
  "questions": [
    {{
      "id": "Q1",
      "feature_id": "Feature-002",
      "text": "正面図と側面図で穴の深さが矛盾しています。どちらが正しいですか？",
      "confidence": 0.45,
      "priority": "high"
    }}
  ]
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
        "confidence_map": {},
        "questions": [],
    }
