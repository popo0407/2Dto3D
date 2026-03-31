from __future__ import annotations

import time
import uuid
from typing import Optional

from pydantic import BaseModel, Field


def generate_id() -> str:
    return str(uuid.uuid4())


def now_ts() -> int:
    return int(time.time())


class SessionItem(BaseModel):
    session_id: str = Field(default_factory=generate_id)
    user_id: str = ""
    project_name: str = ""
    status: str = "UPLOADING"
    current_node_id: str = ""
    input_files: list[str] = Field(default_factory=list)
    pending_verify_comment: str = ""
    created_at: int = Field(default_factory=now_ts)
    updated_at: int = Field(default_factory=now_ts)
    ttl: int = 0

    def to_dynamo(self) -> dict:
        d = self.model_dump()
        if not d["ttl"]:
            d["ttl"] = d["created_at"] + 90 * 86400  # 90 days
        return d


class NodeItem(BaseModel):
    node_id: str = Field(default_factory=generate_id)
    session_id: str = ""
    parent_node_id: str = ""
    type: str = "INITIAL"
    cadquery_script: str = ""
    ai_reasoning: str = ""
    diff_patch: str = ""
    step_s3_key: str = ""
    gltf_s3_key: str = ""
    user_message: str = ""
    ai_questions: list[dict] = Field(default_factory=list)
    created_at: int = Field(default_factory=now_ts)

    def to_dynamo(self) -> dict:
        return self.model_dump()


class DrawingElementItem(BaseModel):
    drawing_id: str = ""
    element_seq: str = ""
    element_type: str = ""
    feature_label: str = ""
    dimensions: dict = Field(default_factory=dict)
    position: dict = Field(default_factory=dict)
    orientation: str = ""
    cq_fragment: str = ""
    confidence: float = 0.0
    is_verified: bool = False
    ai_reasoning: str = ""
    verification_count: int = 0
    node_id: str = ""
    ttl: int = 0

    def to_dynamo(self) -> dict:
        from decimal import Decimal

        d = self.model_dump()
        # DynamoDB requires Decimal for numeric types
        d["confidence"] = Decimal(str(d["confidence"]))
        if not d["ttl"]:
            d["ttl"] = now_ts() + 90 * 86400
        return d
