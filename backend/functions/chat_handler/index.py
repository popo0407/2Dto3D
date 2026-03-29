"""Chat handler: interactive AI conversation for model refinement."""
from __future__ import annotations

import json
import logging
import os
import time
import uuid

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "")
NODES_TABLE = os.environ.get("NODES_TABLE", "")
ARTIFACTS_BUCKET = os.environ.get("ARTIFACTS_BUCKET", "")
PROCESSING_QUEUE_URL = os.environ.get("PROCESSING_QUEUE_URL", "")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "ap-northeast-1")

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")
sqs_client = boto3.client("sqs")


def lambda_handler(event: dict, context) -> dict:
    """Handle chat message: create a new node with modified CadQuery script.

    POST /sessions/{session_id}/nodes/{node_id}/chat
    Body: {"message": "穴の直径を8mmに変更して"}
    """
    http_method = event.get("httpMethod", "")
    if http_method != "POST":
        return _response(405, {"error": "Method not allowed"})

    session_id = event["pathParameters"]["session_id"]
    node_id = event["pathParameters"]["node_id"]
    body = json.loads(event.get("body") or "{}")
    user_message = body.get("message", "")

    if not user_message:
        return _response(400, {"error": "message is required"})

    # Get parent node
    nodes_table = dynamodb.Table(NODES_TABLE)
    resp = nodes_table.get_item(Key={"node_id": node_id})
    parent_node = resp.get("Item")
    if not parent_node:
        return _response(404, {"error": "Node not found"})

    parent_script = parent_node.get("cadquery_script", "")

    # Build prompt for script modification
    prompt = f"""以下のCadQueryスクリプトを、ユーザーの指示に従い修正してください。

【現在のスクリプト】
```python
{parent_script}
```

【ユーザーの指示】
{user_message}

【穴・貫通穴の方向ルール】
- `.hole()` はデフォルトで現在のワークプレーンの法線方向に穴を開ける
- X方向の穴: `.faces(">X")` or `.faces("<X")` のワークプレーンで `.hole()`
- Y方向の穴: `.faces(">Y")` or `.faces("<Y")` のワークプレーンで `.hole()`
- Z方向の穴: `.faces(">Z")` or `.faces("<Z")` のワークプレーンで `.hole()`

【ルール】
- 修正後の完全なスクリプトを出力する（差分ではなく全体）
- show_object() は使用禁止
- 各フィーチャーに `# Feature-NNN:` コメントを付ける

【出力フォーマット(JSON)】
{{
  "cadquery_script": "修正後の完全なスクリプト",
  "diff_summary": "変更箇所の要約"
}}"""

    # Invoke AI
    from common.bedrock_client import get_bedrock_client

    try:
        client = get_bedrock_client(region=BEDROCK_REGION)
        raw_response = client.invoke_multimodal(prompt=prompt)
    except Exception as e:
        logger.error("Bedrock invocation failed: %s", e)
        return _response(502, {"error": f"AI invocation failed: {e}"})

    # Parse response
    ai_output = _parse_ai_response(raw_response)
    new_script = ai_output.get("cadquery_script", parent_script)

    # Validate
    from common.script_validator import validate_cadquery_script, ScriptValidationError

    try:
        validate_cadquery_script(new_script)
    except ScriptValidationError as e:
        return _response(400, {
            "error": "AI generated invalid script",
            "validation_errors": [str(e)],
        })

    # Create new child node
    new_node_id = str(uuid.uuid4())
    now = int(time.time())
    new_node = {
        "node_id": new_node_id,
        "session_id": session_id,
        "parent_node_id": node_id,
        "type": "CHAT_EDIT",
        "cadquery_script": new_script,
        "diff_patch": ai_output.get("diff_summary", ""),
        "step_s3_key": "",
        "gltf_s3_key": "",
        "user_message": user_message,
        "created_at": now,
    }
    nodes_table.put_item(Item=new_node)

    # Update session current node
    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET current_node_id = :nid, updated_at = :now",
        ExpressionAttributeValues={
            ":nid": new_node_id,
            ":now": now,
        },
    )

    # TODO: Optionally trigger CadQuery re-execution via SQS
    # 修正スクリプトで CadQuery パイプラインを再実行する
    if PROCESSING_QUEUE_URL:
        sqs_client.send_message(
            QueueUrl=PROCESSING_QUEUE_URL,
            MessageBody=json.dumps({
                "session_id": session_id,
                "node_id": new_node_id,
                "restart_from_cadquery": True,
            }),
        )
        logger.info("Triggered pipeline re-execution for node %s", new_node_id)
    else:
        logger.warning("PROCESSING_QUEUE_URL not set — pipeline re-execution skipped")

    logger.info("Chat created new node %s from parent %s", new_node_id, node_id)
    return _response(201, new_node)


def _parse_ai_response(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    import re

    json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", raw, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    return {"cadquery_script": "", "diff_summary": ""}


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
        "body": json.dumps(body, default=str),
    }
