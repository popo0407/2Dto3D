"""Tests for dimension_verify_handler."""
from __future__ import annotations

import json
import importlib
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest
import boto3
from moto import mock_aws


def _seed_session(dynamo_resource, session_id="sess-001", comment=""):
    """Insert a minimal session item."""
    table = dynamo_resource.Table("test-sessions")
    table.put_item(Item={
        "session_id": session_id,
        "user_id": "user-001",
        "status": "VERIFYING_DIMENSIONS",
        "input_files": [],
        "pending_verify_comment": comment,
        "created_at": 1000,
        "updated_at": 1000,
        "ttl": 9999999,
    })


def _seed_node(dynamo_resource, node_id="node-001", session_id="sess-001"):
    table = dynamo_resource.Table("test-nodes")
    table.put_item(Item={
        "node_id": node_id,
        "session_id": session_id,
        "cadquery_script": "",
        "created_at": 1000,
    })


def _seed_elements(dynamo_resource, session_id="sess-001"):
    """Seed a box (high-conf) and a tapped_hole (low-conf) element."""
    table = dynamo_resource.Table("test-drawing-elements")
    table.put_item(Item={
        "drawing_id": session_id,
        "element_seq": "0001",
        "element_type": "box",
        "feature_label": "Feature-001: base_body",
        "feature_spec": {},
        "dimensions": {"width": Decimal("100"), "height": Decimal("60"), "depth": Decimal("20")},
        "position": {"x": Decimal("0"), "y": Decimal("0"), "z": Decimal("0")},
        "orientation": "XY",
        "cq_fragment": "result = cq.Workplane('XY').box(100, 60, 20)",
        "confidence": Decimal("0.95"),
        "is_verified": True,
        "ai_reasoning": "Explicit dimensions",
        "verification_count": 0,
        "node_id": "node-001",
        "ttl": 9999999,
    })
    table.put_item(Item={
        "drawing_id": session_id,
        "element_seq": "0002",
        "element_type": "tapped_hole",
        "feature_label": "Hole-M6-01: M6 タップ穴 +Z",
        "feature_spec": {
            "hole_type": "tapped",
            "designation": "M6",
            "pitch": Decimal("1.0"),
            "tap_depth": Decimal("12.0"),
            "drill_diameter": Decimal("5.0"),
            "through": False,
            "standard": "JIS",
        },
        "dimensions": {"diameter": Decimal("5"), "depth": Decimal("12")},
        "position": {"x": Decimal("20"), "y": Decimal("10"), "z": Decimal("0")},
        "orientation": "+Z",
        "cq_fragment": 'result = result.faces(">Z").workplane().pushPoints([(20,10)]).hole(5.0, 12.0)',
        "confidence": Decimal("0.70"),
        "is_verified": False,
        "ai_reasoning": "M6 annotation found, position uncertain",
        "verification_count": 0,
        "node_id": "node-001",
        "ttl": 9999999,
    })


MOCK_VERIFY_RESPONSE = json.dumps([
    {
        "element_seq": "0002",
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
        "confidence": 0.92,
        "ai_reasoning": "M6 (JIS B 0205) 確認。下穴径5.0mm、タップ深さ12mm",
    }
])


MOCK_FINAL_ASSEMBLY_RESPONSE = json.dumps({
    "cadquery_script": "import cadquery as cq\nresult = cq.Workplane('XY').box(100, 60, 20)\nresult = result.faces('>Z').workplane().pushPoints([(30,15)]).hole(6)\n",
    "assembly_reasoning": "Base box with one through-hole",
})


@mock_aws
def test_verify_updates_confidence(dynamodb_tables, s3_buckets):
    """Normal verification iteration raises confidence of low-conf elements."""
    _seed_session(dynamodb_tables)
    _seed_node(dynamodb_tables)
    _seed_elements(dynamodb_tables)

    with patch("common.bedrock_client.get_bedrock_client") as mock_bedrock, \
         patch("common.ws_notify.send_progress"):
        mock_client = MagicMock()
        mock_client.invoke_multimodal.return_value = MOCK_VERIFY_RESPONSE
        mock_bedrock.return_value = mock_client

        import backend.functions.dimension_verify_handler.index as module
        importlib.reload(module)

        result = module.lambda_handler({
            "session_id": "sess-001",
            "node_id": "node-001",
            "iteration_count": 0,
            "is_final": False,
            "cadquery_script": "",
            "total_elements": 2,
            "low_confidence_count": 1,
        }, None)

    assert result["session_id"] == "sess-001"
    assert result["iteration_count"] == 1
    assert result["all_verified"] is True  # 0.92 >= 0.85
    assert result["low_confidence_count"] == 0

    # Verify DynamoDB was updated
    elem_table = dynamodb_tables.Table("test-drawing-elements")
    resp = elem_table.get_item(Key={"drawing_id": "sess-001", "element_seq": "0002"})
    item = resp["Item"]
    assert float(item["confidence"]) == pytest.approx(0.92)
    assert item["is_verified"] is True
    assert item["verification_count"] == 1
    # feature_spec が更新されていること
    assert item["feature_spec"]["designation"] == "M6"
    assert float(item["feature_spec"]["pitch"]) == 1.0


