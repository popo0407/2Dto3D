from __future__ import annotations

import json
import base64
import logging
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """あなたは機械設計の専門家であり、CADオペレーターです。
提供された図面を以下の優先順位で解釈してください：

【解釈の優先順位】
1. 明示的な数値寸法（記入された数字）
2. 図面の幾何要素から計算できる寸法
3. 標準規格（JIS/ISO）に基づく推定
4. 図面の対称性・繰り返しパターン

【出力形式】
- CadQueryスクリプト（実行可能Python）
- 確度スコア（Feature単位）
- 不明箇所の質問リスト（最大5件、優先度付き）

【禁止事項】
- 図面に記載のない形状の付加
- 寸法の独断的な丸め（±0.5mm超）
- 閉じていないソリッド（Water-tightでない形状）"""

MODEL_ID = "jp.anthropic.claude-sonnet-4-6"


class BedrockClient:
    def __init__(self, region: str = "ap-northeast-1") -> None:
        self._client = boto3.client("bedrock-runtime", region_name=region)

    def invoke_multimodal(
        self,
        prompt: str,
        image_bytes: Optional[bytes] = None,
        context_json: Optional[dict] = None,
        system_prompt: str = SYSTEM_PROMPT,
        max_tokens: int = 4096,
    ) -> str:
        content: list[dict] = []

        if image_bytes:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(image_bytes).decode(),
                    },
                }
            )

        if context_json:
            content.append(
                {
                    "type": "text",
                    "text": f"【図面の幾何情報（JSON）】\n{json.dumps(context_json, ensure_ascii=False, indent=2)}",
                }
            )

        content.append({"type": "text", "text": prompt})

        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": [{"role": "user", "content": content}],
            }
        )

        logger.info("Invoking Bedrock model %s", MODEL_ID)
        response = self._client.invoke_model(
            modelId=MODEL_ID,
            body=body,
            contentType="application/json",
            accept="application/json",
        )

        result = json.loads(response["body"].read())
        return result["content"][0]["text"]


class MockBedrockClient:
    """dev環境のモックAIクライアント"""

    def invoke_multimodal(
        self,
        prompt: str,
        image_bytes: Optional[bytes] = None,
        context_json: Optional[dict] = None,
        system_prompt: str = "",
        max_tokens: int = 4096,
    ) -> str:
        logger.info("[MOCK] Bedrock invocation with prompt length=%d", len(prompt))
        return json.dumps(
            {
                "cadquery_script": _MOCK_CADQUERY_SCRIPT,
                "confidence_map": {
                    "Feature-001": 0.95,
                    "Feature-002": 0.80,
                },
                "questions": [],
            },
            ensure_ascii=False,
        )


_MOCK_CADQUERY_SCRIPT = '''import cadquery as cq

# Feature-001: 基底矩形板
BASE_WIDTH = 100.0   # mm
BASE_HEIGHT = 50.0   # mm
BASE_DEPTH = 20.0    # mm
base = cq.Workplane("XY").box(BASE_WIDTH, BASE_HEIGHT, BASE_DEPTH)

# Feature-002: 貫通穴
HOLE_DIAMETER = 6.0  # mm
result = base.faces(">Z").workplane().hole(HOLE_DIAMETER)
'''


def get_bedrock_client(use_mock: bool, region: str = "ap-northeast-1"):
    if use_mock:
        return MockBedrockClient()
    return BedrockClient(region=region)
