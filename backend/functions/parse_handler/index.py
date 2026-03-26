"""Step Functions Step 1: Parse uploaded 2D files.

Reads uploaded files from S3, extracts basic geometric information,
and prepares input for AI analysis.
"""
from __future__ import annotations

import json
import logging
import os
import io

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "")
NODES_TABLE = os.environ.get("NODES_TABLE", "")
UPLOADS_BUCKET = os.environ.get("UPLOADS_BUCKET", "")

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")


def lambda_handler(event: dict, context) -> dict:
    """Parse uploaded files and extract geometric metadata.

    Input (from Step Functions):
        {"session_id": "..."}
    Output:
        {"session_id": "...", "node_id": "...", "parsed_data": {...}}
    """
    session_id = event["session_id"]
    logger.info("Parsing session %s", session_id)

    # Fetch session from DynamoDB
    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    resp = sessions_table.get_item(Key={"session_id": session_id})
    session = resp.get("Item")
    if not session:
        raise ValueError(f"Session not found: {session_id}")

    input_files: list[str] = session.get("input_files", [])
    if not input_files:
        raise ValueError(f"No input files for session: {session_id}")

    # Parse each uploaded file
    parsed_files = []
    image_keys = []
    for s3_key in input_files:
        ext = s3_key.rsplit(".", 1)[-1].lower() if "." in s3_key else ""
        file_meta = {
            "s3_key": s3_key,
            "extension": ext,
            "type": _classify_file(ext),
        }

        if ext == "dxf":
            file_meta["entities"] = _parse_dxf(s3_key)
        elif ext in ("png", "jpg", "jpeg", "tiff", "tif"):
            image_keys.append(s3_key)
            file_meta["entities"] = {"type": "raster_image"}

        parsed_files.append(file_meta)

    # Create initial node
    import uuid
    import time

    node_id = str(uuid.uuid4())
    now = int(time.time())

    nodes_table = dynamodb.Table(NODES_TABLE)
    node_item = {
        "node_id": node_id,
        "session_id": session_id,
        "parent_node_id": "",
        "type": "INITIAL",
        "cadquery_script": "",
        "diff_patch": "",
        "step_s3_key": "",
        "gltf_s3_key": "",
        "confidence_map": {},
        "user_message": "",
        "ai_questions": [],
        "created_at": now,
    }
    nodes_table.put_item(Item=node_item)

    # Update session
    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET current_node_id = :nid, #s = :status, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":nid": node_id,
            ":status": "PARSING",
            ":now": now,
        },
    )

    parsed_data = {
        "files": parsed_files,
        "image_keys": image_keys,
        "file_count": len(parsed_files),
    }

    logger.info(
        "Parsed %d files for session %s, node %s",
        len(parsed_files),
        session_id,
        node_id,
    )

    return {
        "session_id": session_id,
        "node_id": node_id,
        "parsed_data": parsed_data,
    }


def _classify_file(ext: str) -> str:
    if ext == "dxf":
        return "vector_cad"
    if ext == "pdf":
        return "document"
    if ext in ("png", "jpg", "jpeg", "tiff", "tif"):
        return "raster_image"
    return "unknown"


def _parse_dxf(s3_key: str) -> dict:
    """Basic DXF parsing - extract entity counts."""
    try:
        obj = s3_client.get_object(Bucket=UPLOADS_BUCKET, Key=s3_key)
        content = obj["Body"].read().decode("utf-8", errors="replace")

        entity_counts: dict[str, int] = {}
        in_entities = False
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped == "ENTITIES":
                in_entities = True
                continue
            if stripped == "ENDSEC" and in_entities:
                break
            if in_entities and stripped in ("LINE", "CIRCLE", "ARC", "LWPOLYLINE", "INSERT", "DIMENSION"):
                entity_counts[stripped] = entity_counts.get(stripped, 0) + 1

        return {"entity_counts": entity_counts, "total_entities": sum(entity_counts.values())}
    except Exception as e:
        logger.warning("DXF parse error for %s: %s", s3_key, e)
        return {"error": str(e)}
