"""Step Functions Step 5: Validate generated 3D model."""
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

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")


def lambda_handler(event: dict, context) -> dict:
    """Validate the generated 3D model quality.

    Input:
        {"session_id": "...", "node_id": "...", ...}
    Output:
        {"session_id": "...", "node_id": "...", "validation": {...}}
    """
    session_id = event["session_id"]
    node_id = event["node_id"]
    logger.info("Validating node %s", node_id)
    send_progress(session_id, "VALIDATING", 88, "品質検証中...")

    # Update session status
    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET #s = :status, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "VALIDATING",
            ":now": int(time.time()),
        },
    )

    nodes_table = dynamodb.Table(NODES_TABLE)
    resp = nodes_table.get_item(Key={"node_id": node_id})
    node = resp.get("Item")
    if not node:
        raise ValueError(f"Node not found: {node_id}")

    validation_result = {
        "is_valid": True,
        "checks": [],
    }

    # Check 1: CadQuery script exists
    script = node.get("cadquery_script", "")
    if script:
        validation_result["checks"].append({
            "name": "script_present",
            "passed": True,
        })
    else:
        validation_result["checks"].append({
            "name": "script_present",
            "passed": False,
            "detail": "No CadQuery script",
        })
        validation_result["is_valid"] = False

    # Check 2: STEP file exists in S3
    step_key = node.get("step_s3_key", "")
    if step_key:
        try:
            s3_client.head_object(Bucket=ARTIFACTS_BUCKET, Key=step_key)
            validation_result["checks"].append({
                "name": "step_file_exists",
                "passed": True,
            })
        except s3_client.exceptions.ClientError:
            validation_result["checks"].append({
                "name": "step_file_exists",
                "passed": False,
                "detail": f"STEP file not found: {step_key}",
            })
            validation_result["is_valid"] = False
    else:
        validation_result["checks"].append({
            "name": "step_file_exists",
            "passed": False,
            "detail": "No STEP file key",
        })
        validation_result["is_valid"] = False

    # Check 3: glTF file exists
    gltf_key = node.get("gltf_s3_key", "")
    if gltf_key:
        try:
            s3_client.head_object(Bucket=ARTIFACTS_BUCKET, Key=gltf_key)
            validation_result["checks"].append({
                "name": "gltf_file_exists",
                "passed": True,
            })
        except s3_client.exceptions.ClientError:
            validation_result["checks"].append({
                "name": "gltf_file_exists",
                "passed": False,
                "detail": f"glTF file not found: {gltf_key}",
            })

    # Check 4: Confidence scores
    confidence_map = node.get("confidence_map", {})
    if confidence_map:
        low_confidence = [k for k, v in confidence_map.items() if isinstance(v, (int, float)) and v < 0.5]
        validation_result["checks"].append({
            "name": "confidence_check",
            "passed": len(low_confidence) == 0,
            "detail": f"Low confidence features: {low_confidence}" if low_confidence else "All features above threshold",
        })

    # Script validation
    if script:
        from common.script_validator import validate_cadquery_script, ScriptValidationError

        try:
            validate_cadquery_script(script)
            validation_result["checks"].append({
                "name": "script_safety",
                "passed": True,
            })
        except ScriptValidationError as e:
            validation_result["checks"].append({
                "name": "script_safety",
                "passed": False,
                "detail": str(e),
            })

    logger.info("Validation result for node %s: %s", node_id, validation_result["is_valid"])
    return {
        "session_id": session_id,
        "node_id": node_id,
        "validation": validation_result,
    }
