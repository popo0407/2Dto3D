"""Step Functions Step 6: Notify user via WebSocket on pipeline completion."""
from __future__ import annotations

import json
import logging
import os
import time

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "")
NODES_TABLE = os.environ.get("NODES_TABLE", "")
CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE", "")
PREVIEWS_BUCKET = os.environ.get("PREVIEWS_BUCKET", "")
WEBSOCKET_API_ID = os.environ.get("WEBSOCKET_API_ID", "")
ENV_NAME = os.environ.get("ENV_NAME", "dev")

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")


def lambda_handler(event: dict, context) -> dict:
    """Send completion notification to connected WebSocket clients.

    Input:
        {"session_id": "...", "node_id": "...", "validation": {...}}
    Output:
        {"session_id": "...", "node_id": "...", "notified": true}
    """
    session_id = event["session_id"]
    node_id = event["node_id"]
    validation = event.get("validation", {})
    logger.info("Notifying completion for session %s, node %s", session_id, node_id)

    # Update session status to COMPLETED
    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    final_status = "COMPLETED" if validation.get("is_valid", False) else "COMPLETED_WITH_WARNINGS"
    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET #s = :status, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": final_status,
            ":now": int(time.time()),
        },
    )

    # Get node to find gltf preview URL
    nodes_table = dynamodb.Table(NODES_TABLE)
    node_resp = nodes_table.get_item(Key={"node_id": node_id})
    node = node_resp.get("Item", {})
    preview_key = node.get("preview_s3_key", "")
    gltf_url = ""
    if preview_key and PREVIEWS_BUCKET:
        try:
            gltf_url = s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": PREVIEWS_BUCKET, "Key": preview_key},
                ExpiresIn=3600,
            )
        except Exception as e:
            logger.warning("Failed to generate presigned URL for %s: %s", preview_key, e)

    # Find active connections for this session
    conn_table = dynamodb.Table(CONNECTIONS_TABLE)
    connections = _get_session_connections(conn_table, session_id)

    if not connections:
        logger.info("No active connections for session %s", session_id)
        return {"session_id": session_id, "node_id": node_id, "notified": False}

    # Send notification via API Gateway Management API
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    endpoint_url = f"https://{WEBSOCKET_API_ID}.execute-api.{region}.amazonaws.com/{ENV_NAME}"
    apigw_client = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint_url)

    message = json.dumps({
        "type": "PROCESSING_COMPLETE",
        "session_id": session_id,
        "node_id": node_id,
        "gltf_url": gltf_url,
        "ai_reasoning": node.get("ai_reasoning", ""),
        "status": final_status,
        "validation": validation,
    })

    notified_count = 0
    for conn in connections:
        connection_id = conn["connection_id"]
        try:
            apigw_client.post_to_connection(
                ConnectionId=connection_id,
                Data=message.encode("utf-8"),
            )
            notified_count += 1
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in ("GoneException", "410"):
                # Stale connection, clean up
                conn_table.delete_item(Key={"connection_id": connection_id})
                logger.info("Removed stale connection %s", connection_id)
            else:
                logger.error("Failed to notify %s: %s", connection_id, e)

    logger.info("Notified %d connections for session %s", notified_count, session_id)
    return {"session_id": session_id, "node_id": node_id, "notified": notified_count > 0}


def _get_session_connections(table, session_id: str) -> list[dict]:
    """Scan connections table for a session (small table, scan is acceptable)."""
    resp = table.scan(
        FilterExpression=boto3.dynamodb.conditions.Attr("session_id").eq(session_id),
    )
    return resp.get("Items", [])
