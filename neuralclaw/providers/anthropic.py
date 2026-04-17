"""
Anthropic Provider — Claude API integration via aiohttp.
"""

from __future__ import annotations

import json
import re
from typing import Any

import aiohttp

from neuralclaw.providers.router import LLMProvider, LLMResponse, ToolCall


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-6",
        base_url: str = "https://api.anthropic.com",
        request_timeout_seconds: float = 120.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._request_timeout_seconds = request_timeout_seconds

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        system_content = ""
        converted_messages: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role")
            if role == "system":
                system_content = msg.get("content", "")
                continue
            if role == "tool":
                converted_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": msg.get("content", ""),
                    }],
                })
                continue
            if role == "assistant" and msg.get("tool_calls"):
                tool_blocks = []
                for tc in msg.get("tool_calls", []):
                    fn = tc.get("function", {})
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {"raw": args}
                    tool_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": args,
                    })
                converted_messages.append({"role": "assistant", "content": tool_blocks})
                continue

            content = msg.get("content", "")
            if isinstance(content, str):
                converted_messages.append({
                    "role": role,
                    "content": [{"type": "text", "text": content}],
                })
            else:
                converted_messages.append({
                    "role": role,
                    "content": self._convert_content_blocks(content),
                })

        # Convert OpenAI tool format to Anthropic format
        anthropic_tools = None
        if tools:
            anthropic_tools = []
            for t in tools:
                fn = t.get("function", t)
                anthropic_tools.append({
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {}),
                })

        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": converted_messages,
        }
        if system_content:
            payload["system"] = system_content
        if anthropic_tools:
            payload["tools"] = anthropic_tools

        headers = {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._base_url}/v1/messages",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self._request_timeout_seconds),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise RuntimeError(f"Anthropic API error ({resp.status}): {error_text[:300]}")

                data = await resp.json()

        # Parse response
        content_parts = data.get("content", [])
        text_content = ""
        tool_calls: list[ToolCall] | None = None

        for part in content_parts:
            if part["type"] == "text":
                text_content += part["text"]
            elif part["type"] == "tool_use":
                if tool_calls is None:
                    tool_calls = []
                tool_calls.append(ToolCall(
                    id=part["id"],
                    name=part["name"],
                    arguments=part.get("input", {}),
                ))

        return LLMResponse(
            content=text_content or None,
            tool_calls=tool_calls,
            model=data.get("model", self._model),
            usage=data.get("usage", {}),
            raw=data,
        )

    def _convert_content_blocks(self, content: Any) -> list[dict[str, Any]]:
        if not isinstance(content, list):
            text = str(content or "").strip()
            return [{"type": "text", "text": text}] if text else []

        converted: list[dict[str, Any]] = []
        for block in content:
            if isinstance(block, str):
                text = block.strip()
                if text:
                    converted.append({"type": "text", "text": text})
                continue
            if not isinstance(block, dict):
                continue

            block_type = str(block.get("type", "") or "").strip()
            if block_type in {"text", "input_text"}:
                text = str(block.get("text", "") or block.get("content", "") or "").strip()
                if text:
                    converted.append({"type": "text", "text": text})
                continue

            if block_type == "image_url":
                image_block = self._convert_image_block(block.get("image_url"))
                if image_block:
                    converted.append(image_block)
                continue

            if block_type == "image":
                source = block.get("source")
                if isinstance(source, dict):
                    converted.append({"type": "image", "source": source})

        return converted

    def _convert_image_block(self, image_url: Any) -> dict[str, Any] | None:
        if isinstance(image_url, str):
            url_value = image_url
            detail = ""
        elif isinstance(image_url, dict):
            url_value = str(image_url.get("url", "") or "").strip()
            detail = str(image_url.get("detail", "") or "").strip()
        else:
            return None

        if not url_value:
            return None

        source = self._image_source_from_url(url_value)
        if not source:
            return None

        image_block: dict[str, Any] = {"type": "image", "source": source}
        if detail:
            image_block["detail"] = detail
        return image_block

    def _image_source_from_url(self, url_value: str) -> dict[str, str] | None:
        if not url_value.startswith("data:"):
            return None

        match = re.match(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$", url_value, re.S)
        if not match:
            return None

        mime_type = match.group("mime").strip() or "image/png"
        data = match.group("data").strip()
        if not data:
            return None

        return {
            "type": "base64",
            "media_type": mime_type,
            "data": data,
        }

    async def list_models(self) -> list[dict[str, Any]]:
        """Return available Anthropic Claude models.

        The Anthropic API exposes GET /v1/models when available; fall back
        to a curated list of current production models.
        """
        # Try live endpoint first
        if self._api_key:
            try:
                headers = {
                    "x-api-key": self._api_key,
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01",
                }
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{self._base_url}/v1/models",
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            raw = data.get("data", [])
                            if raw:
                                return [
                                    {
                                        "id": m.get("id", ""),
                                        "name": m.get("display_name", m.get("id", "")),
                                        "owned_by": "anthropic",
                                        "object": "model",
                                        "created": m.get("created_at", 0),
                                    }
                                    for m in raw if m.get("id")
                                ]
            except Exception:
                pass

        # Fallback: curated list of current Claude models
        known_models = [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-20250514",
            "claude-3-5-haiku-20241022",
        ]
        return [
            {"id": m, "name": m, "owned_by": "anthropic", "object": "model"}
            for m in known_models
        ]

    async def is_available(self) -> bool:
        return bool(self._api_key)
