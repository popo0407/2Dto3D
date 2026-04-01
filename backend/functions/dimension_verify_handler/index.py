"""Step Functions Step: Recursive dimension verification via Bedrock.

Iteratively re-checks low-confidence drawing elements, incorporating
human feedback. Assembles intermediate CadQuery scripts using a
template-based approach (orientation → .faces() mapping).
"""
from __future__ import annotations

import json
import logging
import os
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key, Attr
from common.ws_notify import send_progress

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DRAWING_ELEMENTS_TABLE = os.environ.get("DRAWING_ELEMENTS_TABLE", "")
SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "")
NODES_TABLE = os.environ.get("NODES_TABLE", "")
UPLOADS_BUCKET = os.environ.get("UPLOADS_BUCKET", "")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "ap-northeast-1")
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.85"))
MAX_VERIFY_ITERATIONS = int(os.environ.get("MAX_VERIFY_ITERATIONS", "5"))

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")


VERIFY_PROMPT = """以下の2D図面の設計要素について、確度が低い項目を再検証してください。

【低確度要素（要再検証）】
{low_confidence_elements}

【高確度要素（参考情報）】
{high_confidence_summary}

{human_comment_section}

【出力形式（JSON配列）】
再検証した要素のみを以下の形式で出力してください（高確度要素は含めないでください）。
```json
[
  {{
    "element_seq": "0001",
    "element_type": "tapped_hole",
    "feature_label": "Hole-M6-01: タップ穴 +Z",
    "feature_spec": {{
      "hole_type": "tapped",
      "designation": "M6",
      "pitch": 1.0,
      "tap_depth": 15.0,
      "drill_diameter": 5.0,
      "through": false,
      "standard": "JIS"
    }},
    "dimensions": {{"diameter": 5.0, "depth": 15.0}},
    "position": {{"x": 30.0, "y": 15.0, "z": 0.0}},
    "orientation": "+Z",
    "cq_fragment": "result = result.faces(\\">Z\\").workplane().pushPoints([(30,15)]).hole(5.0, 15.0)",
    "confidence": 0.90,
    "ai_reasoning": "M6規格（JIS B 0205）の下穴径5.0mm、タップ深さは板厚の75%で推定"
  }}
]
```

【feature_spec スキーマ（element_type ごと）】

■ hole_through（貫通穴）
  {{"hole_type": "through", "diameter": 6.0}}

■ hole_blind（止め穴）
  {{"hole_type": "blind", "diameter": 6.0, "depth": 10.0}}

■ tapped_hole（ネジ穴・タップ穴）
  {{
    "hole_type": "tapped",
    "designation": "M6",
    "pitch": 1.0,
    "tap_depth": 15.0,
    "drill_diameter": 5.0,
    "through": false,
    "standard": "JIS"
  }}

■ fillet（R面取り）
  {{"radius": 2.0, "edge_selector": "|Z", "quantity": 4}}

■ chamfer（C面取り）
  {{"distance": 1.0, "angle": 45.0, "edge_selector": "|Z", "quantity": 2}}

■ slot（長穴）
  {{"width": 6.0, "length": 20.0, "depth": null, "orientation": "+Z"}}

■ pocket（ポケット）
  {{"width": 30.0, "height": 20.0, "depth": 5.0}}

【確度の基準】
- 0.95-1.0: 図面に寸法が明示的に記載
- 0.80-0.94: 幾何要素から計算可能、または標準規格で推定
- 0.60-0.79: 対称性やパターンからの推定
- 0.40-0.59: 曖昧さがある
- 0.00-0.39: 低確信度の推測

【重要】
- 前回より確度が上がるよう、図面を注意深く再確認してください
- ネジ穴は必ず element_type = "tapped_hole" で出力し、feature_spec に JIS/ISO 規格値を記載すること
- JSON配列のみを出力してください
"""

