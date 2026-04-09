from __future__ import annotations

import time
import uuid
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# feature_spec 型定義（element_type ごとの詳細スペック）
# ---------------------------------------------------------------------------


class HoleSpec(BaseModel):
    """通常穴（貫通・止め穴）のスペック。"""

    hole_type: Literal["through", "blind"] = "through"
    diameter: float = 0.0
    depth: Optional[float] = None  # through の場合は None


class TappedHoleSpec(BaseModel):
    """ネジ穴（タップ穴）のスペック。"""

    hole_type: Literal["tapped"] = "tapped"
    designation: str = ""        # 例: "M6", "M8x1.25"
    pitch: float = 0.0           # ネジピッチ (mm)
    tap_depth: float = 0.0       # タップ深さ (mm)
    drill_diameter: float = 0.0  # 下穴径 (mm)
    through: bool = False        # 貫通タップの場合 True
    standard: Literal["JIS", "ISO", "UNC", "UNF", "other"] = "JIS"


class FilletSpec(BaseModel):
    """フィレット（R面取り）のスペック。"""

    radius: float = 0.0
    edge_selector: str = "|Z"    # CadQuery エッジセレクタ (例: "|Z", ">Z", "<Z")
    quantity: int = 1            # 同一フィレットの対象エッジ数


class ChamferSpec(BaseModel):
    """シャンファー（C面取り）のスペック。"""

    distance: float = 0.0        # 面取り量 (mm)
    angle: float = 45.0          # 面取り角度 (deg)。45°以外の場合に指定
    edge_selector: str = "|Z"    # CadQuery エッジセレクタ
    quantity: int = 1


class SlotSpec(BaseModel):
    """長穴（スロット）のスペック。"""

    width: float = 0.0
    length: float = 0.0
    depth: Optional[float] = None   # None = 貫通
    orientation: str = "+Z"


class PocketSpec(BaseModel):
    """ポケット加工のスペック。"""

    width: float = 0.0
    height: float = 0.0
    depth: float = 0.0


FeatureSpec = Union[
    HoleSpec,
    TappedHoleSpec,
    FilletSpec,
    ChamferSpec,
    SlotSpec,
    PocketSpec,
    dict,  # element_type = "other" / 未定義フィーチャーの fallback
]


def generate_id() -> str:
    return str(uuid.uuid4())


def now_ts() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# BuildPlan models (Interactive BuildPlan mode)
# ---------------------------------------------------------------------------


class StepParameter(BaseModel):
    """BuildStep individual parameter with provenance info."""

    value: Union[float, str, bool, int] = 0.0
    unit: str = "mm"
    source: Literal["extracted", "standard", "calculated", "user"] = "extracted"
    confidence: float = 1.0


class BuildPlanItem(BaseModel):
    """Build plan metadata — one per session in BuildPlan mode."""

    plan_id: str = Field(default_factory=generate_id)
    session_id: str = ""
    node_id: str = ""
    plan_status: str = "planning"  # planning, active, executing, completed, archived
    total_steps: int = 0
    current_step: int = 0
    created_at: int = Field(default_factory=now_ts)
    updated_at: int = Field(default_factory=now_ts)
    ttl: int = 0

    def to_dynamo(self) -> dict:
        d = self.model_dump()
        if not d["ttl"]:
            d["ttl"] = d["created_at"] + 90 * 86400
        return d


class BuildStepItem(BaseModel):
    """Individual build step within a BuildPlan."""

    plan_id: str = ""
    step_seq: str = ""  # "0001", "0002", ...
    step_type: str = ""  # base_body, hole_through, tapped_hole, fillet, chamfer, slot, pocket
    step_name: str = ""  # Japanese label for UI display
    parameters: dict = Field(default_factory=dict)  # key → StepParameter-compatible dict
    cq_code: str = ""  # CadQuery code fragment for this step
    dependencies: list[str] = Field(default_factory=list)
    group_id: str = ""  # For batch operations on identical features
    confidence: float = 0.0
    status: str = "planned"  # planned, executing, completed, modified, failed
    ai_reasoning: str = ""
    checkpoint_step_key: str = ""  # S3 key for STEP checkpoint
    checkpoint_glb_key: str = ""  # S3 key for GLB preview
    executed_at: int = 0
    ttl: int = 0

    def to_dynamo(self) -> dict:
        from decimal import Decimal

        d = self.model_dump()
        d["confidence"] = Decimal(str(d["confidence"]))
        d["parameters"] = _float_to_decimal_dict(d["parameters"])
        if not d["ttl"]:
            d["ttl"] = now_ts() + 90 * 86400
        return d


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
    # element_type の有効値:
    #   "box"         : 基本直方体
    #   "hole_through": 貫通穴
    #   "hole_blind"  : 止め穴
    #   "tapped_hole" : ネジ穴（タップ穴）
    #   "fillet"      : R面取り
    #   "chamfer"     : C面取り
    #   "slot"        : 長穴
    #   "pocket"      : ポケット加工
    #   "boss"        : ボス（突起）
    #   "rib"         : リブ
    #   "other"       : 上記以外
    element_type: str = ""
    feature_label: str = ""
    # feature_spec: element_type に対応した詳細パラメータ (後方互換のため optional)
    feature_spec: dict = Field(default_factory=dict)
    # 下記 dimensions/position/orientation は後方互換フィールド。
    # 新規保存時は feature_spec を優先し、こちらにも概要値を保持する。
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
        d["dimensions"] = _float_to_decimal_dict(d["dimensions"])
        d["position"] = _float_to_decimal_dict(d["position"])
        d["feature_spec"] = _float_to_decimal_dict(d["feature_spec"])
        if not d["ttl"]:
            d["ttl"] = now_ts() + 90 * 86400
        return d


def _float_to_decimal_dict(obj: dict | list | float | int | str | None):
    """Recursively convert float values to Decimal for DynamoDB storage."""
    from decimal import Decimal

    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _float_to_decimal_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_float_to_decimal_dict(i) for i in obj]
    return obj
