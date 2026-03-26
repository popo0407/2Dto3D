"""Step Functions Step 4: Optimize generated 3D model.

Post-processes CadQuery output - converts STEP to glTF for web preview.
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
ARTIFACTS_BUCKET = os.environ.get("ARTIFACTS_BUCKET", "")
PREVIEWS_BUCKET = os.environ.get("PREVIEWS_BUCKET", "")

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")


def lambda_handler(event: dict, context) -> dict:
    """Optimize and convert 3D artifacts.

    Input:
        {"session_id": "...", "node_id": "...", ...}
    Output:
        {"session_id": "...", "node_id": "...", "optimized": true}
    """
    session_id = event["session_id"]
    node_id = event["node_id"]
    send_progress(session_id, "OPTIMIZING", 75, "形状最適化中...")
    logger.info("Optimizing node %s", node_id)

    # Update session status
    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET #s = :status, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "OPTIMIZING",
            ":now": int(time.time()),
        },
    )

    nodes_table = dynamodb.Table(NODES_TABLE)
    resp = nodes_table.get_item(Key={"node_id": node_id})
    node = resp.get("Item")
    if not node:
        raise ValueError(f"Node not found: {node_id}")

    step_key = node.get("step_s3_key", "")
    gltf_key = node.get("gltf_s3_key", "")

    optimized = False

    # If STEP file exists, generate a preview-optimized copy
    if step_key:
        try:
            preview_key = f"previews/{session_id}/{node_id}/preview.gltf"

            if gltf_key:
                # Copy glTF to previews bucket for CDN serving
                s3_client.copy_object(
                    CopySource={"Bucket": ARTIFACTS_BUCKET, "Key": gltf_key},
                    Bucket=PREVIEWS_BUCKET,
                    Key=preview_key,
                    ContentType="model/gltf+json",
                )
                optimized = True
                logger.info("Copied glTF to previews: %s", preview_key)
            else:
                logger.warning("No glTF for node %s, skipping preview copy", node_id)
        except Exception as e:
            logger.error("Optimization error for node %s: %s", node_id, e)
            raise

    # Update node metadata
    if optimized:
        nodes_table.update_item(
            Key={"node_id": node_id},
            UpdateExpression="SET preview_s3_key = :pk",
            ExpressionAttributeValues={
                ":pk": preview_key,
            },
        )

    logger.info("Optimization complete for node %s, optimized=%s", node_id, optimized)
    return {
        "session_id": session_id,
        "node_id": node_id,
        "optimized": optimized,
    }
