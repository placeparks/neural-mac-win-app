"""
OpenAI Provider — OpenAI API + compatible endpoints (Groq, Together, etc.)
"""

from __future__ import annotations

import json
from typing import Any

import aiohttp

from neuralclaw.providers.router import LLMProvider, LLMResponse, ToolCall


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible API provider."""

    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5.4",
        base_url: str = "https://api.openai.com/v1",
        request_timeout_seconds: float = 120.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._request_timeout_seconds = request_timeout_seconds

    # Models that use the new API: max_completion_tokens, no custom temperature
    _NEW_API_PREFIX = ("gpt-5", "gpt-4.1", "o1", "o3", "o4")

    def _is_new_api_model(self) -> bool:
        """GPT-5+, GPT-4.1+, and all o-series use new API parameters."""
        model = self._model.lower()
        return any(model.startswith(p) for p in self._NEW_API_PREFIX)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
        }

        # GPT-5+, GPT-4.1+, o-series: max_completion_tokens, no temperature
        if self._is_new_api_model():
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["max_tokens"] = max_tokens
            payload["temperature"] = temperature

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self._request_timeout_seconds),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise RuntimeError(f"OpenAI API error ({resp.status}): {error_text[:300]}")

                data = await resp.json()

        choice = data["choices"][0]
        message = choice["message"]

        # Parse tool calls
        tool_calls: list[ToolCall] | None = None
        if message.get("tool_calls"):
            tool_calls = []
            for tc in message["tool_calls"]:
                args = tc["function"].get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                tool_calls.append(ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=args,
                ))

        return LLMResponse(
            content=message.get("content"),
            tool_calls=tool_calls,
            model=data.get("model", self._model),
            usage=data.get("usage", {}),
            raw=data,
        )

    async def is_available(self) -> bool:
        return bool(self._api_key)
