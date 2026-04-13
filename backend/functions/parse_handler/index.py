"""Step Functions Step 1: Parse uploaded 2D files.

Reads uploaded files from S3, extracts basic geometric information,
and prepares input for AI analysis.
"""
from __future__ import annotations

import json
import logging
import os
import io
from decimal import Decimal

import boto3
import ezdxf
from common.ws_notify import send_progress

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "")
NODES_TABLE = os.environ.get("NODES_TABLE", "")
DRAWING_ELEMENTS_TABLE = os.environ.get("DRAWING_ELEMENTS_TABLE", "")
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

    # チャット編集による再実行: parse/AI を省略して既存 node をそのまま次ステップへ渡す
    if event.get("restart_from_cadquery"):
        node_id = event["node_id"]
        logger.info("restart_from_cadquery=True — skipping parse for node %s", node_id)
        return {
            "session_id": session_id,
            "node_id": node_id,
            "parsed_data": {"files": [], "image_keys": [], "file_count": 0},
            "restart_from_cadquery": True,
        }

    send_progress(session_id, "PARSING", 10, "ファイルを解析中...")

    # Fetch session from DynamoDB
    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    resp = sessions_table.get_item(Key={"session_id": session_id})
    session = resp.get("Item")
    if not session:
        raise ValueError(f"Session not found: {session_id}")

    input_files: list[str] = session.get("input_files", [])
    if not input_files:
        raise ValueError(f"No input files for session: {session_id}")

    input_file_descriptions: dict = session.get("input_file_descriptions", {})
    drawing_notes: str = session.get("drawing_notes", "")

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
            dxf_result = _parse_dxf(s3_key)
            file_meta["entities"] = dxf_result
            file_meta["dxf_dimensions"] = dxf_result.get("dimensions", [])
        elif ext in ("png", "jpg", "jpeg", "tiff", "tif"):
            image_keys.append(s3_key)
            file_meta["entities"] = {"type": "raster_image"}
            desc = input_file_descriptions.get(s3_key, "")
            if desc:
                file_meta["description"] = desc

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

    # Store DXF DIMENSION entities to drawing_elements table
    for file_meta in parsed_files:
        dims = file_meta.get("dxf_dimensions", [])
        if dims:
            _store_dxf_dimensions(session_id, node_id, dims)

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
        "drawing_notes": drawing_notes,
        "image_descriptions": {k: v for k, v in input_file_descriptions.items() if k in image_keys},
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
    """Parse DXF file using ezdxf. Extract entity counts and DIMENSION entities."""
    try:
        obj = s3_client.get_object(Bucket=UPLOADS_BUCKET, Key=s3_key)
        content = obj["Body"].read()

        # ezdxf.read() expects a text stream
        text_stream = io.StringIO(content.decode("utf-8", errors="replace"))
        doc = ezdxf.read(text_stream)
        msp = doc.modelspace()

        entity_counts: dict[str, int] = {}
        dimensions: list[dict] = []
        seq = 0

        for entity in msp:
            etype = entity.dxftype()
            entity_counts[etype] = entity_counts.get(etype, 0) + 1

            if etype == "DIMENSION":
                seq += 1
                dim_data = _extract_dimension(entity, seq)
                dimensions.append(dim_data)

        return {
            "entity_counts": entity_counts,
            "total_entities": sum(entity_counts.values()),
            "dimensions": dimensions,
            "dimension_count": len(dimensions),
        }
    except Exception as e:
        logger.warning("DXF parse error for %s: %s", s3_key, e)
        return {"error": str(e)}


def _extract_dimension(entity, seq: int) -> dict:
    """Extract basic info from a single DIMENSION entity."""
    dxf = entity.dxf

    # Measurement value (actual dimension number)
    measurement = None
    try:
        measurement = round(entity.get_measurement(), 6)
    except Exception:
        pass

    # Dimension text override (user-specified text, may differ from measurement)
    text = dxf.get("text", "") or ""

    # Definition points
    defpoint = _point_to_list(dxf.get("defpoint", None))
    defpoint2 = _point_to_list(dxf.get("defpoint2", None))
    defpoint3 = _point_to_list(dxf.get("defpoint3", None))

    # Dimension type flag (0=linear, 1=aligned, 2=angular, 3=diameter, 4=radius, 5=angular3p, 6=ordinate)
    dimtype = dxf.get("dimtype", 0) & 0x0F  # lower 4 bits = type

    type_names = {
        0: "linear",
        1: "aligned",
        2: "angular",
        3: "diameter",
        4: "radius",
        5: "angular_3point",
        6: "ordinate",
    }

    return {
        "seq": seq,
        "dim_type": type_names.get(dimtype, f"unknown({dimtype})"),
        "measurement": measurement,
        "text_override": text,
        "defpoint": defpoint,
        "defpoint2": defpoint2,
        "defpoint3": defpoint3,
    }


def _point_to_list(point) -> list[float] | None:
    """Convert ezdxf Vec3 / tuple to a JSON-serializable list."""
    if point is None:
        return None
    try:
        return [round(float(v), 6) for v in point]
    except Exception:
        return None


def _store_dxf_dimensions(
    session_id: str, node_id: str, dimensions: list[dict]
) -> None:
    """Store extracted DXF DIMENSION entities into drawing_elements table."""
    if not DRAWING_ELEMENTS_TABLE:
        logger.warning("DRAWING_ELEMENTS_TABLE not configured, skipping DXF dimension storage")
        return

    table = dynamodb.Table(DRAWING_ELEMENTS_TABLE)
    import time

    now = int(time.time())

    for dim in dimensions:
        seq = dim["seq"]
        position = {}
        if dim.get("defpoint"):
            position = {
                "x": dim["defpoint"][0],
                "y": dim["defpoint"][1],
                "z": dim["defpoint"][2] if len(dim["defpoint"]) > 2 else 0.0,
            }

        # Build dimensions dict from measurement
        dim_values: dict = {}
        if dim.get("measurement") is not None:
            dim_values["value"] = dim["measurement"]
        if dim.get("text_override"):
            dim_values["text_override"] = dim["text_override"]

        item = {
            "drawing_id": session_id,
            "element_seq": f"DXF-DIM-{seq:04d}",
            "element_type": "dimension",
            "feature_label": f"DXF Dimension {seq} ({dim['dim_type']})",
            "dimensions": _decimalize(dim_values),
            "position": _decimalize(position),
            "orientation": "",
            "cq_fragment": "",
            "confidence": Decimal("0.5"),
            "is_verified": False,
            "ai_reasoning": f"DXF DIMENSION entity (type={dim['dim_type']})",
            "verification_count": 0,
            "node_id": node_id,
            "source": "dxf_parse",
            "defpoint2": _decimalize_list(dim.get("defpoint2")),
            "defpoint3": _decimalize_list(dim.get("defpoint3")),
            "ttl": now + 90 * 86400,
        }
        table.put_item(Item=item)

    logger.info(
        "Stored %d DXF dimensions for session %s (node %s)",
        len(dimensions),
        session_id,
        node_id,
    )


def _decimalize(d: dict) -> dict:
    """Convert float values in a dict to Decimal for DynamoDB."""
    return {k: Decimal(str(v)) if isinstance(v, float) else v for k, v in d.items()}


def _decimalize_list(lst: list | None) -> list | None:
    """Convert float values in a list to Decimal for DynamoDB."""
    if lst is None:
        return None
    return [Decimal(str(v)) if isinstance(v, float) else v for v in lst]
