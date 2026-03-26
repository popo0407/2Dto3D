"""Tests for common models."""
from __future__ import annotations

import sys
sys.path.insert(0, "/workspaces/2Dto3D/backend")

from common.models import SessionItem, NodeItem, generate_id, now_ts


def test_generate_id():
    """generate_id returns a UUID string."""
    id1 = generate_id()
    id2 = generate_id()
    assert isinstance(id1, str)
    assert len(id1) == 36
    assert id1 != id2


def test_session_item_defaults():
    """SessionItem has correct defaults."""
    session = SessionItem()
    assert session.status == "UPLOADING"
    assert session.current_node_id == ""
    assert session.input_files == []
    assert session.session_id  # non-empty


def test_session_item_to_dynamo():
    """SessionItem.to_dynamo() generates TTL."""
    session = SessionItem(user_id="u1", project_name="P")
    d = session.to_dynamo()
    assert d["user_id"] == "u1"
    assert d["ttl"] > 0


def test_node_item_defaults():
    """NodeItem has correct defaults."""
    node = NodeItem(session_id="s1")
    assert node.type == "INITIAL"
    assert node.cadquery_script == ""
    assert node.confidence_map == {}


def test_node_item_to_dynamo():
    """NodeItem.to_dynamo() returns full dict."""
    node = NodeItem(
        session_id="s1",
        cadquery_script="import cq",
        confidence_map={"F1": 0.9},
    )
    d = node.to_dynamo()
    assert d["session_id"] == "s1"
    assert d["confidence_map"] == {"F1": 0.9}
