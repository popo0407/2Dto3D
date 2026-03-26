"""Step Functions Step 2: AI analysis via Amazon Bedrock.

Sends parsed file data and images to Claude for 3D model generation.
"""
from __future__ import annotations

import json
import logging
import os
import time

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

NODES_TABLE = os.environ.get("NODES_TABLE", "")
SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "")
UPLOADS_BUCKET = os.environ.get("UPLOADS_BUCKET", "")
USE_MOCK_AI = os.environ.get("USE_MOCK_AI", "true").lower() == "true"
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

    client = get_bedrock_client(use_mock=USE_MOCK_AI, region=BEDROCK_REGION)
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
        logger.warning("Script validation failed: %s", e)
        cadquery_script = ""

    # Update node with AI results
    nodes_table = dynamodb.Table(NODES_TABLE)
    nodes_table.update_item(
        Key={"node_id": node_id},
        UpdateExpression="SET cadquery_script = :script, confidence_map = :conf, ai_questions = :q",
        ExpressionAttributeValues={
            ":script": cadquery_script,
            ":conf": confidence_map,
            ":q": questions,
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

【出力要件】
1. CadQueryスクリプト（`import cadquery as cq` から始まる実行可能コード）
2. 各Feature の確度スコア（0.0～1.0）
3. 不明箇所への質問（最大5件）

【出力フォーマット(JSON)】
{{
  "cadquery_script": "import cadquery as cq\\n...",
  "confidence_map": {{"Feature-001": 0.95}},
  "questions": [{{"id": "Q1", "text": "...", "priority": "high"}}]
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
