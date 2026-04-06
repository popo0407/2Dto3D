from __future__ import annotations

import json
import base64
import logging
from dataclasses import dataclass, field
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


@dataclass
class InvokeResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class BedrockClient:
    def __init__(self, region: str = "ap-northeast-1") -> None:
        self._client = boto3.client("bedrock-runtime", region_name=region)

    def invoke_multimodal(
        self,
        prompt: str,
        image_bytes: Optional[bytes] = None,
        image_media_type: str = "image/png",
        context_json: Optional[dict] = None,
        system_prompt: str = SYSTEM_PROMPT,
        max_tokens: int = 8192,
    ) -> str:
        content: list[dict] = []

        if image_bytes:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image_media_type,
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

        logger.info("Invoking Bedrock model %s (streaming)", MODEL_ID)
        response = self._client.invoke_model_with_response_stream(
            modelId=MODEL_ID,
            body=body,
            contentType="application/json",
            accept="application/json",
        )

        full_text = ""
        input_tokens = 0
        output_tokens = 0
        for event in response["body"]:
            chunk = json.loads(event["chunk"]["bytes"])
            chunk_type = chunk.get("type")
            if chunk_type == "message_start":
                usage = chunk.get("message", {}).get("usage", {})
                input_tokens += usage.get("input_tokens", 0)
            elif chunk_type == "content_block_delta":
                delta = chunk.get("delta", {})
                if delta.get("type") == "text_delta":
                    full_text += delta.get("text", "")
            elif chunk_type == "message_delta":
                usage = chunk.get("usage", {})
                output_tokens += usage.get("output_tokens", 0)
        return InvokeResult(text=full_text, input_tokens=input_tokens, output_tokens=output_tokens)


    def invoke_with_messages(
        self,
        messages: list[dict],
        system_prompt: str = SYSTEM_PROMPT,
        max_tokens: int = 4096,
    ) -> InvokeResult:
        """Call Claude with a pre-built messages array for multi-turn conversations."""
        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": messages,
            }
        )
        logger.info("Invoking Bedrock model %s with conversation history (streaming)", MODEL_ID)
        response = self._client.invoke_model_with_response_stream(
            modelId=MODEL_ID,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        full_text = ""
        input_tokens = 0
        output_tokens = 0
        for event in response["body"]:
            chunk = json.loads(event["chunk"]["bytes"])
            chunk_type = chunk.get("type")
            if chunk_type == "message_start":
                usage = chunk.get("message", {}).get("usage", {})
                input_tokens += usage.get("input_tokens", 0)
            elif chunk_type == "content_block_delta":
                delta = chunk.get("delta", {})
                if delta.get("type") == "text_delta":
                    full_text += delta.get("text", "")
            elif chunk_type == "message_delta":
                usage = chunk.get("usage", {})
                output_tokens += usage.get("output_tokens", 0)
        return InvokeResult(text=full_text, input_tokens=input_tokens, output_tokens=output_tokens)


def get_bedrock_client(region: str = "ap-northeast-1") -> BedrockClient:
    return BedrockClient(region=region)