FINAL_ASSEMBLY_PROMPT = """以下の確定済みの設計要素群から、最終的なCadQueryスクリプトを組み立ててください。
すべての要素の整合性を確認し、実行可能なスクリプトを生成してください。

【設計要素一覧】
{all_elements}

【ルール】
- `import cadquery as cq` で始める
- 各フィーチャーに `# Feature-NNN:` コメントを付ける
- 穴は `# Hole-NNN:` で管理
- 同一面・同一径・同一深さの穴は `.pushPoints()` でグループ化
- 穴は必ず `.faces("...").workplane().pushPoints([...]).hole(d)` 形式
- `show_object()` は使用禁止
- 最後に `result` 変数にソリッドが格納されていること

【出力フォーマット(JSON)】
```json
{{
  "cadquery_script": "import cadquery as cq\\n...",
  "assembly_reasoning": "組み立て時の確認事項・修正点"
}}
```
"""


def lambda_handler(event: dict, context) -> dict:
    """Verify low-confidence drawing elements and optionally assemble final script.

    Input:
        {"session_id": "...", "node_id": "...", "iteration_count": N, "is_final": false,
         "cadquery_script": "...", "total_elements": N, "low_confidence_count": N}
    Output:
        {"session_id": "...", "node_id": "...", "all_verified": bool,
         "iteration_count": N, "cadquery_script": "...", ...}
    """
    session_id = event["session_id"]
    node_id = event["node_id"]
    iteration_count = event.get("iteration_count", 0) + 1
    is_final = event.get("is_final", False)
    cadquery_script = event.get("cadquery_script", "")

    logger.info(
        "Verification iteration %d for session %s (is_final=%s)",
        iteration_count,
        session_id,
        is_final,
    )

    # Update session status
    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET #s = :status, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "VERIFYING_DIMENSIONS",
            ":now": int(time.time()),
        },
    )

    step_label = "VERIFYING_DIMENSIONS"
    progress_pct = 40 + min(iteration_count * 8, 40)
    send_progress(
        session_id,
        step_label,
        progress_pct,
        f"寸法検証中... (反復 {iteration_count}/{MAX_VERIFY_ITERATIONS})",
    )

    # --- Read and clear human comment ---
    human_comment = _read_and_clear_comment(session_id, sessions_table)

    # --- Query drawing elements ---
    elements_table = dynamodb.Table(DRAWING_ELEMENTS_TABLE)
    all_elements = _query_all_elements(session_id, elements_table)
    low_conf_elements = [
        e for e in all_elements if float(e.get("confidence", 0)) < CONFIDENCE_THRESHOLD
    ]
    high_conf_elements = [
        e for e in all_elements if float(e.get("confidence", 0)) >= CONFIDENCE_THRESHOLD
    ]

    # If all verified already, skip AI call
    if not low_conf_elements and not is_final:
        logger.info("All elements verified for session %s", session_id)
        assembled_script = _assemble_script_template(all_elements)
        return _build_output(
            session_id, node_id, cadquery_script=assembled_script,
            all_verified=True, iteration_count=iteration_count,
            total_elements=len(all_elements), low_confidence_count=0,
        )

    # --- Load image for multimodal context ---
    image_bytes, image_media_type = _load_first_image(session_id, sessions_table)

    from common.bedrock_client import get_bedrock_client
    client = get_bedrock_client(region=BEDROCK_REGION)

    if is_final:
        # Final assembly: AI integrates all fragments into coherent script
        assembled_script = _final_assembly(client, all_elements, image_bytes, image_media_type)
        # Validate the assembled script
        from common.script_validator import validate_cadquery_script, ScriptValidationError
        try:
            validate_cadquery_script(assembled_script)
        except ScriptValidationError as e:
            logger.error("Final assembly script validation failed: %s", e)
            raise RuntimeError(f"Final assembly validation failed: {e}") from e

        # Update node with final script
        nodes_table = dynamodb.Table(NODES_TABLE)
        nodes_table.update_item(
            Key={"node_id": node_id},
            UpdateExpression="SET cadquery_script = :script",
            ExpressionAttributeValues={":script": assembled_script},
        )

        send_progress(session_id, step_label, 85, "最終スクリプト組み立て完了")

        return _build_output(
            session_id, node_id, cadquery_script=assembled_script,
            all_verified=True, iteration_count=iteration_count,
            total_elements=len(all_elements), low_confidence_count=0,
        )

    # --- Regular verification iteration ---
    updated_elements = _verify_elements(
        client, low_conf_elements, high_conf_elements,
        human_comment, image_bytes, image_media_type,
    )

    # Update DynamoDB with new confidence scores
    low_after_update = 0
    for updated in updated_elements:
        seq = updated.get("element_seq", "")
        if not seq:
            continue
        new_confidence = float(updated.get("confidence", 0.0))
        if new_confidence < CONFIDENCE_THRESHOLD:
            low_after_update += 1

        elements_table.update_item(
            Key={"drawing_id": session_id, "element_seq": seq},
            UpdateExpression=(
                "SET confidence = :conf, is_verified = :ver, "
                "ai_reasoning = :reason, verification_count = verification_count + :one, "
                "cq_fragment = :frag, dimensions = :dims, "
                "#pos = :pos, orientation = :orient, "
                "element_type = :etype, feature_label = :flabel, "
                "feature_spec = :fspec"
            ),
            ExpressionAttributeNames={"#pos": "position"},
            ExpressionAttributeValues={
                ":conf": Decimal(str(new_confidence)),
                ":ver": new_confidence >= CONFIDENCE_THRESHOLD,
                ":reason": updated.get("ai_reasoning", ""),
                ":one": 1,
                ":frag": updated.get("cq_fragment", ""),
                ":dims": _float_to_decimal(updated.get("dimensions", {})),
                ":pos": _float_to_decimal(updated.get("position", {})),
                ":orient": updated.get("orientation", ""),
                ":etype": updated.get("element_type", ""),
                ":flabel": updated.get("feature_label", ""),
                ":fspec": _float_to_decimal(updated.get("feature_spec", {})),
            },
        )

    # Re-query for latest state and assemble intermediate script
    all_elements_updated = _query_all_elements(session_id, elements_table)
    assembled_script = _assemble_script_template(all_elements_updated)

    # Update node with intermediate script
    nodes_table = dynamodb.Table(NODES_TABLE)
    nodes_table.update_item(
        Key={"node_id": node_id},
        UpdateExpression="SET cadquery_script = :script, ai_reasoning = :reason",
        ExpressionAttributeValues={
            ":script": assembled_script,
            ":reason": f"反復 {iteration_count}: {len(updated_elements)}要素を再検証",
        },
    )

    all_verified = low_after_update == 0

    # Send verification progress via WebSocket (includes element data for frontend preview)
    _send_verification_progress(session_id, all_elements_updated, iteration_count, all_verified)

    return _build_output(
        session_id, node_id, cadquery_script=assembled_script,
        all_verified=all_verified, iteration_count=iteration_count,
        total_elements=len(all_elements_updated), low_confidence_count=low_after_update,
    )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _build_output(
    session_id: str,
    node_id: str,
    cadquery_script: str,
    all_verified: bool,
    iteration_count: int,
    total_elements: int,
    low_confidence_count: int,
) -> dict:
    return {
        "session_id": session_id,
        "node_id": node_id,
        "cadquery_script": cadquery_script,
        "all_verified": all_verified,
        "iteration_count": iteration_count,
        "total_elements": total_elements,
        "low_confidence_count": low_confidence_count,
    }


