"""Tests for upload_handler Lambda."""
from __future__ import annotations

import json
import importlib

import pytest
from moto import mock_aws

from tests.conftest import make_api_event


@mock_aws
def test_create_session(dynamodb_tables, s3_buckets):
    """POST /sessions creates a new session."""
    # Re-import to pick up mocked boto3
    import backend.functions.upload_handler.index as module
    importlib.reload(module)

    event = make_api_event(
        method="POST",
        resource="/sessions",
        body={"project_name": "テストプロジェクト"},
    )

    resp = module.lambda_handler(event, None)
    assert resp["statusCode"] == 201

    body = json.loads(resp["body"])
    assert body["project_name"] == "テストプロジェクト"
    assert body["status"] == "UPLOADING"
    assert "session_id" in body
    assert body["user_id"] == "test-user-123"


@mock_aws
def test_presigned_upload(dynamodb_tables, s3_buckets):
    """POST /sessions/{id}/upload generates a presigned URL."""
    import backend.functions.upload_handler.index as module
    importlib.reload(module)

    # Create session first
    create_event = make_api_event(
        method="POST",
        resource="/sessions",
        body={"project_name": "Test"},
    )
    create_resp = module.lambda_handler(create_event, None)
    session_id = json.loads(create_resp["body"])["session_id"]

    # Request presigned URL
    upload_event = make_api_event(
        method="POST",
        resource="/sessions/{session_id}/upload",
        path_params={"session_id": session_id},
        body={"filename": "drawing.dxf", "content_type": "application/dxf"},
    )

    resp = module.lambda_handler(upload_event, None)
    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    assert "upload_url" in body
    assert "s3_key" in body
    assert body["s3_key"].startswith(session_id)


@mock_aws
def test_presigned_upload_invalid_extension(dynamodb_tables, s3_buckets):
    """POST /sessions/{id}/upload rejects unsupported file types."""
    import backend.functions.upload_handler.index as module
    importlib.reload(module)

    event = make_api_event(
        method="POST",
        resource="/sessions/{session_id}/upload",
        path_params={"session_id": "fake-id"},
        body={"filename": "malware.exe"},
    )

    resp = module.lambda_handler(event, None)
    assert resp["statusCode"] == 400
    assert "Unsupported" in json.loads(resp["body"])["error"]


@mock_aws
def test_start_processing(dynamodb_tables, s3_buckets):
    """POST /sessions/{id}/process updates status to PROCESSING."""
    import backend.functions.upload_handler.index as module
    importlib.reload(module)

    # Create session
    create_resp = module.lambda_handler(
        make_api_event(method="POST", resource="/sessions", body={"project_name": "P"}),
        None,
    )
    session_id = json.loads(create_resp["body"])["session_id"]

    # Start processing
    proc_event = make_api_event(
        method="POST",
        resource="/sessions/{session_id}/process",
        path_params={"session_id": session_id},
    )
    resp = module.lambda_handler(proc_event, None)
    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    assert body["status"] == "PROCESSING"


@mock_aws
def test_invalid_route(dynamodb_tables, s3_buckets):
    """Unknown route returns 400."""
    import backend.functions.upload_handler.index as module
    importlib.reload(module)

    event = make_api_event(method="GET", resource="/unknown")
    resp = module.lambda_handler(event, None)
    assert resp["statusCode"] == 400
