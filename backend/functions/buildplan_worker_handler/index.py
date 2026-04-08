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
# Prompts
# ---------------------------------------------------------------------------

INTERACTIVE_SYSTEM_PROMPT = """あなたは機械設計の専門家でありCADオペレーターです。
2D図面を1ステップずつ分析しながら、3D CADモデルを段階的に構築します。
各ステップで図面のどの部分をどのように解釈したか、ユーザーが確認できるよう丁寧に説明してください。"""

NEXT_STEP_PROMPT = """添付の2D図面を見て、3Dモデルを段階的に構築しています。

【確定済みステップ】
{confirmed_steps}

【次のステップを1つ提案してください】
- 確定済みステップの続きとして次に行う加工を1つだけ提案してください
- 最初のステップは必ず base_body（直方体・円柱などのベース形状）にしてください
- 穴あけは必ず .faces("...").workplane().pushPoints([...]).hole(d) 形式
- 全ての加工が完了した場合は {{"is_complete": true}} のみを返してください

【step_type 一覧】
- base_body: ベース形状（box, cylinder）
- hole_through: 貫通穴、hole_blind: 止め穴、tapped_hole: ネジ穴
- fillet: R面取り、chamfer: C面取り、slot: 長穴、pocket: ポケット加工

【CadQuery 座標系】
- .box(W, D, H): 原点中心。図面座標(Xd,Yd) → CQ: (Xd-W/2, Yd-H/2)
- .cylinder(height, radius): ※引数の順序は高さ先・半径後（例: .cylinder(40, 98) = 高さ40, 半径98）
  または named引数 .cylinder(height=40, radius=98) を使うことを推奨
- 確定済みステップがある場合、cq_code は result 変数を引き継ぐ

【パラメータ形式】
{{"value": 数値, "unit": "mm", "source": "extracted|standard|calculated", "confidence": 0.0-1.0}}

【出力フォーマット（JSONのみ）】
```json
{{
  "is_complete": false,
  "step_type": "base_body",
  "step_name": "基本直方体",
  "parameters": {{"width": {{"value": 100, "unit": "mm", "source": "extracted", "confidence": 0.95}}}},
  "cq_code": "result = cq.Workplane('XY').box(100, 50, 30)",
  "group_id": "",
  "confidence": 0.95,
  "explanation": "正面図の外形から幅100mm、側面図から奥行30mmと読み取りました",
  "choices": []
}}
```
※ confidence < 0.85 の場合のみ choices に解釈の選択肢を入れてください（例: [{{"id":"a","label":"φ8mm"}},...]）
※ JSON のみ出力。cq_code の先頭に import 文は不要
"""

REVISE_SYSTEM_PROMPT = """あなたは機械設計の専門家でありCADオペレーターです。
ユーザーが直前のあなたの提案に対して指摘・修正を行っています。
その指摘内容を必ず反映し、前回と同じ内容を繰り返さないでください。
修正が必要な箇所だけ変更し、同じJSON形式（is_complete, step_type, step_name, parameters, cq_code, group_id, confidence, explanation, choices）で修正版を返してください。
JSON のみ出力してください。"""




# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context) -> None:
    """Route to create or modify worker based on action field."""
    action = event.get("action", "create")
    logger.info("BuildPlan worker: action=%s", action)

    if action == "next_step":
        _handle_next_step(event)
    elif action == "revise_step":
        _handle_revise_step(event)
    else:
        logger.error("Unknown action: %s", action)


# ---------------------------------------------------------------------------
# Next Step action (interactive mode: propose one step at a time)
# ---------------------------------------------------------------------------

