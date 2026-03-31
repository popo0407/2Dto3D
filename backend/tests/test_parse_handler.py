"""Tests for parse_handler Lambda."""
from __future__ import annotations

import io
import importlib
import time

import pytest
import boto3
import ezdxf
from moto import mock_aws

from tests.conftest import make_api_event


def _make_simple_dxf() -> bytes:
    """Create a minimal DXF with LINE and CIRCLE entities (no DIMENSION)."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0))
    msp.add_line((0, 0), (0, 10))
    msp.add_circle((5, 5), radius=3)
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


def _make_dxf_with_dimensions() -> bytes:
    """Create a DXF with LINE + DIMENSION entities."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    # Two lines forming an L-shape
    msp.add_line((0, 0), (100, 0))
    msp.add_line((0, 0), (0, 60))
    # Linear dimension for the horizontal line
    msp.add_linear_dim(base=(50, -10), p1=(0, 0), p2=(100, 0)).render()
    # Linear dimension for the vertical line
    msp.add_linear_dim(base=(-10, 30), p1=(0, 0), p2=(0, 60), angle=90).render()
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


@mock_aws
def test_parse_handler_with_dxf(dynamodb_tables, s3_buckets):
    """Parse handler processes DXF files and creates initial node."""
    s3_buckets.put_object(
        Bucket="test-uploads",
        Key="sess-001/file1.dxf",
        Body=_make_simple_dxf(),
    )

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

    entities = result["parsed_data"]["files"][0]["entities"]
    assert entities["entity_counts"]["LINE"] == 2
    assert entities["entity_counts"]["CIRCLE"] == 1
    assert entities["dimension_count"] == 0


@mock_aws
def test_parse_handler_dxf_dimensions(dynamodb_tables, s3_buckets):
    """Parse handler extracts DIMENSION entities and stores them in drawing_elements table."""
    s3_buckets.put_object(
        Bucket="test-uploads",
        Key="sess-dim/drawing.dxf",
        Body=_make_dxf_with_dimensions(),
    )

    table = dynamodb_tables.Table("test-sessions")
    now = int(time.time())
    table.put_item(Item={
        "session_id": "sess-dim",
        "user_id": "user-1",
        "project_name": "DXF Dimension Test",
        "status": "PROCESSING",
        "current_node_id": "",
        "input_files": ["sess-dim/drawing.dxf"],
        "created_at": now,
        "updated_at": now,
        "ttl": now + 86400,
    })

    import backend.functions.parse_handler.index as module
    importlib.reload(module)

    result = module.lambda_handler({"session_id": "sess-dim"}, None)

    # Verify parsed_data contains dimension info
    file_data = result["parsed_data"]["files"][0]
    assert file_data["entities"]["dimension_count"] == 2
    assert len(file_data["dxf_dimensions"]) == 2

    dims = file_data["dxf_dimensions"]
    assert dims[0]["dim_type"] == "linear"
    assert dims[0]["measurement"] is not None
    # Horizontal dimension should measure ~100
    assert abs(dims[0]["measurement"] - 100.0) < 0.01
    # Vertical dimension should measure ~60
    assert abs(dims[1]["measurement"] - 60.0) < 0.01

    # Verify elements stored in drawing_elements table
    elements_table = dynamodb_tables.Table("test-drawing-elements")
    resp = elements_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("drawing_id").eq("sess-dim"),
    )
    items = resp["Items"]
    assert len(items) == 2
    assert items[0]["element_seq"] == "DXF-DIM-0001"
    assert items[0]["element_type"] == "dimension"
    assert items[0]["source"] == "dxf_parse"
    assert items[0]["node_id"] == result["node_id"]


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
