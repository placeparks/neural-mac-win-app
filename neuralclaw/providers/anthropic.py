"""
Anthropic Provider — Claude API integration via aiohttp.
"""

from __future__ import annotations

import json
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
                converted_messages.append({"role": role, "content": content})

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

    async def is_available(self) -> bool:
        return bool(self._api_key)
