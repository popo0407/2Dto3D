"""CadQuery Runner - Executes CadQuery scripts inside ECS Fargate.

Environment variables:
    SESSION_ID: Session identifier
    NODE_ID: Node identifier
    NODES_TABLE: DynamoDB table for nodes
    SESSIONS_TABLE: DynamoDB table for sessions
    ARTIFACTS_BUCKET: S3 bucket for output artifacts
"""
from __future__ import annotations

import ast
import json
import logging
import os
import sys
import tempfile
import time
import traceback

import boto3

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SESSION_ID = os.environ.get("SESSION_ID", "")
NODE_ID = os.environ.get("NODE_ID", "")
NODES_TABLE = os.environ.get("NODES_TABLE", "")
SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "")
ARTIFACTS_BUCKET = os.environ.get("ARTIFACTS_BUCKET", "")

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")


def _send_progress(session_id: str, step: str, progress: int, message: str) -> None:
    """Send a PROGRESS WebSocket message to all active connections for a session."""
    import json
    from boto3.dynamodb.conditions import Attr

    api_id = os.environ.get("WEBSOCKET_API_ID", "")
    connections_table_name = os.environ.get("CONNECTIONS_TABLE", "")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    stage = os.environ.get("ENV_NAME", "dev")

    if not api_id or not connections_table_name:
        logger.debug("WEBSOCKET_API_ID not set — skipping progress notification")
        return

    try:
        table = dynamodb.Table(connections_table_name)
        resp = table.scan(FilterExpression=Attr("session_id").eq(session_id))
        connections = resp.get("Items", [])
        if not connections:
            return

        endpoint_url = f"https://{api_id}.execute-api.{region}.amazonaws.com/{stage}"
        apigw = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint_url)
        payload = json.dumps(
            {"type": "PROGRESS", "session_id": session_id, "step": step, "progress": progress, "message": message}
        ).encode()

        for conn in connections:
            try:
                apigw.post_to_connection(ConnectionId=conn["connection_id"], Data=payload)
            except Exception:
                pass
    except Exception as exc:
        logger.warning("_send_progress failed: %s", exc)

# Dangerous modules/builtins that must not appear in CadQuery scripts
BLOCKED_IMPORTS = frozenset({"os", "subprocess", "sys", "shutil", "socket", "ctypes"})
BLOCKED_BUILTINS = frozenset({"eval", "exec", "__import__", "compile", "open"})


