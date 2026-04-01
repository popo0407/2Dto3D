"""Step Functions Step: Extract drawing elements and confidence scores via Bedrock.

Parses the AI-generated CadQuery script into individual drawing elements,
storing each with a confidence score in the drawing_elements DynamoDB table.
"""
from __future__ import annotations

import json
import logging
import os
import time
from decimal import Decimal

import boto3
from common.ws_notify import send_progress

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DRAWING_ELEMENTS_TABLE = os.environ.get("DRAWING_ELEMENTS_TABLE", "")
SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "")
NODES_TABLE = os.environ.get("NODES_TABLE", "")
UPLOADS_BUCKET = os.environ.get("UPLOADS_BUCKET", "")
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "ap-northeast-1")

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")

EXTRACT_PROMPT = """添付の2D図面画像と、AIが生成した以下のCadQueryスクリプトを解析し、
各設計要素（Feature）ごとに寸法情報と確度を抽出してください。

【CadQueryスクリプト】
```python
{cadquery_script}
```

【出力形式（JSON配列）】
各要素を以下の形式で出力してください。
```json
[
  {{
    "element_type": "box" | "hole_through" | "hole_blind" | "tapped_hole" | "fillet" | "chamfer" | "slot" | "pocket" | "boss" | "rib" | "other",
    "feature_label": "Feature-001: base_body" のようなラベル,
    "feature_spec": {{
      /* element_type に応じた詳細パラメータ（下記スキーマ参照） */
    }},
    "dimensions": {{
      "width": 100.0, "height": 60.0, "depth": 20.0,
      "diameter": null, "radius": null
    }},
    "position": {{"x": 0.0, "y": 0.0, "z": 0.0}},
    "orientation": "+Z" | "-Z" | "+Y" | "-Y" | "+X" | "-X" | "XY" | "",
    "cq_fragment": "result = cq.Workplane(\\"XY\\").box(100, 60, 20)",
    "confidence": 0.95,
    "ai_reasoning": "図面に100×60×20の寸法が明記されている"
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
    "designation": "M6",        // JIS/ISO ネジ呼び径 (例: M6, M8x1.25)
    "pitch": 1.0,                // ネジピッチ (mm)
    "tap_depth": 15.0,           // タップ深さ (mm); 貫通の場合は null
    "drill_diameter": 5.0,       // 下穴径 (mm)
    "through": false,            // 貫通タップの場合 true
    "standard": "JIS"            // "JIS" | "ISO" | "UNC" | "UNF" | "other"
  }}

■ fillet（R面取り）
  {{
    "radius": 2.0,
    "edge_selector": "|Z",       // CadQuery エッジセレクタ (例: "|Z", ">Z or <Z")
    "quantity": 4                // 対象エッジ本数
  }}

■ chamfer（C面取り）
  {{
    "distance": 1.0,             // 面取り量 (mm)
    "angle": 45.0,               // 面取り角度 (deg); 45°以外の場合のみ記入
    "edge_selector": "|Z",
    "quantity": 2
  }}

■ slot（長穴）
  {{"width": 6.0, "length": 20.0, "depth": null, "orientation": "+Z"}}

■ pocket（ポケット）
  {{"width": 30.0, "height": 20.0, "depth": 5.0}}

【確度の基準】
- 0.95-1.0: 図面に寸法が明示的に記載されている
- 0.80-0.94: 幾何要素から計算可能、または標準規格で推定
- 0.60-0.79: 対称性やパターンからの推定
- 0.40-0.59: 図面からの読み取りに曖昧さがある
- 0.00-0.39: 確信度が低い推測

【重要】
- CadQueryスクリプト中の `# Feature-NNN:` や `# Hole-NNN:` コメントを要素のラベルに使用
- cq_fragment は各要素に対応するCadQueryコードの断片（実行可能な形式）
- orientation は穴やポケットのドリル方向（.faces() の引数に対応）
- ネジ穴は必ず element_type = "tapped_hole" で出力すること
- フィレット・シャンファーは element_type = "fillet" / "chamfer" で独立して出力すること
- base_body（ベースとなるbox等）は必ず最初の要素として含める
- JSON配列のみを出力してください（説明文は不要）
"""


