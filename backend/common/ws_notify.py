"""Shared utility: send WebSocket PROGRESS notifications from pipeline step Lambdas."""
from __future__ import annotations

import json
import logging
import os

import boto3
from boto3.dynamodb.conditions import Attr

logger = logging.getLogger()


def send_progress(session_id: str, step: str, progress: int, message: str) -> None:
    """Broadcast a PROGRESS message to all active WebSocket connections for a session.

    Args:
        session_id: Session to notify.
        step: Step identifier (PARSING / AI_ANALYZING / BUILDING / OPTIMIZING / VALIDATING).
        progress: Integer 0-100.
        message: Human-readable Japanese status message shown in the UI.
    """
    api_id = os.environ.get("WEBSOCKET_API_ID", "")
    connections_table_name = os.environ.get("CONNECTIONS_TABLE", "")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    stage = os.environ.get("ENV_NAME", "dev")

    if not api_id or not connections_table_name:
        logger.debug("WEBSOCKET_API_ID or CONNECTIONS_TABLE not set — skipping progress notification")
        return

    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(connections_table_name)
        resp = table.scan(FilterExpression=Attr("session_id").eq(session_id))
        connections = resp.get("Items", [])

        if not connections:
            logger.info("No active WebSocket connections for session %s", session_id)
            return

        endpoint_url = f"https://{api_id}.execute-api.{region}.amazonaws.com/{stage}"
        apigw = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint_url)

        payload = json.dumps({
            "type": "PROGRESS",
            "session_id": session_id,
            "step": step,
            "progress": progress,
            "message": message,
        }).encode()

        for conn in connections:
            connection_id = conn["connection_id"]
            try:
                apigw.post_to_connection(ConnectionId=connection_id, Data=payload)
            except apigw.exceptions.GoneException:
                logger.info("Removing stale connection %s", connection_id)
                table.delete_item(Key={"connection_id": connection_id})
            except Exception as exc:
                logger.warning("Failed to push to connection %s: %s", connection_id, exc)

    except Exception as exc:
        logger.warning("send_progress failed for session %s: %s", session_id, exc)


def send_token_usage(session_id: str, step: str, input_tokens: int, output_tokens: int) -> None:
    """Broadcast a TOKEN_USAGE message to all active WebSocket connections for a session."""
    api_id = os.environ.get("WEBSOCKET_API_ID", "")
    connections_table_name = os.environ.get("CONNECTIONS_TABLE", "")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    stage = os.environ.get("ENV_NAME", "dev")

    if not api_id or not connections_table_name:
        return

    try:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(connections_table_name)
        resp = table.scan(FilterExpression=Attr("session_id").eq(session_id))
        connections = resp.get("Items", [])

        if not connections:
            return

        endpoint_url = f"https://{api_id}.execute-api.{region}.amazonaws.com/{stage}"
        apigw = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint_url)

        payload = json.dumps({
            "type": "TOKEN_USAGE",
            "session_id": session_id,
            "step": step,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }).encode()

        for conn in connections:
            connection_id = conn["connection_id"]
            try:
                apigw.post_to_connection(ConnectionId=connection_id, Data=payload)
            except apigw.exceptions.GoneException:
                table.delete_item(Key={"connection_id": connection_id})
            except Exception as exc:
                logger.warning("Failed to push token usage to connection %s: %s", connection_id, exc)

    except Exception as exc:
        logger.warning("send_token_usage failed for session %s: %s", session_id, exc)