def _handle_next_step(event: dict) -> None:
    """Generate the next proposed step based on confirmed steps so far."""
    plan_id = event["plan_id"]
    session_id = event["session_id"]
    node_id = event.get("node_id", "")

    plans_table = dynamodb.Table(BUILD_PLANS_TABLE)
    steps_table = dynamodb.Table(BUILD_STEPS_TABLE)

    try:
        sessions_table = dynamodb.Table(SESSIONS_TABLE)
        session = sessions_table.get_item(Key={"session_id": session_id}).get("Item", {})
        image_bytes, image_media_type = _load_first_image(session)

        # Get confirmed steps in order
        all_steps = _query_all_steps(plan_id, steps_table)
        confirmed = [s for s in all_steps if s.get("status") == "confirmed"]
        next_num = len(confirmed) + 1
        next_seq = str(next_num).zfill(4)

        # Build confirmed summary for prompt
        if confirmed:
            lines = []
            for s in confirmed:
                lines.append(
                    f"Step {s['step_seq']} ({s.get('step_type','')}) — {s.get('step_name','')}:\n"
                    f"  {s.get('cq_code','')}"
                )
            confirmed_summary = "\n\n".join(lines)
        else:
            confirmed_summary = "（確定済みステップなし — これが最初のステップです）"

        from common.bedrock_client import get_bedrock_client
        client = get_bedrock_client(region=BEDROCK_REGION)
        invoke_result = client.invoke_multimodal(
            prompt=NEXT_STEP_PROMPT.format(confirmed_steps=confirmed_summary),
            image_bytes=image_bytes,
            image_media_type=image_media_type,
            system_prompt=INTERACTIVE_SYSTEM_PROMPT,
            max_tokens=4096,
        )

        ai_output = _parse_ai_response(invoke_result.text)
        now = int(time.time())

        if ai_output.get("is_complete"):
            # All steps done
            plans_table.update_item(
                Key={"plan_id": plan_id},
                UpdateExpression=(
                    "SET plan_status = :s, current_step_seq = :cs, "
                    "current_step_status = :css, total_steps = :t, updated_at = :now"
                ),
                ExpressionAttributeValues={
                    ":s": "interactive",
                    ":cs": "",
                    ":css": "done",
                    ":t": len(confirmed),
                    ":now": now,
                },
            )
            logger.info("BuildPlan next_step: all complete, plan_id=%s", plan_id)
            return

        # Save proposed step
        choices = _float_to_decimal(ai_output.get("choices", []))
        steps_table.put_item(Item={
            "plan_id": plan_id,
            "step_seq": next_seq,
            "step_type": ai_output.get("step_type", ""),
            "step_name": ai_output.get("step_name", ""),
            "parameters": _float_to_decimal(ai_output.get("parameters", {})),
            "cq_code": ai_output.get("cq_code", ""),
            "dependencies": [],
            "group_id": ai_output.get("group_id", ""),
            "confidence": Decimal(str(ai_output.get("confidence", 0.0))),
            "status": "proposed",
            "ai_reasoning": ai_output.get("explanation", ""),
            "choices": choices,
            "conversation": [
                {"role": "assistant", "content": invoke_result.text, "timestamp": now}
            ],
            "checkpoint_step_key": "",
            "checkpoint_glb_key": "",
            "executed_at": 0,
            "ttl": now + 90 * 86400,
        })

        # Update plan
        plans_table.update_item(
            Key={"plan_id": plan_id},
            UpdateExpression=(
                "SET plan_status = :s, current_step_seq = :cs, "
                "current_step_status = :css, updated_at = :now"
            ),
            ExpressionAttributeValues={
                ":s": "interactive",
                ":cs": next_seq,
                ":css": "ready",
                ":now": now,
            },
        )

        # Update session & node on first step
        if next_num == 1 and node_id:
            nodes_table = dynamodb.Table(NODES_TABLE)
            nodes_table.update_item(
                Key={"node_id": node_id},
                UpdateExpression="SET ai_reasoning = :r",
                ExpressionAttributeValues={":r": ai_output.get("explanation", "")},
            )
            sessions_table.update_item(
                Key={"session_id": session_id},
                UpdateExpression="SET #s = :s, updated_at = :now",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "BUILDPLAN_ACTIVE", ":now": now},
            )

        logger.info("next_step proposed: plan_id=%s, seq=%s", plan_id, next_seq)

    except Exception as e:
        logger.error("next_step failed for plan %s: %s", plan_id, e, exc_info=True)
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
# Revise Step action (re-propose a step based on user feedback)
# ---------------------------------------------------------------------------