def validate_script(script: str) -> tuple[bool, list[str]]:
    """AST-based safety validation of CadQuery script."""
    errors: list[str] = []
    try:
        tree = ast.parse(script)
    except SyntaxError as e:
        return False, [f"SyntaxError: {e}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BLOCKED_IMPORTS:
                    errors.append(f"Blocked import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in BLOCKED_IMPORTS:
                errors.append(f"Blocked import: {node.module}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_BUILTINS:
                errors.append(f"Blocked builtin: {node.func.id}")

    return len(errors) == 0, errors


def execute_cadquery(script: str, work_dir: str) -> dict:
    """Execute CadQuery script and export STEP + glTF."""
    import cadquery as cq

    import math

    # No-op stubs for CadQuery GUI functions that AI may include
    def _noop(*args, **kwargs):
        pass

    # Execute script in restricted namespace.
    # __import__ is required for `import cadquery as cq` inside the script.
    # Security is enforced by validate_script() (AST check) before this call.
    namespace = {"cq": cq, "math": math, "show_object": _noop, "debug": _noop, "log": _noop, "__builtins__": {
        "__import__": __import__,
        "range": range, "len": len, "int": int, "float": float,
        "str": str, "list": list, "dict": dict, "tuple": tuple,
        "True": True, "False": False, "None": None,
        "print": print, "abs": abs, "min": min, "max": max,
        "round": round, "enumerate": enumerate, "zip": zip,
        "map": map, "filter": filter, "sorted": sorted,
        "isinstance": isinstance, "type": type, "bool": bool,
    }}

    exec(script, namespace)  # noqa: S102 - Script is validated before execution

    # Find the result variable (convention: 'result' or last CQ object)
    result = namespace.get("result")
    if result is None:
        # Look for any Workplane object
        for name, val in namespace.items():
            if isinstance(val, cq.Workplane) and not name.startswith("_"):
                result = val

    if result is None:
        raise RuntimeError("No CadQuery result found. Define a 'result' variable.")

    # Export STEP
    step_path = os.path.join(work_dir, "output.step")
    cq.exporters.export(result, step_path, exportType="STEP")

    # Export GLB via STL → trimesh → GLB pipeline (single binary, no external .bin)
    stl_path = os.path.join(work_dir, "output.stl")
    glb_path = os.path.join(work_dir, "output.glb")
    # High-resolution STL: small tolerances → smoother curved surfaces
    cq.exporters.export(
        result, stl_path, exportType="STL",
        tolerance=0.01,       # linear tolerance 0.01mm
        angularTolerance=0.1, # angular tolerance 0.1 radians (~6°)
    )

    import trimesh
    import numpy as np

    mesh = trimesh.load(stl_path)
    # Re-merge coplanar faces to reduce visual artifacts on flat surfaces
    if hasattr(mesh, 'merge_vertices'):
        mesh.merge_vertices()
    mesh.export(glb_path, file_type="glb")

    return {
        "step_path": step_path,
        "glb_path": glb_path,
        "step_size": os.path.getsize(step_path),
        "glb_size": os.path.getsize(glb_path),
    }


def upload_artifacts(work_dir_result: dict) -> dict:
    """Upload STEP and GLB files to S3."""
    step_key = f"artifacts/{SESSION_ID}/{NODE_ID}/output.step"
    glb_key = f"artifacts/{SESSION_ID}/{NODE_ID}/output.glb"

    s3_client.upload_file(
        work_dir_result["step_path"], ARTIFACTS_BUCKET, step_key,
        ExtraArgs={"ContentType": "application/step"},
    )
    s3_client.upload_file(
        work_dir_result["glb_path"], ARTIFACTS_BUCKET, glb_key,
        ExtraArgs={"ContentType": "model/gltf-binary"},
    )

    logger.info("Uploaded STEP (%d bytes) and GLB (%d bytes)",
                work_dir_result["step_size"], work_dir_result["glb_size"])

    return {"step_s3_key": step_key, "gltf_s3_key": glb_key}


def update_node(s3_keys: dict) -> None:
    """Update DynamoDB node with artifact S3 keys."""
    table = dynamodb.Table(NODES_TABLE)
    table.update_item(
        Key={"node_id": NODE_ID},
        UpdateExpression="SET step_s3_key = :sk, gltf_s3_key = :gk",
        ExpressionAttributeValues={
            ":sk": s3_keys["step_s3_key"],
            ":gk": s3_keys["gltf_s3_key"],
        },
    )


def update_session_status(status: str) -> None:
    """Update session status."""
    table = dynamodb.Table(SESSIONS_TABLE)
    table.update_item(
        Key={"session_id": SESSION_ID},
        UpdateExpression="SET #s = :status, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": status,
            ":now": int(time.time()),
        },
    )


def main() -> None:
    logger.info("CadQuery Runner started: session=%s, node=%s", SESSION_ID, NODE_ID)
    _send_progress(SESSION_ID, "BUILDING", 55, "3Dモデル構築中...")

    if not all([SESSION_ID, NODE_ID, NODES_TABLE, ARTIFACTS_BUCKET]):
        logger.error("Missing required environment variables")
        sys.exit(1)

    # Fetch node to get CadQuery script
    nodes_table = dynamodb.Table(NODES_TABLE)
    resp = nodes_table.get_item(Key={"node_id": NODE_ID})
    node = resp.get("Item")
    if not node:
        logger.error("Node not found: %s", NODE_ID)
        sys.exit(1)

    script = node.get("cadquery_script", "")
    if not script:
        logger.error("No CadQuery script in node %s", NODE_ID)
        sys.exit(1)

    # Validate script
    is_valid, errors = validate_script(script)
    if not is_valid:
        logger.error("Script validation failed: %s", errors)
        update_session_status("CADQUERY_ERROR")
        sys.exit(1)

    update_session_status("CADQUERY_RUNNING")

    try:
        with tempfile.TemporaryDirectory() as work_dir:
            logger.info("Executing CadQuery script (%d bytes)", len(script))
            result = execute_cadquery(script, work_dir)

            logger.info("Uploading artifacts to S3")
            s3_keys = upload_artifacts(result)

            logger.info("Updating node with artifact keys")
            update_node(s3_keys)

        update_session_status("CADQUERY_COMPLETE")
        logger.info("CadQuery Runner completed successfully")

    except Exception as e:
        logger.error("CadQuery execution failed: %s\n%s", e, traceback.format_exc())
        update_session_status("CADQUERY_ERROR")
        sys.exit(1)


if __name__ == "__main__":
    main()
