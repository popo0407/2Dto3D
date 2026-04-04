"""BuildPlan worker handler: executes AI-heavy operations asynchronously.

Invoked with InvocationType="Event" (async) by:
  - buildplan_create_handler  → action="create"
  - buildplan_step_handler    → action="modify"

Never called directly from API Gateway.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "")
NODES_TABLE = os.environ.get("NODES_TABLE", "")
BUILD_PLANS_TABLE = os.environ.get("BUILD_PLANS_TABLE", "")
BUILD_STEPS_TABLE = os.environ.get("BUILD_STEPS_TABLE", "")
UPLOADS_BUCKET = os.environ.get("UPLOADS_BUCKET", "")
ARTIFACTS_BUCKET = os.environ.get("ARTIFACTS_BUCKET", "")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "ap-northeast-1")

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")

# ---------------------------------------------------------------------------
# Prompts (shared with create and modify workflows)
# ---------------------------------------------------------------------------

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

【出力フォーマット（JSON のみ）】
```json
{{
  "reasoning": "図面の分析結果と構築戦略の説明（日本語）",
  "steps": [
    {{
      "step_seq": "0001",
      "step_type": "base_body",
      "step_name": "基本直方体",
      "parameters": {{}},
      "cq_code": "result = cq.Workplane('XY').box(100, 50, 10)",
      "group_id": "",
      "confidence": 0.95,
      "ai_reasoning": "..."
    }}
  ]
}}
```

【重要】JSON のみを出力してください。cq_code の先頭に import 文は不要です。
"""

