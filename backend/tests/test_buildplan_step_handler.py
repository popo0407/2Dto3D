"""Tests for buildplan_step_handler Lambda."""
from __future__ import annotations

import json
import importlib
from decimal import Decimal

import pytest
from moto import mock_aws

from tests.conftest import make_api_event


def _seed_plan_and_steps(dynamodb_resource):
    """Insert a plan and two steps into test tables."""
    plans_table = dynamodb_resource.Table("test-build-plans")
    steps_table = dynamodb_resource.Table("test-build-steps")

    plan_id = "plan-001"
    session_id = "sess-001"
    node_id = "node-001"

    plans_table.put_item(Item={
        "plan_id": plan_id,
        "session_id": session_id,
        "node_id": node_id,
        "plan_status": "planned",
        "total_steps": 2,
        "current_step": 0,
        "reasoning": "Test plan",
        "created_at": 1000,
        "updated_at": 1000,
    })

    steps_table.put_item(Item={
        "plan_id": plan_id,
        "step_seq": "0001",
        "step_type": "base_body",
        "step_name": "基本直方体 100×50×10",
        "parameters": {
            "width": {"value": Decimal("100"), "unit": "mm", "source": "extracted", "confidence": Decimal("0.95")},
            "height": {"value": Decimal("50"), "unit": "mm", "source": "extracted", "confidence": Decimal("0.95")},
            "depth": {"value": Decimal("10"), "unit": "mm", "source": "extracted", "confidence": Decimal("0.9")},
        },
        "cq_code": "result = cq.Workplane('XY').box(100, 50, 10)",
        "dependencies": [],
        "group_id": "",
        "confidence": Decimal("0.95"),
        "status": "planned",
        "ai_reasoning": "外形寸法から",
        "checkpoint_step_key": "",
        "checkpoint_glb_key": "",
        "executed_at": 0,
    })

    steps_table.put_item(Item={
        "plan_id": plan_id,
        "step_seq": "0002",
        "step_type": "hole_through",
        "step_name": "Φ6 貫通穴",
        "parameters": {
            "diameter": {"value": Decimal("6"), "unit": "mm", "source": "extracted", "confidence": Decimal("0.92")},
            "face": {"value": ">Z", "unit": "", "source": "calculated", "confidence": Decimal("0.9")},
        },
        "cq_code": 'result = result.faces(">Z").workplane().hole(6.0)',
        "dependencies": ["0001"],
        "group_id": "hole_a",
        "confidence": Decimal("0.88"),
        "status": "planned",
        "ai_reasoning": "Φ6の穴",
        "checkpoint_step_key": "",
        "checkpoint_glb_key": "",
        "executed_at": 0,
    })

    # Also seed sessions and nodes tables
    sessions_table = dynamodb_resource.Table("test-sessions")
    sessions_table.put_item(Item={
        "session_id": session_id,
        "user_id": "test-user-123",
        "status": "BUILDPLAN_PLANNED",
        "input_files": [],
        "created_at": 1000,
    })

    nodes_table = dynamodb_resource.Table("test-nodes")
    nodes_table.put_item(Item={
        "node_id": node_id,
        "session_id": session_id,
        "type": "BUILDPLAN_INITIAL",
        "cadquery_script": "",
        "created_at": 1000,
    })

    return plan_id, session_id, node_id


@mock_aws
def test_list_steps(dynamodb_tables):
    """GET /build-plans/{plan_id}/steps returns all steps sorted by step_seq."""
    import backend.functions.buildplan_step_handler.index as module
    importlib.reload(module)

    plan_id, _, _ = _seed_plan_and_steps(dynamodb_tables)

    event = make_api_event(
        method="GET",
        resource="/build-plans/{plan_id}/steps",
        path_params={"plan_id": plan_id},
    )

    resp = module.lambda_handler(event, None)
    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    assert body["plan_id"] == plan_id
    assert len(body["steps"]) == 2
    # Verify ordering
    seqs = [s["step_seq"] for s in body["steps"]]
    assert seqs == ["0001", "0002"]


