"""Tests for dimension_extract_handler."""
from __future__ import annotations

import json
import importlib
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest
import boto3
from moto import mock_aws
from common.bedrock_client import InvokeResult


MOCK_AI_RESPONSE = json.dumps([
    {
        "element_type": "box",
        "feature_label": "Feature-001: base_body",
        "feature_spec": {},
        "dimensions": {"width": 100.0, "height": 60.0, "depth": 20.0},
        "position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "orientation": "XY",
        "cq_fragment": "result = cq.Workplane('XY').box(100, 60, 20)",
        "confidence": 0.95,
        "ai_reasoning": "Width/height/depth explicitly noted on drawing",
    },
    {
        "element_type": "hole_through",
        "feature_label": "Hole-001: Φ6 through +Z",
        "feature_spec": {"hole_type": "through", "diameter": 6.0},
        "dimensions": {"diameter": 6.0, "depth": 20.0},
        "position": {"x": 30.0, "y": 15.0, "z": 0.0},
        "orientation": "+Z",
        "cq_fragment": 'result = result.faces(">Z").workplane().pushPoints([(30,15)]).hole(6)',
        "confidence": 0.70,
        "ai_reasoning": "Diameter from Φ6 annotation, position uncertain",
    },
])

MOCK_AI_RESPONSE_WITH_TAPPED = json.dumps([
    {
        "element_type": "box",
        "feature_label": "Feature-001: base_body",
        "feature_spec": {},
        "dimensions": {"width": 80.0, "height": 50.0, "depth": 15.0},
        "position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "orientation": "XY",
        "cq_fragment": "result = cq.Workplane('XY').box(80, 50, 15)",
        "confidence": 0.95,
        "ai_reasoning": "Explicit dimensions on drawing",
    },
    {
        "element_type": "tapped_hole",
        "feature_label": "Hole-M6-01: M6 タップ穴 +Z",
        "feature_spec": {
            "hole_type": "tapped",
            "designation": "M6",
            "pitch": 1.0,
            "tap_depth": 12.0,
            "drill_diameter": 5.0,
            "through": False,
            "standard": "JIS",
        },
        "dimensions": {"diameter": 5.0, "depth": 12.0},
        "position": {"x": 20.0, "y": 10.0, "z": 0.0},
        "orientation": "+Z",
        "cq_fragment": 'result = result.faces(">Z").workplane().pushPoints([(20,10)]).hole(5.0, 12.0)',
        "confidence": 0.72,
        "ai_reasoning": "M6 annotation found; pitch from JIS B 0205",
    },
    {
        "element_type": "fillet",
        "feature_label": "Fillet-001: R2 edges |Z",
        "feature_spec": {"radius": 2.0, "edge_selector": "|Z", "quantity": 4},
        "dimensions": {"radius": 2.0},
        "position": {},
        "orientation": "",
        "cq_fragment": 'result = result.edges("|Z").fillet(2.0)',
        "confidence": 0.90,
        "ai_reasoning": "R2 fillet annotation on all vertical edges",
    },
    {
        "element_type": "chamfer",
        "feature_label": "Chamfer-001: C1 edge +Z",
        "feature_spec": {"distance": 1.0, "angle": 45.0, "edge_selector": ">Z", "quantity": 1},
        "dimensions": {"distance": 1.0},
        "position": {},
        "orientation": "",
        "cq_fragment": 'result = result.edges(">Z").chamfer(1.0)',
        "confidence": 0.88,
        "ai_reasoning": "C1 chamfer on top face edge",
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
         patch("common.ws_notify.send_progress"), \
         patch("common.ws_notify.send_token_usage"):
        mock_client = MagicMock()
        mock_client.invoke_multimodal.return_value = InvokeResult(text=MOCK_AI_RESPONSE, input_tokens=100, output_tokens=200)
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
    assert item["feature_spec"] == {}  # boxはfeature_spec空

    resp2 = elements.get_item(Key={"drawing_id": "sess-001", "element_seq": "0002"})
    item2 = resp2["Item"]
    assert item2["element_type"] == "hole_through"
    assert item2["is_verified"] is False  # 0.70 < 0.85
    assert float(item2["confidence"]) == 0.70
    assert item2["feature_spec"]["hole_type"] == "through"
    assert float(item2["feature_spec"]["diameter"]) == 6.0


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
         patch("common.ws_notify.send_progress"), \
         patch("common.ws_notify.send_token_usage"):
        mock_client = MagicMock()
        mock_client.invoke_multimodal.return_value = InvokeResult(text=markdown_response, input_tokens=100, output_tokens=200)
        mock_bedrock.return_value = mock_client

        import backend.functions.dimension_extract_handler.index as module
        importlib.reload(module)

        result = module.lambda_handler({
            "session_id": "sess-002",
            "node_id": "node-002",
            "cadquery_script": "result = cq.Workplane('XY').box(100, 60, 20)",
        }, None)

    assert result["total_elements"] == 2


@mock_aws
def test_extract_tapped_hole_fillet_chamfer(dynamodb_tables, s3_buckets):
    """tapped_hole/fillet/chamfer が feature_spec を含めて正しく保存される。"""
    sessions = dynamodb_tables.Table("test-sessions")
    sessions.put_item(Item={
        "session_id": "sess-003",
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
        "node_id": "node-003",
        "session_id": "sess-003",
        "cadquery_script": "",
        "created_at": 1000,
    })

    with patch("common.bedrock_client.get_bedrock_client") as mock_bedrock, \
         patch("common.ws_notify.send_progress"), \
         patch("common.ws_notify.send_token_usage"):
        mock_client = MagicMock()
        mock_client.invoke_multimodal.return_value = InvokeResult(text=MOCK_AI_RESPONSE_WITH_TAPPED, input_tokens=100, output_tokens=200)
        mock_bedrock.return_value = mock_client

        import backend.functions.dimension_extract_handler.index as module
        importlib.reload(module)

        result = module.lambda_handler({
            "session_id": "sess-003",
            "node_id": "node-003",
            "cadquery_script": "result = cq.Workplane('XY').box(80, 50, 15)",
        }, None)

    assert result["total_elements"] == 4
    # tapped_hole (0.72) が低確度、fillet (0.90) と chamfer (0.88) は高確度
    assert result["low_confidence_count"] == 1

    elements = dynamodb_tables.Table("test-drawing-elements")

    # tapped_hole の feature_spec を検証
    tap = elements.get_item(Key={"drawing_id": "sess-003", "element_seq": "0002"})["Item"]
    assert tap["element_type"] == "tapped_hole"
    assert tap["feature_spec"]["designation"] == "M6"
    assert float(tap["feature_spec"]["pitch"]) == 1.0
    assert float(tap["feature_spec"]["tap_depth"]) == 12.0
    assert float(tap["feature_spec"]["drill_diameter"]) == 5.0
    assert tap["feature_spec"]["standard"] == "JIS"
    assert tap["feature_spec"]["through"] is False
    assert tap["is_verified"] is False  # 0.72 < 0.85

    # fillet の feature_spec を検証
    fil = elements.get_item(Key={"drawing_id": "sess-003", "element_seq": "0003"})["Item"]
    assert fil["element_type"] == "fillet"
    assert float(fil["feature_spec"]["radius"]) == 2.0
    assert fil["feature_spec"]["edge_selector"] == "|Z"
    assert int(fil["feature_spec"]["quantity"]) == 4
    assert fil["is_verified"] is True  # 0.90 >= 0.85

    # chamfer の feature_spec を検証
    chm = elements.get_item(Key={"drawing_id": "sess-003", "element_seq": "0004"})["Item"]
    assert chm["element_type"] == "chamfer"
    assert float(chm["feature_spec"]["distance"]) == 1.0
    assert float(chm["feature_spec"]["angle"]) == 45.0
    assert chm["feature_spec"]["edge_selector"] == ">Z"
    assert chm["is_verified"] is True  # 0.88 >= 0.85