def _read_and_clear_comment(session_id: str, sessions_table) -> str:
    """Read pending human comment and clear it atomically."""
    resp = sessions_table.get_item(Key={"session_id": session_id})
    session = resp.get("Item", {})
    comment = session.get("pending_verify_comment", "")
    if comment:
        sessions_table.update_item(
            Key={"session_id": session_id},
            UpdateExpression="SET pending_verify_comment = :empty",
            ExpressionAttributeValues={":empty": ""},
        )
        logger.info("Read human comment for session %s: %s", session_id, comment[:100])
    return comment


def _query_all_elements(session_id: str, elements_table) -> list[dict]:
    """Query all drawing elements for a session, sorted by element_seq."""
    items = []
    resp = elements_table.query(
        KeyConditionExpression=Key("drawing_id").eq(session_id),
    )
    items.extend(resp.get("Items", []))
    while resp.get("LastEvaluatedKey"):
        resp = elements_table.query(
            KeyConditionExpression=Key("drawing_id").eq(session_id),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        items.extend(resp.get("Items", []))
    return sorted(items, key=lambda x: x.get("element_seq", ""))


def _load_first_image(session_id: str, sessions_table) -> tuple:
    """Load first image file from session for multimodal context."""
    resp = sessions_table.get_item(Key={"session_id": session_id})
    session = resp.get("Item", {})
    input_files = session.get("input_files", [])

    for f in input_files:
        ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
        if ext in ("png", "jpg", "jpeg", "tiff", "tif"):
            try:
                obj = s3_client.get_object(Bucket=UPLOADS_BUCKET, Key=f)
                media_map = {
                    "png": "image/png",
                    "jpg": "image/jpeg",
                    "jpeg": "image/jpeg",
                    "tiff": "image/tiff",
                    "tif": "image/tiff",
                }
                return obj["Body"].read(), media_map.get(ext, "image/png")
            except Exception as e:
                logger.warning("Failed to load image %s: %s", f, e)

    return None, "image/png"


def _verify_elements(
    client,
    low_conf_elements: list[dict],
    high_conf_elements: list[dict],
    human_comment: str,
    image_bytes: bytes | None,
    image_media_type: str,
) -> list[dict]:
    """Invoke Bedrock to re-verify low-confidence elements."""
    low_conf_text = json.dumps(
        [_element_to_prompt_dict(e) for e in low_conf_elements],
        ensure_ascii=False,
        indent=2,
    )

    high_conf_summary = json.dumps(
        [
            {
                "element_seq": e["element_seq"],
                "feature_label": e.get("feature_label", ""),
                "dimensions": _decimal_to_float(e.get("dimensions", {})),
                "orientation": e.get("orientation", ""),
            }
            for e in high_conf_elements
        ],
        ensure_ascii=False,
        indent=2,
    )

    human_section = ""
    if human_comment:
        human_section = f"【ユーザーからのコメント】\n{human_comment}\n上記のコメントを踏まえて検証してください。"

    prompt = VERIFY_PROMPT.format(
        low_confidence_elements=low_conf_text,
        high_confidence_summary=high_conf_summary,
        human_comment_section=human_section,
    )

    raw_response = client.invoke_multimodal(
        prompt=prompt,
        image_bytes=image_bytes,
        image_media_type=image_media_type,
    )

    return _parse_elements(raw_response)


def _final_assembly(
    client,
    all_elements: list[dict],
    image_bytes: bytes | None,
    image_media_type: str,
) -> str:
    """Final AI-assisted assembly of all elements into a coherent CadQuery script."""
    elements_text = json.dumps(
        [_element_to_prompt_dict(e) for e in all_elements],
        ensure_ascii=False,
        indent=2,
    )

    prompt = FINAL_ASSEMBLY_PROMPT.format(all_elements=elements_text)

    raw_response = client.invoke_multimodal(
        prompt=prompt,
        image_bytes=image_bytes,
        image_media_type=image_media_type,
    )

    # Parse JSON response
    text = raw_response.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed.get("cadquery_script", "")
        except json.JSONDecodeError:
            pass

    # If not JSON, assume the entire response is the script
    logger.warning("Final assembly response not JSON, using raw text")
    return text


def _assemble_script_template(elements: list[dict]) -> str:
    """Deterministic template-based script assembly from element fragments.

    Uses orientation attribute to generate correct .faces() calls.
    Handles tapped_hole, fillet, chamfer via feature_spec.
    """
    if not elements:
        return "import cadquery as cq\nresult = cq.Workplane('XY').box(10, 10, 10)\n"

    lines = ["import cadquery as cq", ""]

    # Separate base body from features
    base_elements = [e for e in elements if e.get("element_type") == "box"]
    feature_elements = [e for e in elements if e.get("element_type") != "box"]

    # Base body first
    for elem in base_elements:
        frag = elem.get("cq_fragment", "")
        label = elem.get("feature_label", "base")
        if frag:
            lines.append(f"# {label}")
            lines.append(frag)
            lines.append("")

    # If no base body fragment, fallback
    if not base_elements:
        lines.append("# base_body (auto-generated)")
        lines.append("result = cq.Workplane('XY').box(10, 10, 10)")
        lines.append("")

    orientation_faces_map = {
        "+Z": '">Z"',
        "-Z": '"<Z"',
        "+Y": '">Y"',
        "-Y": '"<Y"',
        "+X": '">X"',
        "-X": '"<X"',
    }

    # --- 通常穴（hole_through / hole_blind / 旧 hole タイプ）をグループ化 ---
    plain_hole_types = {"hole_through", "hole_blind", "hole"}
    hole_elements = [e for e in feature_elements if e.get("element_type") in plain_hole_types]
    tapped_elements = [e for e in feature_elements if e.get("element_type") == "tapped_hole"]
    fillet_elements = [e for e in feature_elements if e.get("element_type") == "fillet"]
    chamfer_elements = [e for e in feature_elements if e.get("element_type") == "chamfer"]
    other_features = [
        e for e in feature_elements
        if e.get("element_type") not in {*plain_hole_types, "tapped_hole", "fillet", "chamfer"}
    ]

    # --- 通常穴: (orientation, diameter, depth) でグループ化して pushPoints ---
    hole_groups: dict[tuple, list[dict]] = {}
    for h in hole_elements:
        spec = _decimal_to_float(h.get("feature_spec", {}))
        dims = _decimal_to_float(h.get("dimensions", {}))
        orient = h.get("orientation", "+Z")
        diameter = spec.get("diameter") or dims.get("diameter", 0)
        depth = spec.get("depth") or dims.get("depth")
        key = (orient, diameter, depth)
        hole_groups.setdefault(key, []).append(h)

    for (orient, diameter, depth), holes in hole_groups.items():
        faces_selector = orientation_faces_map.get(orient, '">Z"')
        positions = []
        labels = []
        for h in holes:
            pos = _decimal_to_float(h.get("position", {}))
            x = pos.get("x", 0)
            y = pos.get("y", 0)
            positions.append(f"({x}, {y})")
            labels.append(h.get("feature_label", ""))

        label_str = ", ".join(labels) if labels else "holes"
        lines.append(f"# {label_str}")
        points_str = ", ".join(positions)
        depth_arg = f", {depth}" if depth else ""
        lines.append(
            f"result = result.faces({faces_selector}).workplane()"
            f".pushPoints([{points_str}]).hole({diameter}{depth_arg})"
        )
        lines.append("")

    # --- タップ穴: feature_spec.drill_diameter で下穴、tap_depth でタップ ---
    for h in tapped_elements:
        frag = h.get("cq_fragment", "")
        label = h.get("feature_label", "tapped_hole")
        spec = _decimal_to_float(h.get("feature_spec", {}))
        if frag:
            lines.append(f"# {label} ({spec.get('designation', '')} pitch={spec.get('pitch', '')})")
            lines.append(frag)
        else:
            # cq_fragment がない場合は feature_spec から自動生成
            orient = h.get("orientation", "+Z")
            faces_selector = orientation_faces_map.get(orient, '">Z"')
            pos = _decimal_to_float(h.get("position", {}))
            drill_d = spec.get("drill_diameter", 0)
            tap_depth = spec.get("tap_depth")
            depth_arg = f", {tap_depth}" if tap_depth else ""
            lines.append(f"# {label} ({spec.get('designation', '')})")
            lines.append(
                f"result = result.faces({faces_selector}).workplane()"
                f".pushPoints([({pos.get('x', 0)}, {pos.get('y', 0)})]).hole({drill_d}{depth_arg})"
            )
        lines.append("")

    # --- フィレット ---
    for elem in fillet_elements:
        frag = elem.get("cq_fragment", "")
        label = elem.get("feature_label", "fillet")
        spec = _decimal_to_float(elem.get("feature_spec", {}))
        if frag:
            lines.append(f"# {label}")
            lines.append(frag)
        else:
            radius = spec.get("radius", 0)
            edge_sel = spec.get("edge_selector", "|Z")
            lines.append(f"# {label} R={radius}")
            lines.append(f'result = result.edges("{edge_sel}").fillet({radius})')
        lines.append("")

    # --- シャンファー ---
    for elem in chamfer_elements:
        frag = elem.get("cq_fragment", "")
        label = elem.get("feature_label", "chamfer")
        spec = _decimal_to_float(elem.get("feature_spec", {}))
        if frag:
            lines.append(f"# {label}")
            lines.append(frag)
        else:
            dist = spec.get("distance", 0)
            edge_sel = spec.get("edge_selector", "|Z")
            lines.append(f"# {label} C={dist}")
            lines.append(f'result = result.edges("{edge_sel}").chamfer({dist})')
        lines.append("")

    # --- その他フィーチャー ---
    for elem in other_features:
        frag = elem.get("cq_fragment", "")
        label = elem.get("feature_label", "feature")
        if frag:
            lines.append(f"# {label}")
            lines.append(frag)
            lines.append("")

    return "\n".join(lines)


def _element_to_prompt_dict(elem: dict) -> dict:
    """Convert a DynamoDB element item to a clean dict for the AI prompt."""
    return {
        "element_seq": elem.get("element_seq", ""),
        "element_type": elem.get("element_type", ""),
        "feature_label": elem.get("feature_label", ""),
        "feature_spec": _decimal_to_float(elem.get("feature_spec", {})),
        "dimensions": _decimal_to_float(elem.get("dimensions", {})),
        "position": _decimal_to_float(elem.get("position", {})),
        "orientation": elem.get("orientation", ""),
        "cq_fragment": elem.get("cq_fragment", ""),
        "confidence": float(elem.get("confidence", 0)),
        "ai_reasoning": elem.get("ai_reasoning", ""),
    }


def _decimal_to_float(obj):
    """Recursively convert Decimal values to float for JSON serialization."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_float(i) for i in obj]
    return obj


def _parse_elements(raw_response: str) -> list[dict]:
    """Extract JSON array of elements from AI response text."""
    text = raw_response.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    logger.error("Failed to parse elements from AI response: %s...", text[:200])
    raise RuntimeError("AI response does not contain valid JSON element array")


def _float_to_decimal(obj):
    """Recursively convert float values to Decimal for DynamoDB storage."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _float_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_float_to_decimal(i) for i in obj]
    return obj


def _send_verification_progress(
    session_id: str,
    elements: list[dict],
    iteration_count: int,
    all_verified: bool,
) -> None:
    """Send VERIFICATION_PROGRESS via WebSocket with element data for frontend preview."""
    api_id = os.environ.get("WEBSOCKET_API_ID", "")
    connections_table_name = os.environ.get("CONNECTIONS_TABLE", "")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    stage = os.environ.get("ENV_NAME", "dev")

    if not api_id or not connections_table_name:
        return

    try:
        conn_table = dynamodb.Table(connections_table_name)
        resp = conn_table.scan(FilterExpression=Attr("session_id").eq(session_id))
        connections = resp.get("Items", [])
        if not connections:
            return

        endpoint_url = f"https://{api_id}.execute-api.{region}.amazonaws.com/{stage}"
        apigw = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint_url)

        # Build element summary for frontend (Three.js primitive preview)
        element_preview = [
            {
                "element_seq": e.get("element_seq", ""),
                "element_type": e.get("element_type", ""),
                "feature_label": e.get("feature_label", ""),
                "dimensions": _decimal_to_float(e.get("dimensions", {})),
                "position": _decimal_to_float(e.get("position", {})),
                "orientation": e.get("orientation", ""),
                "confidence": float(e.get("confidence", 0)),
                "is_verified": e.get("is_verified", False),
            }
            for e in elements
        ]

        payload = json.dumps({
            "type": "VERIFICATION_PROGRESS",
            "session_id": session_id,
            "iteration_count": iteration_count,
            "all_verified": all_verified,
            "elements": element_preview,
        }).encode()

        for conn in connections:
            try:
                apigw.post_to_connection(ConnectionId=conn["connection_id"], Data=payload)
            except Exception:
                pass
    except Exception as e:
        logger.warning("_send_verification_progress failed: %s", e)
