"""Tests for ws_handler (WebSocket connect/disconnect)."""
from __future__ import annotations

import json
import importlib

import pytest
import boto3
from moto import mock_aws


@mock_aws
def test_connect_handler(dynamodb_tables):
    """WebSocket connect stores connection in DynamoDB."""
    import backend.functions.ws_handler.index as module
    importlib.reload(module)

    event = {
        "requestContext": {"connectionId": "conn-abc123"},
        "queryStringParameters": {"user_id": "user-001"},
    }

    resp = module.connect_handler(event, None)
    assert resp["statusCode"] == 200

    # Verify connection stored
    table = dynamodb_tables.Table("test-connections")
    item = table.get_item(Key={"connection_id": "conn-abc123"}).get("Item")
    assert item is not None
    assert item["user_id"] == "user-001"


@mock_aws
def test_disconnect_handler(dynamodb_tables):
    """WebSocket disconnect removes connection from DynamoDB."""
    import backend.functions.ws_handler.index as module
    importlib.reload(module)

    # First connect
    table = dynamodb_tables.Table("test-connections")
    table.put_item(Item={
        "connection_id": "conn-abc123",
        "user_id": "user-001",
        "connected_at": 1000000,
        "ttl": 2000000,
    })

    event = {
        "requestContext": {"connectionId": "conn-abc123"},
    }

    resp = module.disconnect_handler(event, None)
    assert resp["statusCode"] == 200

    # Verify connection removed
    item = table.get_item(Key={"connection_id": "conn-abc123"}).get("Item")
    assert item is None


@mock_aws
def test_connect_anonymous(dynamodb_tables):
    """WebSocket connect without user_id defaults to anonymous."""
    import backend.functions.ws_handler.index as module
    importlib.reload(module)

    event = {
        "requestContext": {"connectionId": "conn-xyz"},
        "queryStringParameters": None,
    }

    resp = module.connect_handler(event, None)
    assert resp["statusCode"] == 200

    table = dynamodb_tables.Table("test-connections")
    item = table.get_item(Key={"connection_id": "conn-xyz"}).get("Item")
    assert item["user_id"] == "anonymous"