@mock_aws
def test_all_verified_skips_ai(dynamodb_tables, s3_buckets):
    """When all elements are already high-confidence, AI is not called."""
    _seed_session(dynamodb_tables)
    _seed_node(dynamodb_tables)

    # Seed only a high-confidence element
    table = dynamodb_tables.Table("test-drawing-elements")
    table.put_item(Item={
        "drawing_id": "sess-001",
        "element_seq": "0001",
        "element_type": "box",
        "feature_label": "Feature-001: base",
        "feature_spec": {},
        "dimensions": {"width": Decimal("50")},
        "position": {"x": Decimal("0")},
        "orientation": "XY",
        "cq_fragment": "result = cq.Workplane('XY').box(50, 50, 10)",
        "confidence": Decimal("0.95"),
        "is_verified": True,
        "ai_reasoning": "ok",
        "verification_count": 0,
        "node_id": "node-001",
        "ttl": 9999999,
    })

    with patch("common.bedrock_client.get_bedrock_client") as mock_bedrock, \
         patch("common.ws_notify.send_progress"):
        mock_client = MagicMock()
        mock_bedrock.return_value = mock_client

        import backend.functions.dimension_verify_handler.index as module
        importlib.reload(module)

        result = module.lambda_handler({
            "session_id": "sess-001",
            "node_id": "node-001",
            "iteration_count": 0,
            "is_final": False,
            "cadquery_script": "",
            "total_elements": 1,
            "low_confidence_count": 0,
        }, None)

    assert result["all_verified"] is True
    # Bedrock should NOT have been called
    mock_client.invoke_multimodal.assert_not_called()


@mock_aws
def test_human_comment_is_read_and_cleared(dynamodb_tables, s3_buckets):
    """Pending human comment is forwarded to AI and cleared from session."""
    _seed_session(dynamodb_tables, comment="穴位置はX=35です")
    _seed_node(dynamodb_tables)
    _seed_elements(dynamodb_tables)

    with patch("common.bedrock_client.get_bedrock_client") as mock_bedrock, \
         patch("common.ws_notify.send_progress"):
        mock_client = MagicMock()
        mock_client.invoke_multimodal.return_value = MOCK_VERIFY_RESPONSE
        mock_bedrock.return_value = mock_client

        import backend.functions.dimension_verify_handler.index as module
        importlib.reload(module)

        module.lambda_handler({
            "session_id": "sess-001",
            "node_id": "node-001",
            "iteration_count": 0,
            "is_final": False,
            "cadquery_script": "",
            "total_elements": 2,
            "low_confidence_count": 1,
        }, None)

    # Check that comment was included in the AI prompt
    call_args = mock_client.invoke_multimodal.call_args
    prompt = call_args.kwargs.get("prompt", call_args[1].get("prompt", ""))
    assert "穴位置はX=35です" in prompt

    # Check that comment was cleared from session
    sessions = dynamodb_tables.Table("test-sessions")
    resp = sessions.get_item(Key={"session_id": "sess-001"})
    assert resp["Item"]["pending_verify_comment"] == ""


@mock_aws
def test_final_assembly(dynamodb_tables, s3_buckets):
    """is_final=True triggers final assembly path and updates node."""
    _seed_session(dynamodb_tables)
    _seed_node(dynamodb_tables)
    _seed_elements(dynamodb_tables)

    with patch("common.bedrock_client.get_bedrock_client") as mock_bedrock, \
         patch("common.ws_notify.send_progress"), \
         patch("common.script_validator.validate_cadquery_script"):
        mock_client = MagicMock()
        mock_client.invoke_multimodal.return_value = MOCK_FINAL_ASSEMBLY_RESPONSE
        mock_bedrock.return_value = mock_client

        import backend.functions.dimension_verify_handler.index as module
        importlib.reload(module)

        result = module.lambda_handler({
            "session_id": "sess-001",
            "node_id": "node-001",
            "iteration_count": 4,
            "is_final": True,
            "cadquery_script": "",
            "total_elements": 2,
            "low_confidence_count": 0,
        }, None)

    assert result["all_verified"] is True
    assert "import cadquery as cq" in result["cadquery_script"]

    # Verify node was updated
    nodes = dynamodb_tables.Table("test-nodes")
    resp = nodes.get_item(Key={"node_id": "node-001"})
    assert "import cadquery as cq" in resp["Item"]["cadquery_script"]


@mock_aws
def test_assemble_script_template(dynamodb_tables, s3_buckets):
    """_assemble_script_template generates correct .faces() and .pushPoints()."""
    import backend.functions.dimension_verify_handler.index as module
    importlib.reload(module)

    elements = [
        {
            "element_type": "box",
            "feature_label": "Feature-001: base",
            "cq_fragment": "result = cq.Workplane('XY').box(100, 60, 20)",
            "dimensions": {},
            "position": {},
            "orientation": "XY",
            "confidence": Decimal("0.95"),
        },
        {
            "element_type": "hole",
            "feature_label": "Hole-001",
            "cq_fragment": "",
            "dimensions": {"diameter": Decimal("6"), "depth": Decimal("20")},
            "position": {"x": Decimal("30"), "y": Decimal("15")},
            "orientation": "+Z",
            "confidence": Decimal("0.90"),
        },
        {
            "element_type": "hole",
            "feature_label": "Hole-002",
            "cq_fragment": "",
            "dimensions": {"diameter": Decimal("6"), "depth": Decimal("20")},
            "position": {"x": Decimal("-30"), "y": Decimal("15")},
            "orientation": "+Z",
            "confidence": Decimal("0.88"),
        },
    ]

    script = module._assemble_script_template(elements)

    assert "import cadquery as cq" in script
    assert "result = cq.Workplane('XY').box(100, 60, 20)" in script
    # Both holes should be grouped into a single .pushPoints()
    assert ".pushPoints([(30.0, 15.0), (-30.0, 15.0)])" in script
    assert '.faces(">Z")' in script
    assert ".hole(6.0, 20.0)" in script
