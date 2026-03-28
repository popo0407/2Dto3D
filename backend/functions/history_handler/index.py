from __future__ import annotations

import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "")
NODES_TABLE = os.environ.get("NODES_TABLE", "")
ARTIFACTS_BUCKET = os.environ.get("ARTIFACTS_BUCKET", "")

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")


def lambda_handler(event: dict, context) -> dict:
    http_method = event.get("httpMethod", "")
    resource = event.get("resource", "")

    if resource == "/sessions" and http_method == "GET":
        return _list_sessions(event)
    elif resource == "/sessions/{session_id}" and http_method == "GET":
        return _get_session(event)
    elif resource == "/sessions/{session_id}" and http_method == "DELETE":
        return _delete_session(event)
    elif resource.endswith("/nodes") and http_method == "GET":
        return _list_nodes(event)
    elif resource.endswith("{node_id}") and http_method == "GET":
        return _get_node(event)
    elif resource.endswith("/revert") and http_method == "POST":
        return _revert_to_node(event)
    elif resource.endswith("/download") and http_method == "GET":
        return _download(event)
    elif resource.endswith("/validate") and http_method == "GET":
        return _validate(event)

    return _response(400, {"error": "Invalid route"})


def _list_sessions(event: dict) -> dict:
    user_id = _get_user_id(event)
    table = dynamodb.Table(SESSIONS_TABLE)
    resp = table.query(
        IndexName="user_id-index",
        KeyConditionExpression=boto3.dynamodb.conditions.Key("user_id").eq(user_id),
        ScanIndexForward=False,
    )
    return _response(200, {"sessions": resp.get("Items", [])})


def _get_session(event: dict) -> dict:
    session_id = event["pathParameters"]["session_id"]
    table = dynamodb.Table(SESSIONS_TABLE)
    resp = table.get_item(Key={"session_id": session_id})
    item = resp.get("Item")
    if not item:
        return _response(404, {"error": "Session not found"})
    return _response(200, item)


def _delete_session(event: dict) -> dict:
    session_id = event["pathParameters"]["session_id"]
    table = dynamodb.Table(SESSIONS_TABLE)
    table.delete_item(Key={"session_id": session_id})
    logger.info("Session deleted: %s", session_id)
    return _response(200, {"deleted": session_id})


def _list_nodes(event: dict) -> dict:
    session_id = event["pathParameters"]["session_id"]
    table = dynamodb.Table(NODES_TABLE)
    resp = table.query(
        IndexName="session_id-index",
        KeyConditionExpression=boto3.dynamodb.conditions.Key("session_id").eq(
            session_id
        ),
        ScanIndexForward=True,
    )
    return _response(200, {"nodes": resp.get("Items", [])})


def _get_node(event: dict) -> dict:
    node_id = event["pathParameters"]["node_id"]
    table = dynamodb.Table(NODES_TABLE)
    resp = table.get_item(Key={"node_id": node_id})
    item = resp.get("Item")
    if not item:
        return _response(404, {"error": "Node not found"})
    return _response(200, item)


def _revert_to_node(event: dict) -> dict:
    session_id = event["pathParameters"]["session_id"]
    node_id = event["pathParameters"]["node_id"]

    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    import time

    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET current_node_id = :nid, updated_at = :now",
        ExpressionAttributeValues={
            ":nid": node_id,
            ":now": int(time.time()),
        },
    )
    logger.info("Reverted session %s to node %s", session_id, node_id)
    return _response(200, {"session_id": session_id, "current_node_id": node_id})


def _download(event: dict) -> dict:
    node_id = event["pathParameters"]["node_id"]
    fmt = event.get("queryStringParameters", {}).get("format", "gltf")

    table = dynamodb.Table(NODES_TABLE)
    resp = table.get_item(Key={"node_id": node_id})
    item = resp.get("Item")
    if not item:
        return _response(404, {"error": "Node not found"})

    s3_key = item.get("gltf_s3_key", "") if fmt == "gltf" else item.get("step_s3_key", "")
    if not s3_key:
        return _response(404, {"error": f"No {fmt} file available"})

    url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": ARTIFACTS_BUCKET, "Key": s3_key},
        ExpiresIn=3600,
    )
    return _response(200, {"download_url": url, "format": fmt})


def _validate(event: dict) -> dict:
    node_id = event["pathParameters"]["node_id"]
    table = dynamodb.Table(NODES_TABLE)
    resp = table.get_item(Key={"node_id": node_id})
    item = resp.get("Item")
    if not item:
        return _response(404, {"error": "Node not found"})

    return _response(200, {
        "node_id": node_id,
        "confidence_map": item.get("confidence_map", {}),
        "validation": "pending",
    })


def _get_user_id(event: dict) -> str:
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
    )
    return claims.get("sub", "anonymous")


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
