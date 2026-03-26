"""Tests for history_handler Lambda."""
from __future__ import annotations

import json
import importlib

import pytest
import boto3
from moto import mock_aws

from tests.conftest import make_api_event


def _seed_session(dynamodb_tables, session_id="sess-001", user_id="test-user-123"):
    """Insert a test session."""
    import time

    table = dynamodb_tables.Table("test-sessions")
    now = int(time.time())
    table.put_item(Item={
        "session_id": session_id,
        "user_id": user_id,
        "project_name": "Test",
        "status": "COMPLETED",
        "current_node_id": "node-001",
        "input_files": [],
        "created_at": now,
        "updated_at": now,
        "ttl": now + 90 * 86400,
    })
    return session_id


def _seed_node(dynamodb_tables, node_id="node-001", session_id="sess-001"):
    """Insert a test node."""
    import time

    table = dynamodb_tables.Table("test-nodes")
    table.put_item(Item={
        "node_id": node_id,
        "session_id": session_id,
        "parent_node_id": "",
        "type": "INITIAL",
        "cadquery_script": "import cadquery as cq\nresult = cq.Workplane('XY').box(10,10,10)",
        "step_s3_key": "",
        "gltf_s3_key": "",
        "confidence_map": {"Feature-001": "0.95"},
        "created_at": int(time.time()),
    })
    return node_id


@mock_aws
def test_list_sessions(dynamodb_tables):
    """GET /sessions returns user's sessions."""
    _seed_session(dynamodb_tables)

    import backend.functions.history_handler.index as module
    importlib.reload(module)

    event = make_api_event(method="GET", resource="/sessions")
    resp = module.lambda_handler(event, None)
    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["session_id"] == "sess-001"


@mock_aws
def test_get_session(dynamodb_tables):
    """GET /sessions/{id} returns session details."""
    _seed_session(dynamodb_tables)

    import backend.functions.history_handler.index as module
    importlib.reload(module)

    event = make_api_event(
        method="GET",
        resource="/sessions/{session_id}",
        path_params={"session_id": "sess-001"},
    )
    resp = module.lambda_handler(event, None)
    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    assert body["session_id"] == "sess-001"


@mock_aws
def test_get_session_not_found(dynamodb_tables):
    """GET /sessions/{id} returns 404 for missing session."""
    import backend.functions.history_handler.index as module
    importlib.reload(module)

    event = make_api_event(
        method="GET",
        resource="/sessions/{session_id}",
        path_params={"session_id": "nonexistent"},
    )
    resp = module.lambda_handler(event, None)
    assert resp["statusCode"] == 404


@mock_aws
def test_list_nodes(dynamodb_tables):
    """GET /sessions/{id}/nodes returns nodes."""
    _seed_session(dynamodb_tables)
    _seed_node(dynamodb_tables)

    import backend.functions.history_handler.index as module
    importlib.reload(module)

    event = make_api_event(
        method="GET",
        resource="/sessions/{session_id}/nodes",
        path_params={"session_id": "sess-001"},
    )
    resp = module.lambda_handler(event, None)
    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    assert len(body["nodes"]) == 1


@mock_aws
def test_get_node(dynamodb_tables):
    """GET /sessions/{id}/nodes/{nid} returns node details."""
    _seed_node(dynamodb_tables)

    import backend.functions.history_handler.index as module
    importlib.reload(module)

    event = make_api_event(
        method="GET",
        resource="/sessions/{session_id}/nodes/{node_id}",
        path_params={"session_id": "sess-001", "node_id": "node-001"},
    )
    resp = module.lambda_handler(event, None)
    assert resp["statusCode"] == 200


@mock_aws
def test_delete_session(dynamodb_tables):
    """DELETE /sessions/{id} removes the session."""
    _seed_session(dynamodb_tables)

    import backend.functions.history_handler.index as module
    importlib.reload(module)

    event = make_api_event(
        method="DELETE",
        resource="/sessions/{session_id}",
        path_params={"session_id": "sess-001"},
    )
    resp = module.lambda_handler(event, None)
    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    assert body["deleted"] == "sess-001"
