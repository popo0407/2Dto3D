"""Tests for dimension_extract_handler."""
from __future__ import annotations

import json
import importlib
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest
import boto3
from moto import mock_aws


MOCK_AI_RESPONSE = json.dumps([
    {
        "element_type": "box",
        "feature_label": "Feature-001: base_body",
        "dimensions": {"width": 100.0, "height": 60.0, "depth": 20.0},
        "position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "orientation": "XY",
        "cq_fragment": "result = cq.Workplane('XY').box(100, 60, 20)",
        "confidence": 0.95,
        "ai_reasoning": "Width/height/depth explicitly noted on drawing",
    },
    {
        "element_type": "hole",
        "feature_label": "Hole-001: Φ6 through +Z",
        "dimensions": {"diameter": 6.0, "depth": 20.0},
        "position": {"x": 30.0, "y": 15.0, "z": 0.0},
        "orientation": "+Z",
        "cq_fragment": 'result = result.faces(">Z").workplane().pushPoints([(30,15)]).hole(6)',
        "confidence": 0.70,
        "ai_reasoning": "Diameter from Φ6 annotation, position uncertain",
    },
])


@mock_aws
def test_extract_stores_elements(dynamodb_tables, s3_buckets):
    """dimension_extract_handler stores elements in DynamoDB with correct keys."""
    # Setup session
    sessions = dynamodb_tables.Table("test-sessions")
    sessions.put_item(Item={
        "session_id": "sess-001",
        "user_id": "user-001",
        "status": "AI_ANALYZING",
        "input_files": [],
        "pending_verify_comment": "",
        "created_at": 1000,
        "updated_at": 1000,
        "ttl": 9999999,
    })

    nodes = dynamodb_tables.Table("test-nodes")
    nodes.put_item(Item={
        "node_id": "node-001",
        "session_id": "sess-001",
        "cadquery_script": "",
        "created_at": 1000,
    })

    with patch("common.bedrock_client.get_bedrock_client") as mock_bedrock, \
         patch("common.ws_notify.send_progress"):
        mock_client = MagicMock()
        mock_client.invoke_multimodal.return_value = MOCK_AI_RESPONSE
        mock_bedrock.return_value = mock_client

        import backend.functions.dimension_extract_handler.index as module
        importlib.reload(module)

        result = module.lambda_handler({
            "session_id": "sess-001",
            "node_id": "node-001",
            "cadquery_script": "result = cq.Workplane('XY').box(100, 60, 20)",
        }, None)

    assert result["session_id"] == "sess-001"
    assert result["total_elements"] == 2
    assert result["low_confidence_count"] == 1  # hole at 0.70 < 0.85
    assert result["iteration_count"] == 0

    # Verify elements in DynamoDB
    elements = dynamodb_tables.Table("test-drawing-elements")
    resp = elements.get_item(Key={"drawing_id": "sess-001", "element_seq": "0001"})
    item = resp["Item"]
    assert item["element_type"] == "box"
    assert item["feature_label"] == "Feature-001: base_body"
    assert item["is_verified"] is True  # 0.95 >= 0.85
    assert float(item["confidence"]) == 0.95

    resp2 = elements.get_item(Key={"drawing_id": "sess-001", "element_seq": "0002"})
    item2 = resp2["Item"]
    assert item2["element_type"] == "hole"
    assert item2["is_verified"] is False  # 0.70 < 0.85
    assert float(item2["confidence"]) == 0.70


@mock_aws
def test_extract_parses_json_in_markdown(dynamodb_tables, s3_buckets):
    """Handles AI response with JSON embedded in markdown code blocks."""
    sessions = dynamodb_tables.Table("test-sessions")
    sessions.put_item(Item={
        "session_id": "sess-002",
        "user_id": "user-001",
        "status": "AI_ANALYZING",
        "input_files": [],
        "pending_verify_comment": "",
        "created_at": 1000,
        "updated_at": 1000,
        "ttl": 9999999,
    })

    nodes = dynamodb_tables.Table("test-nodes")
    nodes.put_item(Item={
        "node_id": "node-002",
        "session_id": "sess-002",
        "cadquery_script": "",
        "created_at": 1000,
    })

    # AI response wrapped in markdown
    markdown_response = f"Here is the result:\n```json\n{MOCK_AI_RESPONSE}\n```\n"

    with patch("common.bedrock_client.get_bedrock_client") as mock_bedrock, \
         patch("common.ws_notify.send_progress"):
        mock_client = MagicMock()
        mock_client.invoke_multimodal.return_value = markdown_response
        mock_bedrock.return_value = mock_client

        import backend.functions.dimension_extract_handler.index as module
        importlib.reload(module)

        result = module.lambda_handler({
            "session_id": "sess-002",
            "node_id": "node-002",
            "cadquery_script": "result = cq.Workplane('XY').box(100, 60, 20)",
        }, None)

    assert result["total_elements"] == 2
