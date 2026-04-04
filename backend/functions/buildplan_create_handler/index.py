"""BuildPlan create handler: AI analyzes 2D drawing and generates a step-by-step build plan.

POST /sessions/{session_id}/build-plans
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from decimal import Decimal

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "")
NODES_TABLE = os.environ.get("NODES_TABLE", "")
BUILD_PLANS_TABLE = os.environ.get("BUILD_PLANS_TABLE", "")
BUILD_STEPS_TABLE = os.environ.get("BUILD_STEPS_TABLE", "")
UPLOADS_BUCKET = os.environ.get("UPLOADS_BUCKET", "")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "ap-northeast-1")

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")

BUILDPLAN_SYSTEM_PROMPT = """あなたは機械設計の専門家でありCADオペレーターです。
2D図面を分析し、3D CADモデルを段階的に構築するための構築プラン（BuildPlan）を作成してください。
BuildPlanは実際のCADオペレーターが手作業で組み上げるのと同じ手順で、1ステップずつ構築する計画です。"""

BUILDPLAN_PROMPT = """添付の2D図面を分析し、3Dモデルを段階的に構築するBuildPlanを作成してください。

【BuildPlan の原則】
1. 最初にベース形状（box/cylinder等）を1ステップで作成
2. その後、加工フィーチャーを1つずつ追加（穴あけ、面取り等）
3. 同じ仕様（同径・同深さ・同面）の穴は1ステップにまとめる（group_id で管理）
4. 穴あけとタップ加工は1ステップにまとめる（実際の加工と同じ）
5. 各ステップの CadQuery コードは前のステップの result を引き継ぐ

【step_type 一覧】
- base_body: ベース形状（box, cylinder）
- hole_through: 貫通穴
- hole_blind: 止め穴
- tapped_hole: ネジ穴（下穴+タップを1ステップとして扱う）
- fillet: R面取り
- chamfer: C面取り
- slot: 長穴
- pocket: ポケット加工

【穴の方向と面指定 ― 最重要ルール】
- 穴の方向は図面のビュー（正面/平面/側面）から判断
- 穴あけは必ず .faces("...").workplane().pushPoints([...]).hole(d) 形式
- .faces("...").workplane() を省略禁止

【CadQuery 座標系】
- .box() は原点中心に生成（左端 = -W/2, 右端 = +W/2）
- 図面座標 (Xd, Yd) → CadQuery = (Xd - W/2, Yd - H/2)

【parameters のフォーマット】
各パラメータは以下の形式で記述:
{{"value": 数値または文字列, "unit": "mm", "source": "extracted|standard|calculated", "confidence": 0.0-1.0}}

source の意味:
- extracted: 図面から直接読み取った値
- standard: JIS/ISO 規格に基づく推定値
- calculated: 計算で導出した値

【出力フォーマット（JSON のみ）】
```json
{{
  "reasoning": "図面の分析結果と構築戦略の説明（日本語）",
  "steps": [
    {{
      "step_seq": "0001",
      "step_type": "base_body",
      "step_name": "基本直方体 120×80×15",
      "parameters": {{
        "width": {{"value": 120.0, "unit": "mm", "source": "extracted", "confidence": 0.95}},
        "height": {{"value": 80.0, "unit": "mm", "source": "extracted", "confidence": 0.95}},
        "depth": {{"value": 15.0, "unit": "mm", "source": "extracted", "confidence": 0.90}}
      }},
      "cq_code": "# Step 0001: 基本直方体\\nWIDTH = 120.0\\nHEIGHT = 80.0\\nDEPTH = 15.0\\nresult = cq.Workplane('XY').box(WIDTH, HEIGHT, DEPTH)",
      "group_id": "",
      "confidence": 0.95,
      "ai_reasoning": "正面図の外形寸法 120×80、側面図の厚み 15mm から"
    }},
    {{
      "step_seq": "0002",
      "step_type": "hole_through",
      "step_name": "Φ6 貫通穴 x4（上面）",
      "parameters": {{
        "diameter": {{"value": 6.0, "unit": "mm", "source": "extracted", "confidence": 0.92}},
        "face": {{"value": ">Z", "unit": "", "source": "calculated", "confidence": 0.90}},
        "positions": {{"value": "[(-40, -25), (40, -25), (-40, 25), (40, 25)]", "unit": "mm", "source": "calculated", "confidence": 0.85}}
      }},
      "cq_code": "# Step 0002: Φ6 貫通穴 x4\\nresult = result.faces(\\">Z\\").workplane().pushPoints([(-40, -25), (40, -25), (-40, 25), (40, 25)]).hole(6.0)",
      "group_id": "hole_group_a",
      "confidence": 0.85,
      "ai_reasoning": "正面図に4箇所の円（Φ6）を確認。対称配置。"
    }}
  ]
}}
```

