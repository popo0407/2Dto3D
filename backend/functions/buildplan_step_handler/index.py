"""BuildPlan step handler: CRUD operations, modifications, and step execution.

Routes:
  GET  /build-plans/{plan_id}/steps                    → list steps
  GET  /build-plans/{plan_id}/steps/{step_seq}         → get step detail
  POST /build-plans/{plan_id}/steps/{step_seq}/modify  → modify step (params or NL)
  POST /build-plans/{plan_id}/execute                  → execute from a specific step
  GET  /build-plans/{plan_id}/preview/{step_seq}       → get preview URL
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "")
NODES_TABLE = os.environ.get("NODES_TABLE", "")
BUILD_PLANS_TABLE = os.environ.get("BUILD_PLANS_TABLE", "")
BUILD_STEPS_TABLE = os.environ.get("BUILD_STEPS_TABLE", "")
UPLOADS_BUCKET = os.environ.get("UPLOADS_BUCKET", "")
ARTIFACTS_BUCKET = os.environ.get("ARTIFACTS_BUCKET", "")
PREVIEWS_BUCKET = os.environ.get("PREVIEWS_BUCKET", "")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "ap-northeast-1")
BUILDPLAN_WORKER_FUNCTION_NAME = os.environ.get("BUILDPLAN_WORKER_FUNCTION_NAME", "")

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")
lambda_client = boto3.client("lambda")

# Minimal valid glTF 2.0 for dev mock
PLACEHOLDER_GLTF = json.dumps({
    "asset": {"version": "2.0", "generator": "2Dto3D-buildplan-mock"},
    "scene": 0,
    "scenes": [{"nodes": []}],
})

PLACEHOLDER_STEP_FILE = (
    "ISO-10303-21;\nHEADER;\n"
    "FILE_DESCRIPTION(('2Dto3D buildplan checkpoint'), '2;1');\n"
    "FILE_NAME('checkpoint.step', '', '', (), '', '', '');\n"
    "FILE_SCHEMA(('AP214IS'));\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
)


def lambda_handler(event: dict, context) -> dict:
    """Route requests based on resource and method."""
    http_method = event.get("httpMethod", "")
    resource = event.get("resource", "")

    plan_id = (event.get("pathParameters") or {}).get("plan_id", "")

    # GET /build-plans/{plan_id} — plan status for polling
    if resource == "/build-plans/{plan_id}" and http_method == "GET":
        return _get_plan(plan_id)

    # GET /build-plans/{plan_id}/steps
    if resource.endswith("/steps") and http_method == "GET":
        return _list_steps(plan_id)

    # GET /build-plans/{plan_id}/steps/{step_seq}
    step_seq = (event.get("pathParameters") or {}).get("step_seq", "")
    if "/steps/" in resource and http_method == "GET" and step_seq:
        if "/preview/" in resource:
            return _get_preview(plan_id, step_seq)
        return _get_step(plan_id, step_seq)

    # POST /build-plans/{plan_id}/steps/{step_seq}/modify
    if resource.endswith("/modify") and http_method == "POST":
        body = json.loads(event.get("body") or "{}")
        return _modify_step(plan_id, step_seq, body)

    # POST /build-plans/{plan_id}/modify — batch multi-step modification
    if resource == "/build-plans/{plan_id}/modify" and http_method == "POST":
        body = json.loads(event.get("body") or "{}")
        return _batch_modify(plan_id, body)

    # POST /build-plans/{plan_id}/execute
    if resource.endswith("/execute") and http_method == "POST":
        body = json.loads(event.get("body") or "{}")
        return _execute_plan(plan_id, body)

    # GET /build-plans/{plan_id}/preview/{step_seq}
    if "/preview/" in resource and http_method == "GET":
        preview_seq = (event.get("pathParameters") or {}).get("step_seq", "")
        return _get_preview(plan_id, preview_seq)

    return _response(400, {"error": "Invalid route"})


# ---------------------------------------------------------------------------
# List steps
# ---------------------------------------------------------------------------

def _list_steps(plan_id: str) -> dict:
    """Return all steps for a build plan."""
    steps_table = dynamodb.Table(BUILD_STEPS_TABLE)
    resp = steps_table.query(
        KeyConditionExpression=Key("plan_id").eq(plan_id),
    )
    items = resp.get("Items", [])
    # Convert Decimal back to float for JSON serialization
    return _response(200, {"plan_id": plan_id, "steps": items})


# ---------------------------------------------------------------------------
# Get step detail
# ---------------------------------------------------------------------------

def _get_step(plan_id: str, step_seq: str) -> dict:
    """Return a single step by plan_id + step_seq."""
    steps_table = dynamodb.Table(BUILD_STEPS_TABLE)
    resp = steps_table.get_item(Key={"plan_id": plan_id, "step_seq": step_seq})
    item = resp.get("Item")
    if not item:
        return _response(404, {"error": "Step not found"})
    return _response(200, item)


# ---------------------------------------------------------------------------
# Get plan (status polling endpoint)
# ---------------------------------------------------------------------------

def _get_plan(plan_id: str) -> dict:
    """Return plan metadata including plan_status for frontend polling."""
    plans_table = dynamodb.Table(BUILD_PLANS_TABLE)
    resp = plans_table.get_item(Key={"plan_id": plan_id})
    plan = resp.get("Item")
    if not plan:
        return _response(404, {"error": "Plan not found"})
    return _response(200, _decimal_to_float_dict(plan))


# ---------------------------------------------------------------------------
# Modify step
# ---------------------------------------------------------------------------


def _modify_step(plan_id: str, step_seq: str, body: dict) -> dict:
    """Single-step modify: delegates to _batch_modify for code reuse."""
    new_params = body.get("parameters", {})
    instruction = body.get("instruction", "")
    mod: dict = {"step_seq": step_seq}
    if new_params:
        mod["parameters"] = new_params
    return _batch_modify(plan_id, {"modifications": [mod], "instruction": instruction})


def _batch_modify(plan_id: str, body: dict) -> dict:
    """Kick off async batch step modification via worker Lambda.

    Body:
    {
      "modifications": [{"step_seq": "0002", "parameters": {...}}, ...],
      "instruction": "..."  // optional NL instruction
    }
    Returns 202 immediately.
    """
    modifications: list[dict] = body.get("modifications", [])
    instruction = body.get("instruction", "")

    if not modifications and not instruction.strip():
        return _response(400, {"error": "modifications または instruction が必要です"})

    plans_table = dynamodb.Table(BUILD_PLANS_TABLE)
    plan_resp = plans_table.get_item(Key={"plan_id": plan_id})
    plan = plan_resp.get("Item")
    if not plan:
        return _response(404, {"error": "Plan not found"})

    session_id = plan.get("session_id", "")

    # Validate all step_seqs exist
    if modifications:
        steps_table = dynamodb.Table(BUILD_STEPS_TABLE)
        all_steps = _query_all_steps(plan_id, steps_table)
        existing_seqs = {s["step_seq"] for s in all_steps}
        for mod in modifications:
            seq = mod.get("step_seq", "")
            if seq and seq not in existing_seqs:
                return _response(404, {"error": f"Step {seq} not found"})

    plans_table.update_item(
        Key={"plan_id": plan_id},
        UpdateExpression="SET plan_status = :s, updated_at = :now",
        ExpressionAttributeValues={
            ":s": "modifying",
            ":now": int(time.time()),
        },
    )

    if not BUILDPLAN_WORKER_FUNCTION_NAME:
        return _response(500, {"error": "Worker function not configured"})

    lambda_client.invoke(
        FunctionName=BUILDPLAN_WORKER_FUNCTION_NAME,
        InvocationType="Event",
        Payload=json.dumps({
            "action": "modify",
            "plan_id": plan_id,
            "session_id": session_id,
            "modifications": modifications,
            "instruction": instruction,
        }).encode(),
    )

    logger.info("Batch modify kick-off: plan=%s, mods=%d", plan_id, len(modifications))
    return _response(202, {"status": "modifying", "plan_id": plan_id})





# ---------------------------------------------------------------------------
# Execute plan (from a specific step)
# ---------------------------------------------------------------------------

def _execute_plan(plan_id: str, body: dict) -> dict:
    """Execute BuildPlan from a specific step.

    Body: {"from_step": "0001"}  (defaults to first step if omitted)
    """
    from_step = body.get("from_step", "0001")

    # Load plan
    plans_table = dynamodb.Table(BUILD_PLANS_TABLE)
    plan_resp = plans_table.get_item(Key={"plan_id": plan_id})
    plan = plan_resp.get("Item")
    if not plan:
        return _response(404, {"error": "Plan not found"})

    session_id = plan.get("session_id", "")
    node_id = plan.get("node_id", "")

    from common.ws_notify import send_progress
    send_progress(session_id, "BUILDPLAN_EXECUTING", 10, "BuildPlan 実行中...")

    # Load all steps
    steps_table = dynamodb.Table(BUILD_STEPS_TABLE)
    all_steps = _query_all_steps(plan_id, steps_table)

    if not all_steps:
        return _response(400, {"error": "No steps found"})

    # Build accumulated CadQuery script up to each step
    accumulated_scripts = {}
    header = "import cadquery as cq\nimport math\n\n"

    for i, step in enumerate(all_steps):
        seq = step["step_seq"]
        cq_code = step.get("cq_code", "")

        if i == 0:
            accumulated_scripts[seq] = header + cq_code
        else:
            prev_seq = all_steps[i - 1]["step_seq"]
            accumulated_scripts[seq] = accumulated_scripts[prev_seq] + "\n\n" + cq_code

    # Execute each step from from_step onwards
    total = len(all_steps)
    executed_count = 0
    results = []

    for i, step in enumerate(all_steps):
        seq = step["step_seq"]
        if seq < from_step:
            # Skip already-executed steps
            continue

        progress = 10 + int(80 * (i + 1) / total)
        step_name = step.get("step_name", seq)
        send_progress(
            session_id, "BUILDPLAN_EXECUTING", progress,
            f"Step {seq}: {step_name} を実行中...",
        )

        # Execute accumulated script → generate checkpoint
        full_script = accumulated_scripts[seq]

        # Validate script
        from common.script_validator import validate_cadquery_script, ScriptValidationError
        try:
            validate_cadquery_script(full_script)
        except ScriptValidationError as e:
            logger.error("Step %s script validation failed: %s", seq, e)
            steps_table.update_item(
                Key={"plan_id": plan_id, "step_seq": seq},
                UpdateExpression="SET #st = :status, ai_reasoning = :reason",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":status": "failed",
                    ":reason": f"Script validation: {e}",
                },
            )
            results.append({"step_seq": seq, "status": "failed", "error": str(e)})
            continue

        # Generate checkpoint artifacts (dev mock)
        glb_key = f"previews/{session_id}/buildplan/{plan_id}/{seq}.glb"
        step_key = f"artifacts/{session_id}/buildplan/{plan_id}/{seq}.step"

        s3_client.put_object(
            Bucket=PREVIEWS_BUCKET, Key=glb_key,
            Body=PLACEHOLDER_GLTF.encode("utf-8"),
            ContentType="model/gltf+json",
        )
        s3_client.put_object(
            Bucket=ARTIFACTS_BUCKET, Key=step_key,
            Body=PLACEHOLDER_STEP_FILE.encode("utf-8"),
            ContentType="application/step",
        )

        # Update step in DynamoDB
        now = int(time.time())
        steps_table.update_item(
            Key={"plan_id": plan_id, "step_seq": seq},
            UpdateExpression=(
                "SET #st = :status, checkpoint_step_key = :sk, "
                "checkpoint_glb_key = :gk, executed_at = :now"
            ),
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":status": "completed",
                ":sk": step_key,
                ":gk": glb_key,
                ":now": now,
            },
        )

        executed_count += 1
        results.append({"step_seq": seq, "status": "completed"})

    # Generate final output from last step's accumulated script
    last_step = all_steps[-1]
    final_script = accumulated_scripts[last_step["step_seq"]]

    # Save final script to node
    nodes_table = dynamodb.Table(NODES_TABLE)
    nodes_table.update_item(
        Key={"node_id": node_id},
        UpdateExpression="SET cadquery_script = :script",
        ExpressionAttributeValues={":script": final_script},
    )

    # Generate final GLB for 3D viewer
    final_glb_key = f"previews/{session_id}/buildplan/{plan_id}/final.glb"
    final_step_key = f"artifacts/{session_id}/buildplan/{plan_id}/final.step"
    s3_client.put_object(
        Bucket=PREVIEWS_BUCKET, Key=final_glb_key,
        Body=PLACEHOLDER_GLTF.encode("utf-8"),
        ContentType="model/gltf+json",
    )
    s3_client.put_object(
        Bucket=ARTIFACTS_BUCKET, Key=final_step_key,
        Body=PLACEHOLDER_STEP_FILE.encode("utf-8"),
        ContentType="application/step",
    )

    # Update node with final artifact references
    nodes_table.update_item(
        Key={"node_id": node_id},
        UpdateExpression="SET gltf_s3_key = :gk, step_s3_key = :sk, preview_s3_key = :pk",
        ExpressionAttributeValues={
            ":gk": final_glb_key,
            ":sk": final_step_key,
            ":pk": final_glb_key,
        },
    )

    # Update plan status
    plans_table.update_item(
        Key={"plan_id": plan_id},
        UpdateExpression="SET plan_status = :status, current_step = :cs, updated_at = :now",
        ExpressionAttributeValues={
            ":status": "completed",
            ":cs": len(all_steps),
            ":now": int(time.time()),
        },
    )

    # Generate presigned URL for final preview
    gltf_url = ""
    try:
        gltf_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": PREVIEWS_BUCKET, "Key": final_glb_key},
            ExpiresIn=3600,
        )
    except Exception as e:
        logger.warning("Failed to generate presigned URL: %s", e)

    # Notify via WebSocket
    send_progress(session_id, "BUILDPLAN_COMPLETED", 100, "BuildPlan 実行完了")

    # Send completion via WebSocket
    _send_buildplan_complete(session_id, node_id, gltf_url, results)

    logger.info("Executed %d steps for plan %s", executed_count, plan_id)
    return _response(200, {
        "plan_id": plan_id,
        "executed_count": executed_count,
        "results": results,
        "gltf_url": gltf_url,
        "cadquery_script": final_script,
    })


# ---------------------------------------------------------------------------
# Get preview
# ---------------------------------------------------------------------------

def _get_preview(plan_id: str, step_seq: str) -> dict:
    """Return presigned URL for step's GLB preview."""
    steps_table = dynamodb.Table(BUILD_STEPS_TABLE)
    resp = steps_table.get_item(Key={"plan_id": plan_id, "step_seq": step_seq})
    item = resp.get("Item")
    if not item:
        return _response(404, {"error": "Step not found"})

    glb_key = item.get("checkpoint_glb_key", "")
    if not glb_key:
        return _response(404, {"error": "No preview available yet"})

    url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": PREVIEWS_BUCKET, "Key": glb_key},
        ExpiresIn=3600,
    )
    return _response(200, {"preview_url": url, "step_seq": step_seq})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _query_all_steps(plan_id: str, steps_table) -> list[dict]:
    """Query all steps for a plan, sorted by step_seq."""
    items = []
    resp = steps_table.query(
        KeyConditionExpression=Key("plan_id").eq(plan_id),
    )
    items.extend(resp.get("Items", []))
    while resp.get("LastEvaluatedKey"):
        resp = steps_table.query(
            KeyConditionExpression=Key("plan_id").eq(plan_id),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    return sorted(items, key=lambda x: x.get("step_seq", ""))


def _load_first_image(session: dict) -> tuple:
    """Load first image from session's input_files."""
    input_files = session.get("input_files", [])
    for f in input_files:
        ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
        if ext in ("png", "jpg", "jpeg", "tiff", "tif"):
            try:
                obj = s3_client.get_object(Bucket=UPLOADS_BUCKET, Key=f)
                media_map = {
                    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "tiff": "image/tiff", "tif": "image/tiff",
                }
                return obj["Body"].read(), media_map.get(ext, "image/png")
            except Exception as e:
                logger.warning("Failed to load image %s: %s", f, e)
    return None, "image/png"


def _parse_ai_response(raw: str) -> dict:
    """Parse JSON from AI response."""
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    import re
    json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", raw, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass

    logger.error("Failed to parse AI response: %s", raw[:200])
    return {}


def _float_to_decimal(obj):
    """Recursively convert float to Decimal for DynamoDB."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _float_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_float_to_decimal(i) for i in obj]
    return obj


def _decimal_to_float_dict(obj):
    """Recursively convert Decimal to float for JSON serialization."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_float_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_float_dict(i) for i in obj]
    return obj


def _send_buildplan_complete(session_id: str, node_id: str, gltf_url: str, results: list) -> None:
    """Send BUILDPLAN_COMPLETE WebSocket message."""
    api_id = os.environ.get("WEBSOCKET_API_ID", "")
    connections_table_name = os.environ.get("CONNECTIONS_TABLE", "")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    stage = os.environ.get("ENV_NAME", "dev")

    if not api_id or not connections_table_name:
        return

    try:
        table = dynamodb.Table(connections_table_name)
        from boto3.dynamodb.conditions import Attr
        resp = table.scan(FilterExpression=Attr("session_id").eq(session_id))
        connections = resp.get("Items", [])
        if not connections:
            return

        endpoint_url = f"https://{api_id}.execute-api.{region}.amazonaws.com/{stage}"
        apigw = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint_url)

        payload = json.dumps({
            "type": "BUILDPLAN_COMPLETE",
            "session_id": session_id,
            "node_id": node_id,
            "gltf_url": gltf_url,
            "results": results,
        }, default=str).encode()

        for conn in connections:
            try:
                apigw.post_to_connection(ConnectionId=conn["connection_id"], Data=payload)
            except Exception:
                pass
    except Exception as e:
        logger.warning("_send_buildplan_complete failed: %s", e)


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
        "body": json.dumps(body, default=str),
    }