@mock_aws
def test_get_step_detail(dynamodb_tables):
    """GET /build-plans/{plan_id}/steps/{step_seq} returns step detail."""
    import backend.functions.buildplan_step_handler.index as module
    importlib.reload(module)

    plan_id, _, _ = _seed_plan_and_steps(dynamodb_tables)

    event = make_api_event(
        method="GET",
        resource="/build-plans/{plan_id}/steps/{step_seq}",
        path_params={"plan_id": plan_id, "step_seq": "0001"},
    )

    resp = module.lambda_handler(event, None)
    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    assert body["step_name"] == "基本直方体 100×50×10"
    assert body["step_type"] == "base_body"
    assert "parameters" in body


@mock_aws
def test_get_step_not_found(dynamodb_tables):
    """GET returns 404 for non-existent step."""
    import backend.functions.buildplan_step_handler.index as module
    importlib.reload(module)

    _seed_plan_and_steps(dynamodb_tables)

    event = make_api_event(
        method="GET",
        resource="/build-plans/{plan_id}/steps/{step_seq}",
        path_params={"plan_id": "plan-001", "step_seq": "9999"},
    )

    resp = module.lambda_handler(event, None)
    assert resp["statusCode"] == 404


@mock_aws
def test_execute_plan(dynamodb_tables, s3_buckets):
    """POST /build-plans/{plan_id}/execute runs all steps and creates artifacts."""
    import backend.functions.buildplan_step_handler.index as module
    importlib.reload(module)

    # Patch ws_notify to avoid WebSocket calls
    import backend.common.ws_notify as ws_mod
    ws_mod.send_progress = lambda *a, **kw: None
    ws_mod.send_token_usage = lambda *a, **kw: None

    plan_id, session_id, node_id = _seed_plan_and_steps(dynamodb_tables)

    event = make_api_event(
        method="POST",
        resource="/build-plans/{plan_id}/execute",
        path_params={"plan_id": plan_id},
        body={"from_step": "0001"},
    )

    resp = module.lambda_handler(event, None)
    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    assert body["plan_id"] == plan_id
    assert body["executed_count"] == 2
    assert len(body["results"]) == 2
    for r in body["results"]:
        assert r["status"] == "completed"

    # Verify final script contains both steps
    assert "cq.Workplane" in body["cadquery_script"]
    assert ".hole(6.0)" in body["cadquery_script"]


@mock_aws
def test_execute_plan_not_found(dynamodb_tables, s3_buckets):
    """POST execute returns 404 for non-existent plan."""
    import backend.functions.buildplan_step_handler.index as module
    importlib.reload(module)

    import backend.common.ws_notify as ws_mod
    ws_mod.send_progress = lambda *a, **kw: None

    event = make_api_event(
        method="POST",
        resource="/build-plans/{plan_id}/execute",
        path_params={"plan_id": "nonexistent"},
        body={},
    )

    resp = module.lambda_handler(event, None)
    assert resp["statusCode"] == 404


@mock_aws
def test_get_preview_no_checkpoint(dynamodb_tables):
    """GET preview returns 404 when no checkpoint exists."""
    import backend.functions.buildplan_step_handler.index as module
    importlib.reload(module)

    plan_id, _, _ = _seed_plan_and_steps(dynamodb_tables)

    event = make_api_event(
        method="GET",
        resource="/build-plans/{plan_id}/preview/{step_seq}",
        path_params={"plan_id": plan_id, "step_seq": "0001"},
    )

    resp = module.lambda_handler(event, None)
    assert resp["statusCode"] == 404
    body = json.loads(resp["body"])
    assert "No preview" in body["error"]


@mock_aws
def test_invalid_route(dynamodb_tables):
    """Invalid method/resource returns 400."""
    import backend.functions.buildplan_step_handler.index as module
    importlib.reload(module)

    event = make_api_event(
        method="DELETE",
        resource="/build-plans/{plan_id}/steps",
        path_params={"plan_id": "plan-001"},
    )

    resp = module.lambda_handler(event, None)
    assert resp["statusCode"] == 400