【重要】
- JSON のみを出力してください
- 各ステップの cq_code は前のステップの result 変数を引き継ぐこと
- cq_code の先頭に import 文は不要（自動で付加されます）
- すべての数値は定数として抽出（マジックナンバー禁止）
"""


def lambda_handler(event: dict, context) -> dict:
    """Create a BuildPlan from an uploaded drawing.

    POST /sessions/{session_id}/build-plans
    """
    http_method = event.get("httpMethod", "")
    if http_method != "POST":
        return _response(405, {"error": "Method not allowed"})

    session_id = event["pathParameters"]["session_id"]
    logger.info("Creating BuildPlan for session %s", session_id)

    # Load session data
    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    resp = sessions_table.get_item(Key={"session_id": session_id})
    session = resp.get("Item")
    if not session:
        return _response(404, {"error": "Session not found"})

    # Load image for multimodal analysis
    image_bytes, image_media_type = _load_first_image(session)

    # Load parsed data from S3 if available
    parsed_data = _load_parsed_data(session_id)

    # Create node for history tracking
    nodes_table = dynamodb.Table(NODES_TABLE)
    node_id = str(uuid.uuid4())
    now = int(time.time())
    node = {
        "node_id": node_id,
        "session_id": session_id,
        "parent_node_id": session.get("current_node_id", ""),
        "type": "BUILDPLAN_INITIAL",
        "cadquery_script": "",
        "ai_reasoning": "",
        "created_at": now,
    }
    nodes_table.put_item(Item=node)

    # Update session
    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET #s = :status, current_node_id = :nid, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "BUILDPLAN_CREATING",
            ":nid": node_id,
            ":now": now,
        },
    )

    # Send progress via WebSocket
    from common.ws_notify import send_progress
    send_progress(session_id, "BUILDPLAN_CREATING", 10, "BuildPlan を作成中...")

    # Invoke AI to generate BuildPlan
    from common.bedrock_client import get_bedrock_client
    client = get_bedrock_client(region=BEDROCK_REGION)

    context_json = parsed_data.get("files") if parsed_data else None
    invoke_result = client.invoke_multimodal(
        prompt=BUILDPLAN_PROMPT,
        image_bytes=image_bytes,
        image_media_type=image_media_type,
        context_json=context_json,
        system_prompt=BUILDPLAN_SYSTEM_PROMPT,
        max_tokens=16384,
    )

    from common.ws_notify import send_token_usage
    send_token_usage(session_id, "BUILDPLAN_CREATING", invoke_result.input_tokens, invoke_result.output_tokens)

    # Parse AI response
    ai_output = _parse_ai_response(invoke_result.text)
    steps = ai_output.get("steps", [])
    reasoning = ai_output.get("reasoning", "")

    if not steps:
        logger.error("AI returned no steps for session %s", session_id)
        return _response(500, {"error": "AI failed to generate BuildPlan steps"})

    # Create BuildPlan
    plan_id = str(uuid.uuid4())
    plan = {
        "plan_id": plan_id,
        "session_id": session_id,
        "node_id": node_id,
        "plan_status": "active",
        "total_steps": len(steps),
        "current_step": 0,
        "created_at": now,
        "updated_at": now,
        "ttl": now + 90 * 86400,
    }

    plans_table = dynamodb.Table(BUILD_PLANS_TABLE)
    plans_table.put_item(Item=plan)

    # Save steps
    steps_table = dynamodb.Table(BUILD_STEPS_TABLE)
    saved_steps = []
    for step_data in steps:
        step_item = {
            "plan_id": plan_id,
            "step_seq": step_data.get("step_seq", ""),
            "step_type": step_data.get("step_type", ""),
            "step_name": step_data.get("step_name", ""),
            "parameters": _float_to_decimal(step_data.get("parameters", {})),
            "cq_code": step_data.get("cq_code", ""),
            "dependencies": step_data.get("dependencies", []),
            "group_id": step_data.get("group_id", ""),
            "confidence": Decimal(str(step_data.get("confidence", 0.0))),
            "status": "planned",
            "ai_reasoning": step_data.get("ai_reasoning", ""),
            "checkpoint_step_key": "",
            "checkpoint_glb_key": "",
            "executed_at": 0,
            "ttl": now + 90 * 86400,
        }
        steps_table.put_item(Item=step_item)
        saved_steps.append({
            **step_data,
            "plan_id": plan_id,
            "status": "planned",
        })

    # Update node with reasoning
    nodes_table.update_item(
        Key={"node_id": node_id},
        UpdateExpression="SET ai_reasoning = :reason",
        ExpressionAttributeValues={":reason": reasoning},
    )

    # Update session status
    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET #s = :status, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "BUILDPLAN_ACTIVE",
            ":now": int(time.time()),
        },
    )

    send_progress(session_id, "BUILDPLAN_CREATED", 100, "BuildPlan 作成完了")

    logger.info("BuildPlan created: %s with %d steps", plan_id, len(steps))
    return _response(201, {
        "plan_id": plan_id,
        "session_id": session_id,
        "node_id": node_id,
        "total_steps": len(steps),
        "reasoning": reasoning,
        "steps": saved_steps,
        "input_tokens": invoke_result.input_tokens,
        "output_tokens": invoke_result.output_tokens,
    })


def _load_first_image(session: dict) -> tuple:
    """Load first image from session's input_files."""
    input_files = session.get("input_files", [])
    for f in input_files:
        ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
        if ext in ("png", "jpg", "jpeg", "tiff", "tif"):
            try:
                obj = s3_client.get_object(Bucket=UPLOADS_BUCKET, Key=f)
                media_map = {
                    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "tiff": "image/tiff", "tif": "image/tiff",
                }
                return obj["Body"].read(), media_map.get(ext, "image/png")
            except Exception as e:
                logger.warning("Failed to load image %s: %s", f, e)
    return None, "image/png"


def _load_parsed_data(session_id: str) -> dict:
    """Try to load parsed data from S3 artifacts."""
    artifacts_bucket = os.environ.get("ARTIFACTS_BUCKET", "")
    if not artifacts_bucket:
        return {}
    try:
        obj = s3_client.get_object(
            Bucket=artifacts_bucket,
            Key=f"artifacts/{session_id}/parsed_data.json",
        )
        return json.loads(obj["Body"].read().decode("utf-8"))
    except Exception:
        return {}


def _parse_ai_response(raw: str) -> dict:
    """Parse JSON from AI response, handling markdown code fences."""
    raw = raw.strip()

    # Try direct JSON parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try extracting from code fence
    import re
    json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", raw, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding JSON object
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass

    logger.error("Failed to parse AI response: %s", raw[:200])
    return {}


def _float_to_decimal(obj):
    """Recursively convert float to Decimal for DynamoDB."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _float_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_float_to_decimal(i) for i in obj]
    return obj


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
        "body": json.dumps(body, default=str),
    }
