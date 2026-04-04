"""BuildPlan kick-off handler: creates plan record and invokes worker asynchronously.

POST /sessions/{session_id}/build-plans
Returns 202 immediately. Actual AI work is done by buildplan_worker_handler.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "")
NODES_TABLE = os.environ.get("NODES_TABLE", "")
BUILD_PLANS_TABLE = os.environ.get("BUILD_PLANS_TABLE", "")
BUILDPLAN_WORKER_FUNCTION_NAME = os.environ.get("BUILDPLAN_WORKER_FUNCTION_NAME", "")

dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")


def lambda_handler(event: dict, context) -> dict:
    """Kick-off BuildPlan creation.

    POST /sessions/{session_id}/build-plans
    """
    http_method = event.get("httpMethod", "")
    if http_method != "POST":
        return _response(405, {"error": "Method not allowed"})

    session_id = event["pathParameters"]["session_id"]
    logger.info("Kicking off BuildPlan for session %s", session_id)

    # Validate session
    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    resp = sessions_table.get_item(Key={"session_id": session_id})
    session = resp.get("Item")
    if not session:
        return _response(404, {"error": "Session not found"})

    now = int(time.time())

    # Create history node
    nodes_table = dynamodb.Table(NODES_TABLE)
    node_id = str(uuid.uuid4())
    nodes_table.put_item(Item={
        "node_id": node_id,
        "session_id": session_id,
        "parent_node_id": session.get("current_node_id", ""),
        "type": "BUILDPLAN_INITIAL",
        "cadquery_script": "",
        "ai_reasoning": "",
        "created_at": now,
    })

    # Create plan record with status "creating"
    plan_id = str(uuid.uuid4())
    plans_table = dynamodb.Table(BUILD_PLANS_TABLE)
    plans_table.put_item(Item={
        "plan_id": plan_id,
        "session_id": session_id,
        "node_id": node_id,
        "plan_status": "creating",
        "total_steps": 0,
        "current_step": 0,
        "reasoning": "",
        "created_at": now,
        "updated_at": now,
        "ttl": now + 90 * 86400,
    })

    # Update session: mark as creating
    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET #s = :status, current_node_id = :nid, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "BUILDPLAN_CREATING",
            ":nid": node_id,
            ":now": now,
        },
    )

    # Invoke worker asynchronously (InvocationType="Event" → returns immediately)
    if not BUILDPLAN_WORKER_FUNCTION_NAME:
        logger.error("BUILDPLAN_WORKER_FUNCTION_NAME env var is not set")
        return _response(500, {"error": "Worker function not configured"})

    lambda_client.invoke(
        FunctionName=BUILDPLAN_WORKER_FUNCTION_NAME,
        InvocationType="Event",
        Payload=json.dumps({
            "action": "create",
            "plan_id": plan_id,
            "session_id": session_id,
            "node_id": node_id,
        }).encode(),
    )

    logger.info("BuildPlan kick-off complete: plan_id=%s, invoked worker", plan_id)
    return _response(202, {"plan_id": plan_id, "status": "creating"})


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
        "body": json.dumps(body),
    }
