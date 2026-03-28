"""Pipeline error handler: catches Step Functions errors and notifies frontend via WebSocket."""
from __future__ import annotations

import json
import logging
import os
import time

import boto3
from boto3.dynamodb.conditions import Attr

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")


def _send_error_notification(session_id: str, error_msg: str) -> None:
    api_id = os.environ.get("WEBSOCKET_API_ID", "")
    connections_table_name = os.environ.get("CONNECTIONS_TABLE", "")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    stage = os.environ.get("ENV_NAME", "dev")
    if not api_id or not connections_table_name:
        return
    try:
        table = dynamodb.Table(connections_table_name)
        resp = table.scan(FilterExpression=Attr("session_id").eq(session_id))
        connections = resp.get("Items", [])
        if not connections:
            return
        endpoint_url = f"https://{api_id}.execute-api.{region}.amazonaws.com/{stage}"
        apigw = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint_url)
        payload = json.dumps({
            "type": "PROCESSING_FAILED",
            "session_id": session_id,
            "error": error_msg,
        }).encode()
        for conn in connections:
            try:
                apigw.post_to_connection(ConnectionId=conn["connection_id"], Data=payload)
            except Exception:
                pass
    except Exception as e:
        logger.warning("Error notification failed: %s", e)


def lambda_handler(event: dict, context) -> dict:
    """Called when any pipeline step fails.

    Updates session status to FAILED and sends PROCESSING_FAILED via WebSocket.
    Step Functions passes: { session_id, ..., error: { Error, Cause } }
    """
    session_id = event.get("session_id", "")
    error_info = event.get("error", {})

    if isinstance(error_info, dict):
        cause = str(error_info.get("Cause", str(error_info)))[:500]
        error_code = error_info.get("Error", "UnknownError")
    else:
        cause = str(error_info)[:500]
        error_code = "UnknownError"

    logger.error(
        "Pipeline error for session %s: [%s] %s",
        session_id,
        error_code,
        cause,
    )

    if session_id:
        try:
            sessions_table = dynamodb.Table(os.environ.get("SESSIONS_TABLE", ""))
            sessions_table.update_item(
                Key={"session_id": session_id},
                UpdateExpression="SET #s = :status, updated_at = :now",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":status": "FAILED",
                    ":now": int(time.time()),
                },
            )
            _send_error_notification(
                session_id,
                f"パイプライン処理に失敗しました（{error_code}）。CloudWatchログをご確認ください。",
            )
        except Exception as e:
            logger.error("Error notification processing failed: %s", e)

    return {"session_id": session_id, "notified": bool(session_id)}
