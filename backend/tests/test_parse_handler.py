"""Tests for parse_handler Lambda."""
from __future__ import annotations

import json
import importlib
import time

import pytest
import boto3
from moto import mock_aws

from tests.conftest import make_api_event


DXF_SAMPLE = """0
SECTION
2
ENTITIES
0
LINE
0
CIRCLE
0
LINE
0
ENDSEC
0
EOF
"""


@mock_aws
def test_parse_handler_with_dxf(dynamodb_tables, s3_buckets):
    """Parse handler processes DXF files and creates initial node."""
    # Upload a DXF file to S3
    s3_buckets.put_object(
        Bucket="test-uploads",
        Key="sess-001/file1.dxf",
        Body=DXF_SAMPLE.encode(),
    )

    # Seed session
    table = dynamodb_tables.Table("test-sessions")
    now = int(time.time())
    table.put_item(Item={
        "session_id": "sess-001",
        "user_id": "user-1",
        "project_name": "DXF Test",
        "status": "PROCESSING",
        "current_node_id": "",
        "input_files": ["sess-001/file1.dxf"],
        "created_at": now,
        "updated_at": now,
        "ttl": now + 86400,
    })

    import backend.functions.parse_handler.index as module
    importlib.reload(module)

    result = module.lambda_handler({"session_id": "sess-001"}, None)

    assert result["session_id"] == "sess-001"
    assert "node_id" in result
    assert result["parsed_data"]["file_count"] == 1
    assert result["parsed_data"]["files"][0]["type"] == "vector_cad"

    # Verify entity counts
    entities = result["parsed_data"]["files"][0]["entities"]
    assert entities["entity_counts"]["LINE"] == 2
    assert entities["entity_counts"]["CIRCLE"] == 1


@mock_aws
def test_parse_handler_with_image(dynamodb_tables, s3_buckets):
    """Parse handler handles image files."""
    table = dynamodb_tables.Table("test-sessions")
    now = int(time.time())
    table.put_item(Item={
        "session_id": "sess-002",
        "user_id": "user-1",
        "project_name": "Image Test",
        "status": "PROCESSING",
        "current_node_id": "",
        "input_files": ["sess-002/drawing.png"],
        "created_at": now,
        "updated_at": now,
        "ttl": now + 86400,
    })

    import backend.functions.parse_handler.index as module
    importlib.reload(module)

    result = module.lambda_handler({"session_id": "sess-002"}, None)

    assert result["session_id"] == "sess-002"
    assert result["parsed_data"]["image_keys"] == ["sess-002/drawing.png"]


@mock_aws
def test_parse_handler_missing_session(dynamodb_tables, s3_buckets):
    """Parse handler raises on missing session."""
    import backend.functions.parse_handler.index as module
    importlib.reload(module)

    with pytest.raises(ValueError, match="Session not found"):
        module.lambda_handler({"session_id": "nonexistent"}, None)


@mock_aws
def test_parse_handler_no_files(dynamodb_tables, s3_buckets):
    """Parse handler raises when session has no input files."""
    table = dynamodb_tables.Table("test-sessions")
    now = int(time.time())
    table.put_item(Item={
        "session_id": "sess-003",
        "user_id": "user-1",
        "project_name": "Empty",
        "status": "PROCESSING",
        "current_node_id": "",
        "input_files": [],
        "created_at": now,
        "updated_at": now,
        "ttl": now + 86400,
    })

    import backend.functions.parse_handler.index as module
    importlib.reload(module)

    with pytest.raises(ValueError, match="No input files"):
        module.lambda_handler({"session_id": "sess-003"}, None)