MODIFY_PROMPT = """以下のBuildPlanのステップを、ユーザーの指示に従い修正してください。

【対象ステップ】
{target_step}

【BuildPlan 全ステップ】
{all_steps}

【ユーザーの修正指示】
{user_instruction}

【修正ルール】
1. 修正されたステップから最終ステップまでの全てを再計画してください
2. 修正前のステップ（対象ステップより前）はそのまま維持
3. 各ステップの cq_code は前のステップの result を引き継ぐこと
4. 穴あけは必ず .faces("...").workplane().pushPoints([...]).hole(d) 形式

【出力フォーマット（JSON のみ）】
```json
{{
  "reasoning": "修正内容の説明（日本語）",
  "modified_steps": [
    {{
      "step_seq": "0002",
      "step_type": "...",
      "step_name": "...",
      "parameters": {{}},
      "cq_code": "...",
      "group_id": "...",
      "confidence": 0.95,
      "ai_reasoning": "..."
    }}
  ]
}}
```
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context) -> None:
    """Route to create or modify worker based on action field."""
    action = event.get("action", "create")
    logger.info("BuildPlan worker: action=%s", action)

    if action == "create":
        _handle_create(event)
    elif action == "modify":
        _handle_modify(event)
    else:
        logger.error("Unknown action: %s", action)


# ---------------------------------------------------------------------------
# Create action
# ---------------------------------------------------------------------------

def _handle_create(event: dict) -> None:
    plan_id = event["plan_id"]
    session_id = event["session_id"]
    node_id = event["node_id"]

    plans_table = dynamodb.Table(BUILD_PLANS_TABLE)

    try:
        # Load session and image
        sessions_table = dynamodb.Table(SESSIONS_TABLE)
        session = sessions_table.get_item(Key={"session_id": session_id}).get("Item", {})

        image_bytes, image_media_type = _load_first_image(session)
        parsed_data = _load_parsed_data(session_id)

        # Call Bedrock
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

        # Parse AI response
        ai_output = _parse_ai_response(invoke_result.text)
        steps = ai_output.get("steps", [])
        reasoning = ai_output.get("reasoning", "")

        if not steps:
            raise ValueError("AI returned no steps")

        # Save steps to DynamoDB
        steps_table = dynamodb.Table(BUILD_STEPS_TABLE)
        now = int(time.time())
        for step_data in steps:
            steps_table.put_item(Item={
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
            })

        # Update plan: status → planned
        plans_table.update_item(
            Key={"plan_id": plan_id},
            UpdateExpression=(
                "SET plan_status = :s, total_steps = :t, reasoning = :r, updated_at = :now"
            ),
            ExpressionAttributeValues={
                ":s": "planned",
                ":t": len(steps),
                ":r": reasoning,
                ":now": now,
            },
        )

        # Update node with reasoning
        nodes_table = dynamodb.Table(NODES_TABLE)
        nodes_table.update_item(
            Key={"node_id": node_id},
            UpdateExpression="SET ai_reasoning = :r",
            ExpressionAttributeValues={":r": reasoning},
        )

        # Update session status
        sessions_table.update_item(
            Key={"session_id": session_id},
            UpdateExpression="SET #s = :s, updated_at = :now",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "BUILDPLAN_ACTIVE", ":now": now},
        )

        logger.info("BuildPlan create complete: plan_id=%s, steps=%d", plan_id, len(steps))

    except Exception as e:
        logger.error("BuildPlan create failed for plan %s: %s", plan_id, e, exc_info=True)
        plans_table.update_item(
            Key={"plan_id": plan_id},
            UpdateExpression="SET plan_status = :s, reasoning = :r, updated_at = :now",
            ExpressionAttributeValues={
                ":s": "failed",
                ":r": f"エラー: {e}",
                ":now": int(time.time()),
            },
        )


# ---------------------------------------------------------------------------
# Modify action
# ---------------------------------------------------------------------------

def _handle_modify(event: dict) -> None:
    plan_id = event["plan_id"]
    session_id = event["session_id"]
    step_seq = event["step_seq"]
    instruction = event.get("instruction", "")

    plans_table = dynamodb.Table(BUILD_PLANS_TABLE)
    steps_table = dynamodb.Table(BUILD_STEPS_TABLE)

    try:
        # Load session and image for context
        sessions_table = dynamodb.Table(SESSIONS_TABLE)
        session = sessions_table.get_item(Key={"session_id": session_id}).get("Item", {})
        image_bytes, image_media_type = _load_first_image(session)

        # Load all steps
        all_steps = _query_all_steps(plan_id, steps_table)
        target_step = next((s for s in all_steps if s["step_seq"] == step_seq), None)
        if not target_step:
            raise ValueError(f"Step {step_seq} not found in plan {plan_id}")

        # Build prompt
        prompt = MODIFY_PROMPT.format(
            target_step=json.dumps(_decimal_to_float_dict(target_step), ensure_ascii=False, indent=2),
            all_steps=json.dumps([_decimal_to_float_dict(s) for s in all_steps], ensure_ascii=False, indent=2),
            user_instruction=instruction,
        )

        # Call Bedrock
        from common.bedrock_client import get_bedrock_client
        client = get_bedrock_client(region=BEDROCK_REGION)
        invoke_result = client.invoke_multimodal(
            prompt=prompt,
            image_bytes=image_bytes,
            image_media_type=image_media_type,
            system_prompt="あなたは機械設計の専門家です。BuildPlanのステップ修正を行ってください。",
            max_tokens=16384,
        )

        # Parse response
        ai_output = _parse_ai_response(invoke_result.text)
        modified_steps = ai_output.get("modified_steps", [])
        reasoning = ai_output.get("reasoning", "")

        if not modified_steps:
            raise ValueError("AI returned no modified steps")

        # Update modified steps in DynamoDB
        now = int(time.time())
        for mod_step in modified_steps:
            seq = mod_step.get("step_seq", "")
            if not seq:
                continue
            steps_table.update_item(
                Key={"plan_id": plan_id, "step_seq": seq},
                UpdateExpression=(
                    "SET step_type = :stype, step_name = :sname, "
                    "parameters = :params, cq_code = :code, "
                    "group_id = :gid, confidence = :conf, "
                    "#st = :status, ai_reasoning = :reason"
                ),
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":stype": mod_step.get("step_type", ""),
                    ":sname": mod_step.get("step_name", ""),
                    ":params": _float_to_decimal(mod_step.get("parameters", {})),
                    ":code": mod_step.get("cq_code", ""),
                    ":gid": mod_step.get("group_id", ""),
                    ":conf": Decimal(str(mod_step.get("confidence", 0.0))),
                    ":status": "modified",
                    ":reason": mod_step.get("ai_reasoning", ""),
                },
            )

        # Update plan: status → planned, save reasoning
        plans_table.update_item(
            Key={"plan_id": plan_id},
            UpdateExpression=(
                "SET plan_status = :s, modify_reasoning = :r, updated_at = :now"
            ),
            ExpressionAttributeValues={
                ":s": "planned",
                ":r": reasoning,
                ":now": now,
            },
        )

        logger.info(
            "BuildPlan modify complete: plan_id=%s, step_seq=%s, modified=%d",
            plan_id, step_seq, len(modified_steps),
        )

    except Exception as e:
        logger.error("BuildPlan modify failed for plan %s step %s: %s", plan_id, step_seq, e, exc_info=True)
        plans_table.update_item(
            Key={"plan_id": plan_id},
            UpdateExpression="SET plan_status = :s, modify_reasoning = :r, updated_at = :now",
            ExpressionAttributeValues={
                ":s": "planned",          # revert to planned so UI is not stuck
                ":r": f"修正エラー: {e}",
                ":now": int(time.time()),
            },
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _query_all_steps(plan_id: str, steps_table) -> list[dict]:
    items: list = []
    resp = steps_table.query(KeyConditionExpression=Key("plan_id").eq(plan_id))
    items.extend(resp.get("Items", []))
    while resp.get("LastEvaluatedKey"):
        resp = steps_table.query(
            KeyConditionExpression=Key("plan_id").eq(plan_id),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    return sorted(items, key=lambda x: x.get("step_seq", ""))


def _load_first_image(session: dict) -> tuple:
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
            except Exception as exc:
                logger.warning("Failed to load image %s: %s", f, exc)
    return None, "image/png"


def _load_parsed_data(session_id: str) -> dict:
    if not ARTIFACTS_BUCKET:
        return {}
    try:
        obj = s3_client.get_object(
            Bucket=ARTIFACTS_BUCKET,
            Key=f"artifacts/{session_id}/parsed_data.json",
        )
        return json.loads(obj["Body"].read().decode("utf-8"))
    except Exception:
        return {}


def _parse_ai_response(raw: str) -> dict:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*\n(.*?)\n```", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass
    logger.error("Failed to parse AI response: %s", raw[:200])
    return {}


def _float_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _float_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_float_to_decimal(i) for i in obj]
    return obj


def _decimal_to_float_dict(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_float_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_float_dict(i) for i in obj]
    return obj
