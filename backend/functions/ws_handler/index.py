"""WebSocket connection manager for real-time notifications."""
from __future__ import annotations

import json
import logging
import os
import time

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE", "")

dynamodb = boto3.resource("dynamodb")


def connect_handler(event: dict, context) -> dict:
    """Handle WebSocket $connect event."""
    connection_id = event["requestContext"]["connectionId"]
    query_params = event.get("queryStringParameters") or {}
    user_id = query_params.get("user_id", "anonymous")
    session_id = query_params.get("session_id", "")

    table = dynamodb.Table(CONNECTIONS_TABLE)
    now = int(time.time())
    table.put_item(
        Item={
            "connection_id": connection_id,
            "user_id": user_id,
            "session_id": session_id,
            "connected_at": now,
            "ttl": now + 24 * 3600,  # 24h TTL
        }
    )

    logger.info("WebSocket connected: %s (user: %s, session: %s)", connection_id, user_id, session_id)
    return {"statusCode": 200, "body": "Connected"}


def disconnect_handler(event: dict, context) -> dict:
    """Handle WebSocket $disconnect event."""
    connection_id = event["requestContext"]["connectionId"]

    table = dynamodb.Table(CONNECTIONS_TABLE)
    table.delete_item(Key={"connection_id": connection_id})

    logger.info("WebSocket disconnected: %s", connection_id)
    return {"statusCode": 200, "body": "Disconnected"}


def default_handler(event: dict, context) -> dict:
    """Handle WebSocket $default route (subscribe messages etc.)."""
    connection_id = event["requestContext"]["connectionId"]

    body_str = event.get("body") or "{}"
    try:
        body = json.loads(body_str)
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": "Invalid JSON"}

    action = body.get("action", "")

    if action == "subscribe":
        # Update connection record with session_id if provided
        session_id = body.get("session_id", "")
        if session_id:
            table = dynamodb.Table(CONNECTIONS_TABLE)
            table.update_item(
                Key={"connection_id": connection_id},
                UpdateExpression="SET session_id = :sid",
                ExpressionAttributeValues={":sid": session_id},
            )
            logger.info("Connection %s subscribed to session %s", connection_id, session_id)

    return {"statusCode": 200, "body": "OK"}
