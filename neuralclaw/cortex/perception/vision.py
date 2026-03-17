"""
Vision Perception - multimodal image understanding built on existing providers.
"""

from __future__ import annotations

import json
import re
from typing import Any

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.providers.router import LLMProvider


class VisionPerception:
    """Best-effort multimodal perception for inbound media and screenshots."""

    def __init__(self, provider: LLMProvider, bus: NeuralBus | None = None) -> None:
        self._provider = provider
        self._bus = bus

    async def describe(
        self,
        image_b64: str,
        context: str = "",
        detail: str = "auto",
    ) -> str:
        prompt = "Describe this image for the assistant. Focus on the concrete visible details."
        if context:
            prompt += f" User context: {context}"
        return await self._complete_text(prompt, image_b64=image_b64, detail=detail)

    async def extract_text(self, image_b64: str) -> str:
        return await self._complete_text(
            "Extract all readable text from this image. Preserve line breaks when possible.",
            image_b64=image_b64,
        )

    async def answer_about(self, image_b64: str, question: str) -> str:
        return await self._complete_text(
            f"Answer the user's question about this image. Question: {question}",
            image_b64=image_b64,
        )

    async def locate_element(self, screenshot_b64: str, description: str) -> dict[str, Any] | None:
        response = await self._complete_text(
            (
                "Find the described UI element in this screenshot and return only JSON with "
                "keys x, y, confidence. Use integer pixel coordinates relative to the image. "
                f"Description: {description}"
            ),
            image_b64=screenshot_b64,
        )
        return self._extract_json_object(response)

    async def process_media(self, media_item: dict[str, Any], user_query: str) -> str:
        image_url = self._resolve_image_url(media_item)
        if not image_url:
            return ""

        query = (user_query or "").strip()
        query_lower = query.lower()

        if any(token in query_lower for token in ("ocr", "extract text", "read this", "what does this say")):
            text = await self._complete_text(
                "Extract all readable text from this image. Preserve line breaks when possible.",
                image_url=image_url,
            )
            return f"Text extracted from image:\n{text}".strip()

        if "?" in query or query_lower.startswith(
            ("what", "who", "where", "when", "why", "how", "is ", "are ", "does ", "do ")
        ):
            answer = await self._complete_text(
                f"Answer the user's question about this image. Question: {query}",
                image_url=image_url,
            )
            return f"Answer about image:\n{answer}".strip()

        description = await self._complete_text(
            "Describe this image for the assistant. Focus on visible details that matter for the user's request.",
            image_url=image_url,
        )
        return f"Image summary:\n{description}".strip()

    async def _complete_text(
        self,
        prompt: str,
        *,
        image_b64: str = "",
        image_url: str = "",
        detail: str = "auto",
    ) -> str:
        url = image_url or self._to_data_url(image_b64)
        if not url:
            return ""

        messages = [
            {
                "role": "system",
                "content": "You are a vision perception module for NeuralClaw. Return concise, factual answers.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": url,
                            "detail": detail,
                        },
                    },
                ],
            },
        ]

        try:
            response = await self._provider.complete(messages=messages, tools=None, temperature=0.1)
        except Exception as exc:
            await self._publish_error("vision_complete", exc)
            return ""

        content = (response.content or "").strip()
        if self._bus:
            await self._bus.publish(
                EventType.CONTEXT_ENRICHED,
                {
                    "component": "vision",
                    "prompt": prompt[:120],
                    "preview": content[:200],
                },
                source="perception.vision",
            )
        return content

    def _resolve_image_url(self, media_item: dict[str, Any]) -> str:
        if not isinstance(media_item, dict):
            return ""

        for key in ("image_url", "url"):
            value = media_item.get(key)
            if isinstance(value, str) and value:
                return value

        for key in ("image_b64", "data", "base64", "content"):
            value = media_item.get(key)
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="ignore")
            if isinstance(value, str) and value:
                return self._to_data_url(
                    value,
                    media_item.get("mime_type") or media_item.get("content_type") or "",
                )

        return ""

    def _to_data_url(self, image_b64: str, mime_type: str = "") -> str:
        if not image_b64:
            return ""
        if image_b64.startswith("data:"):
            return image_b64
        mime = mime_type or "image/png"
        return f"data:{mime};base64,{image_b64}"

    async def _publish_error(self, operation: str, exc: Exception) -> None:
        if not self._bus:
            return
        await self._bus.publish(
            EventType.ERROR,
            {
                "component": "vision",
                "operation": operation,
                "error": str(exc),
            },
            source="perception.vision",
        )

    def _extract_json_object(self, text: str) -> dict[str, Any] | None:
        if not text:
            return None
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None
