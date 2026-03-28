"""Mock CadQuery runner for dev environment (enableFargate=false).

Creates placeholder GLTF/STEP artifacts without running actual CadQuery,
then sends BUILDING progress via WebSocket.
Called as a Lambda from Step Functions instead of ECS Fargate in dev.
"""
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
s3_client = boto3.client("s3")

# Minimal valid glTF 2.0 (empty scene — enough for dev smoke tests)
PLACEHOLDER_GLTF = json.dumps({
    "asset": {"version": "2.0", "generator": "2Dto3D-dev-mock"},
    "scene": 0,
    "scenes": [{"nodes": []}],
})

PLACEHOLDER_STEP = (
    "ISO-10303-21;\n"
    "HEADER;\n"
    "FILE_DESCRIPTION(('2Dto3D dev placeholder'), '2;1');\n"
    "FILE_NAME('placeholder.step', '', '', (), '', '', '');\n"
    "FILE_SCHEMA(('AP214IS'));\n"
    "ENDSEC;\n"
    "DATA;\n"
    "ENDSEC;\n"
    "END-ISO-10303-21;\n"
)


def _send_progress(session_id: str, step: str, progress: int, message: str) -> None:
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
            "type": "PROGRESS",
            "session_id": session_id,
            "step": step,
            "progress": progress,
            "message": message,
        }).encode()
        for conn in connections:
            try:
                apigw.post_to_connection(ConnectionId=conn["connection_id"], Data=payload)
            except Exception:
                pass
    except Exception as e:
        logger.warning("_send_progress failed: %s", e)


def lambda_handler(event: dict, context) -> dict:
    """Generate placeholder artifacts and update DynamoDB for dev pipeline.

    Input: {"session_id": "...", "node_id": "..."}
    Output: {"session_id": "...", "node_id": "..."}
    """
    session_id = event["session_id"]
    node_id = event["node_id"]

    _send_progress(session_id, "BUILDING", 55, "3Dモデル構築中 (dev mock)...")

    artifacts_bucket = os.environ.get("ARTIFACTS_BUCKET", "")
    gltf_key = f"artifacts/{session_id}/{node_id}/output.gltf"
    step_key = f"artifacts/{session_id}/{node_id}/output.step"

    s3_client.put_object(
        Bucket=artifacts_bucket,
        Key=gltf_key,
        Body=PLACEHOLDER_GLTF.encode("utf-8"),
        ContentType="model/gltf+json",
    )
    s3_client.put_object(
        Bucket=artifacts_bucket,
        Key=step_key,
        Body=PLACEHOLDER_STEP.encode("utf-8"),
        ContentType="application/step",
    )

    nodes_table = dynamodb.Table(os.environ.get("NODES_TABLE", ""))
    nodes_table.update_item(
        Key={"node_id": node_id},
        UpdateExpression="SET step_s3_key = :sk, gltf_s3_key = :gk",
        ExpressionAttributeValues={":sk": step_key, ":gk": gltf_key},
    )

    sessions_table = dynamodb.Table(os.environ.get("SESSIONS_TABLE", ""))
    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET #s = :status, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "CADQUERY_COMPLETE",
            ":now": int(time.time()),
        },
    )

    logger.info("Mock CadQuery complete for session=%s, node=%s", session_id, node_id)
    return {"session_id": session_id, "node_id": node_id}
