from __future__ import annotations

import json
import logging
import os
import time
import uuid

import boto3
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "")
UPLOADS_BUCKET = os.environ.get("UPLOADS_BUCKET", "")
AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-1")

dynamodb = boto3.resource("dynamodb")
# SigV4 + 仮想ホスト形式で署名することでリージョン固有エンドポイントURLを生成する。
# グローバルエンドポイント (s3.amazonaws.com) を使うと CORS プリフライトが
# バケットのリージョンへリダイレクトされず 500 になるため明示的に指定する。
s3_client = boto3.client(
    "s3",
    region_name=AWS_REGION,
    config=Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"},
    ),
)
sqs_client = boto3.client("sqs")

ALLOWED_EXTENSIONS = {".dxf", ".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


def lambda_handler(event: dict, context) -> dict:
    http_method = event.get("httpMethod", "")
    resource = event.get("resource", "")

    if resource == "/sessions" and http_method == "POST":
        return _create_session(event)
    elif resource == "/sessions/{session_id}/upload" and http_method == "POST":
        return _presigned_upload(event)
    elif resource == "/sessions/{session_id}/process" and http_method == "POST":
        return _start_processing(event)
    elif resource == "/sessions/{session_id}/drawing" and http_method == "GET":
        return _get_drawing(event)

    return _response(400, {"error": "Invalid route"})


def _create_session(event: dict) -> dict:
    user_id = _get_user_id(event)
    body = json.loads(event.get("body") or "{}")
    project_name = body.get("project_name", "Untitled")
    drawing_notes: str = body.get("drawing_notes", "").strip()

    session_id = str(uuid.uuid4())
    now = int(time.time())

    item = {
        "session_id": session_id,
        "user_id": user_id,
        "project_name": project_name,
        "status": "UPLOADING",
        "current_node_id": "",
        "input_files": [],
        "input_file_descriptions": {},
        "drawing_notes": drawing_notes,
        "created_at": now,
        "updated_at": now,
        "ttl": now + 90 * 86400,
    }

    table = dynamodb.Table(SESSIONS_TABLE)
    table.put_item(Item=item)

    logger.info("Session created: %s", session_id)
    return _response(201, item)


def _presigned_upload(event: dict) -> dict:
    session_id = event["pathParameters"]["session_id"]
    body = json.loads(event.get("body") or "{}")
    filename: str = body.get("filename", "")

    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return _response(400, {"error": f"Unsupported file type: {ext}"})

    s3_key = f"{session_id}/{uuid.uuid4()}{ext}"

    presigned = s3_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": UPLOADS_BUCKET,
            "Key": s3_key,
            "ContentType": body.get("content_type", "application/octet-stream"),
        },
        ExpiresIn=600,
    )

    # Register file (and optional description) in session
    description: str = body.get("description", "").strip()
    table = dynamodb.Table(SESSIONS_TABLE)

    update_expr = "SET input_files = list_append(if_not_exists(input_files, :empty), :file), updated_at = :now"
    expr_values: dict = {
        ":file": [s3_key],
        ":empty": [],
        ":now": int(time.time()),
    }

    if description:
        # Merge into input_file_descriptions map: {s3_key: description}
        update_expr += ", input_file_descriptions.#k = :desc"
        table.update_item(
            Key={"session_id": session_id},
            UpdateExpression="SET input_files = list_append(if_not_exists(input_files, :empty), :file),"
                             " input_file_descriptions = if_not_exists(input_file_descriptions, :emptymap),"
                             " updated_at = :now",
            ExpressionAttributeValues={
                ":file": [s3_key],
                ":empty": [],
                ":emptymap": {},
                ":now": int(time.time()),
            },
        )
        # Second update to add the specific key into the map
        table.update_item(
            Key={"session_id": session_id},
            UpdateExpression="SET input_file_descriptions.#k = :desc",
            ExpressionAttributeNames={"#k": s3_key},
            ExpressionAttributeValues={":desc": description},
        )
    else:
        table.update_item(
            Key={"session_id": session_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
        )

    logger.info("Presigned URL generated for session %s: %s", session_id, s3_key)
    return _response(200, {"upload_url": presigned, "s3_key": s3_key})


def _start_processing(event: dict) -> dict:
    session_id = event["pathParameters"]["session_id"]
    body = json.loads(event.get("body") or "{}")
    drawing_notes: str = body.get("drawing_notes", "").strip()

    table = dynamodb.Table(SESSIONS_TABLE)

    update_expr = "SET #s = :status, updated_at = :now"
    expr_values: dict = {
        ":status": "PROCESSING",
        ":now": int(time.time()),
    }
    if drawing_notes:
        update_expr += ", drawing_notes = :notes"
        expr_values[":notes"] = drawing_notes

    table.update_item(
        Key={"session_id": session_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues=expr_values,
    )

    queue_url = os.environ.get("PROCESSING_QUEUE_URL", "")
    if queue_url:
        sqs_client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"session_id": session_id}),
        )

    logger.info("Processing started for session %s", session_id)
    return _response(200, {"session_id": session_id, "status": "PROCESSING"})


def _get_drawing(event: dict) -> dict:
    """Return a presigned GET URL for the session's first uploaded drawing."""
    session_id = event["pathParameters"]["session_id"]
    table = dynamodb.Table(SESSIONS_TABLE)
    resp = table.get_item(Key={"session_id": session_id})
    session = resp.get("Item")
    if not session:
        return _response(404, {"error": "Session not found"})
    input_files = session.get("input_files", [])
    if not input_files:
        return _response(404, {"error": "No drawing found for this session"})
    s3_key = input_files[0]
    try:
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": UPLOADS_BUCKET, "Key": s3_key},
            ExpiresIn=3600,
        )
    except Exception as exc:
        logger.error("Failed to generate presigned GET URL for %s: %s", s3_key, exc)
        return _response(500, {"error": "Could not generate drawing URL"})
    return _response(200, {"url": url, "s3_key": s3_key})


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
