"""Shared test fixtures with moto mocking."""
from __future__ import annotations

import os
import json
import pytest
import boto3
from moto import mock_aws


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    """Set dummy AWS credentials and table/bucket names for all tests."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-1")
    monkeypatch.setenv("SESSIONS_TABLE", "test-sessions")
    monkeypatch.setenv("NODES_TABLE", "test-nodes")
    monkeypatch.setenv("CONNECTIONS_TABLE", "test-connections")
    monkeypatch.setenv("UPLOADS_BUCKET", "test-uploads")
    monkeypatch.setenv("ARTIFACTS_BUCKET", "test-artifacts")
    monkeypatch.setenv("PREVIEWS_BUCKET", "test-previews")
    monkeypatch.setenv("PROCESSING_QUEUE_URL", "")
    monkeypatch.setenv("USE_MOCK_AI", "true")
    monkeypatch.setenv("BEDROCK_REGION", "ap-northeast-1")
    monkeypatch.setenv("ENV_NAME", "dev")
    monkeypatch.setenv("PROJECT_NAME", "2dto3d")


@pytest.fixture
def dynamodb_tables():
    """Create mocked DynamoDB tables."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-northeast-1")

        # Sessions table
        client.create_table(
            TableName="test-sessions",
            KeySchema=[{"AttributeName": "session_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "session_id", "AttributeType": "S"},
                {"AttributeName": "user_id", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "user_id-index",
                    "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Nodes table
        client.create_table(
            TableName="test-nodes",
            KeySchema=[{"AttributeName": "node_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "node_id", "AttributeType": "S"},
                {"AttributeName": "session_id", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "session_id-index",
                    "KeySchema": [{"AttributeName": "session_id", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Connections table
        client.create_table(
            TableName="test-connections",
            KeySchema=[{"AttributeName": "connection_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "connection_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        yield boto3.resource("dynamodb", region_name="ap-northeast-1")


@pytest.fixture
def s3_buckets():
    """Create mocked S3 buckets."""
    with mock_aws():
        client = boto3.client("s3", region_name="ap-northeast-1")
        for bucket in ["test-uploads", "test-artifacts", "test-previews"]:
            client.create_bucket(
                Bucket=bucket,
                CreateBucketConfiguration={"LocationConstraint": "ap-northeast-1"},
            )
        yield client


@pytest.fixture
def sqs_queue():
    """Create mocked SQS queue."""
    with mock_aws():
        client = boto3.client("sqs", region_name="ap-northeast-1")
        resp = client.create_queue(QueueName="test-processing-queue")
        yield resp["QueueUrl"]


def make_api_event(
    method: str = "POST",
    resource: str = "/sessions",
    path_params: dict | None = None,
    body: dict | None = None,
    user_id: str = "test-user-123",
    query_params: dict | None = None,
) -> dict:
    """Create a mock API Gateway event."""
    return {
        "httpMethod": method,
        "resource": resource,
        "pathParameters": path_params or {},
        "queryStringParameters": query_params or {},
        "body": json.dumps(body) if body else None,
        "requestContext": {
            "authorizer": {
                "claims": {"sub": user_id},
            }
        },
        "headers": {"Content-Type": "application/json"},
    }
