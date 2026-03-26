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
    # Extract user_id from query string or authorizer
    query_params = event.get("queryStringParameters") or {}
    user_id = query_params.get("user_id", "anonymous")

    table = dynamodb.Table(CONNECTIONS_TABLE)
    now = int(time.time())
    table.put_item(
        Item={
            "connection_id": connection_id,
            "user_id": user_id,
            "connected_at": now,
            "ttl": now + 24 * 3600,  # 24h TTL
        }
    )

    logger.info("WebSocket connected: %s (user: %s)", connection_id, user_id)
    return {"statusCode": 200, "body": "Connected"}


def disconnect_handler(event: dict, context) -> dict:
    """Handle WebSocket $disconnect event."""
    connection_id = event["requestContext"]["connectionId"]

    table = dynamodb.Table(CONNECTIONS_TABLE)
    table.delete_item(Key={"connection_id": connection_id})

    logger.info("WebSocket disconnected: %s", connection_id)
    return {"statusCode": 200, "body": "Disconnected"}