def _handle_revise_step(event: dict) -> None:
    """Revise a proposed step using conversation history + user instruction."""
    plan_id = event["plan_id"]
    session_id = event["session_id"]
    step_seq = event["step_seq"]
    user_message = event["user_message"]

    plans_table = dynamodb.Table(BUILD_PLANS_TABLE)
    steps_table = dynamodb.Table(BUILD_STEPS_TABLE)

    try:
        sessions_table = dynamodb.Table(SESSIONS_TABLE)
        session = sessions_table.get_item(Key={"session_id": session_id}).get("Item", {})
        image_bytes, image_media_type = _load_first_image(session)

        # Load step and confirmed summary
        step_resp = steps_table.get_item(Key={"plan_id": plan_id, "step_seq": step_seq})
        step = step_resp.get("Item", {})
        conversation: list = list(step.get("conversation", []))

        all_steps = _query_all_steps(plan_id, steps_table)
        confirmed = [s for s in all_steps if s.get("status") == "confirmed"]
        if confirmed:
            confirmed_summary = "\n".join(
                f"Step {s['step_seq']} ({s.get('step_type','')}) — {s.get('step_name','')}:\n  {s.get('cq_code','')}"  # noqa: E501
                for s in confirmed
            )
        else:
            confirmed_summary = "（確定済みステップなし）"

        # Build messages: synthetic first user (image + original NEXT_STEP_PROMPT), then conversation, then new user
        import base64
        initial_user_content: list = []
        if image_bytes:
            initial_user_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_media_type,
                    "data": base64.b64encode(image_bytes).decode(),
                },
            })
        initial_user_content.append({
            "type": "text",
            "text": NEXT_STEP_PROMPT.format(confirmed_steps=confirmed_summary),
        })

        messages: list[dict] = [{"role": "user", "content": initial_user_content}]
        for entry in conversation:
            messages.append({
                "role": entry["role"],
                "content": str(entry["content"]),
            })
        messages.append({
            "role": "user",
            "content": (
                f"{user_message}\n\n"
                "上記の指摘を必ず反映して、修正版をJSON形式のみで出力してください。"
                "前回と同じ内容は繰り返さないでください。"
            ),
        })

        from common.bedrock_client import get_bedrock_client
        client = get_bedrock_client(region=BEDROCK_REGION)
        invoke_result = client.invoke_with_messages(
            messages=messages,
            system_prompt=REVISE_SYSTEM_PROMPT,
            max_tokens=4096,
        )

        ai_output = _parse_ai_response(invoke_result.text)
        now = int(time.time())

        # Append to conversation history
        new_conversation = list(conversation) + [
            {"role": "user", "content": user_message, "timestamp": now},
            {"role": "assistant", "content": invoke_result.text, "timestamp": now},
        ]

        # Update step with revised proposal
        # NOTE: "parameters" is a DynamoDB reserved keyword → must use ExpressionAttributeNames
        choices = _float_to_decimal(ai_output.get("choices", []))
        steps_table.update_item(
            Key={"plan_id": plan_id, "step_seq": step_seq},
            UpdateExpression=(
                "SET step_type = :stype, step_name = :sname, "
                "#params = :params, cq_code = :code, "
                "group_id = :gid, confidence = :conf, "
                "ai_reasoning = :reason, choices = :ch, conversation = :conv"
            ),
            ExpressionAttributeNames={"#params": "parameters"},
            ExpressionAttributeValues={
                ":stype": ai_output.get("step_type", step.get("step_type", "")),
                ":sname": ai_output.get("step_name", step.get("step_name", "")),
                ":params": _float_to_decimal(ai_output.get("parameters", {})),
                ":code": ai_output.get("cq_code", step.get("cq_code", "")),
                ":gid": ai_output.get("group_id", step.get("group_id", "")),
                ":conf": Decimal(str(ai_output.get("confidence", 0.0))),
                ":reason": ai_output.get("explanation", ""),
                ":ch": choices,
                ":conv": new_conversation,
            },
        )

        # Update plan status back to ready
        plans_table.update_item(
            Key={"plan_id": plan_id},
            UpdateExpression="SET current_step_status = :css, updated_at = :now",
            ExpressionAttributeValues={":css": "ready", ":now": now},
        )

        logger.info("revise_step complete: plan_id=%s, seq=%s", plan_id, step_seq)

    except Exception as e:
        logger.error("revise_step failed for plan %s seq %s: %s", plan_id, step_seq, e, exc_info=True)
        plans_table.update_item(
            Key={"plan_id": plan_id},
            UpdateExpression="SET current_step_status = :css, updated_at = :now",
            ExpressionAttributeValues={":css": "ready", ":now": int(time.time())},
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