def lambda_handler(event: dict, context) -> dict:
    """Extract drawing elements from CadQuery script and store in DynamoDB.

    Input:
        {"session_id": "...", "node_id": "...", "cadquery_script": "...", "ai_reasoning": "..."}
    Output:
        {"session_id": "...", "node_id": "...", "total_elements": N, "low_confidence_count": N}
    """
    session_id = event["session_id"]
    node_id = event["node_id"]
    cadquery_script = event.get("cadquery_script", "")
    logger.info("Extracting dimensions for session %s, node %s", session_id, node_id)

    send_progress(session_id, "EXTRACTING_DIMENSIONS", 35, "寸法要素を抽出中...")

    # Update session status
    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET #s = :status, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "EXTRACTING_DIMENSIONS",
            ":now": int(time.time()),
        },
    )

    # Load first image for multimodal context
    image_bytes = None
    image_media_type = "image/png"
    session_resp = sessions_table.get_item(Key={"session_id": session_id})
    session_item = session_resp.get("Item", {})
    input_files = session_item.get("input_files", [])

    for f in input_files:
        ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
        if ext in ("png", "jpg", "jpeg", "tiff", "tif"):
            try:
                obj = s3_client.get_object(Bucket=UPLOADS_BUCKET, Key=f)
                image_bytes = obj["Body"].read()
                media_map = {
                    "png": "image/png",
                    "jpg": "image/jpeg",
                    "jpeg": "image/jpeg",
                    "tiff": "image/tiff",
                    "tif": "image/tiff",
                }
                image_media_type = media_map.get(ext, "image/png")
                break
            except Exception as e:
                logger.warning("Failed to load image %s: %s", f, e)

    # Build extraction prompt
    prompt = EXTRACT_PROMPT.format(cadquery_script=cadquery_script)

    # Invoke Bedrock
    from common.bedrock_client import get_bedrock_client

    client = get_bedrock_client(region=BEDROCK_REGION)
    raw_response = client.invoke_multimodal(
        prompt=prompt,
        image_bytes=image_bytes,
        image_media_type=image_media_type,
    )

    # Parse element list from response
    elements = _parse_elements(raw_response)

    # Store elements in DynamoDB
    elements_table = dynamodb.Table(DRAWING_ELEMENTS_TABLE)
    ttl_value = int(time.time()) + 90 * 86400
    confidence_threshold = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.85"))
    low_confidence_count = 0

    with elements_table.batch_writer() as batch:
        for idx, elem in enumerate(elements):
            seq = f"{idx + 1:04d}"
            confidence = float(elem.get("confidence", 0.0))
            if confidence < confidence_threshold:
                low_confidence_count += 1

            item = {
                "drawing_id": session_id,
                "element_seq": seq,
                "element_type": elem.get("element_type", "other"),
                "feature_label": elem.get("feature_label", f"Element-{seq}"),
                "feature_spec": _float_to_decimal(elem.get("feature_spec", {})),
                "dimensions": _float_to_decimal(elem.get("dimensions", {})),
                "position": _float_to_decimal(elem.get("position", {})),
                "orientation": elem.get("orientation", ""),
                "cq_fragment": elem.get("cq_fragment", ""),
                "confidence": Decimal(str(confidence)),
                "is_verified": confidence >= confidence_threshold,
                "ai_reasoning": elem.get("ai_reasoning", ""),
                "verification_count": 0,
                "node_id": node_id,
                "ttl": ttl_value,
            }
            batch.put_item(Item=item)

    total_elements = len(elements)
    logger.info(
        "Extracted %d elements (%d low confidence) for session %s",
        total_elements,
        low_confidence_count,
        session_id,
    )

    send_progress(
        session_id,
        "EXTRACTING_DIMENSIONS",
        40,
        f"寸法要素{total_elements}個を抽出完了（低確度: {low_confidence_count}個）",
    )

    return {
        "session_id": session_id,
        "node_id": node_id,
        "cadquery_script": cadquery_script,
        "total_elements": total_elements,
        "low_confidence_count": low_confidence_count,
        "iteration_count": 0,
    }


def _parse_elements(raw_response: str) -> list[dict]:
    """Extract JSON array of elements from AI response text."""
    text = raw_response.strip()

    # Try to find JSON array in the response
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    # Try parsing the entire response as JSON
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
