"""
ChatGPT token-based provider — uses OAuth or cookie tokens for API access.
"""

from __future__ import annotations

import json
from typing import Any

import aiohttp

from neuralclaw.providers.router import LLMProvider, LLMResponse, ToolCall
from neuralclaw.session.auth import AuthManager, redact_token

_CHATGPT_API_URL = "https://chatgpt.com/backend-api/conversation"


class ChatGPTTokenProvider(LLMProvider):
    """ChatGPT provider using token-based auth (OAuth or session cookie)."""

    name = "chatgpt_token"
    supports_tools = True

    def __init__(self, *, model: str = "auto") -> None:
        self._model = model or "auto"
        self._auth = AuthManager("chatgpt")

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        cred = await self._auth.get_valid_credential()
        if cred is None:
            raise RuntimeError(
                "No valid ChatGPT token. Run: neuralclaw session auth chatgpt"
            )

        payload = self._build_payload(messages, tools, temperature, max_tokens)
        headers = self._build_headers(cred.access_token, cred.token_type)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                _CHATGPT_API_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status == 401:
                    raise RuntimeError(
                        "ChatGPT token rejected (401). Run: neuralclaw session auth chatgpt"
                    )
                if resp.status == 403:
                    raise RuntimeError(
                        "ChatGPT access forbidden (403). The token may have expired or "
                        "Cloudflare is blocking the request."
                    )
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(
                        f"ChatGPT API error ({resp.status}): {body[:500]}"
                    )

                return await self._parse_response(resp)

    async def is_available(self) -> bool:
        cred = await self._auth.get_valid_credential()
        return cred is not None

    async def get_health(self) -> dict[str, Any]:
        health = self._auth.health_check()
        health["supports_tools"] = True
        return health

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Build ChatGPT backend-api conversation payload."""
        # Convert standard messages to ChatGPT format
        chatgpt_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if content:
                chatgpt_messages.append({
                    "id": f"msg-{len(chatgpt_messages)}",
                    "author": {"role": role},
                    "content": {"content_type": "text", "parts": [content]},
                })

        payload: dict[str, Any] = {
            "action": "next",
            "messages": chatgpt_messages,
            "model": self._model if self._model != "auto" else "auto",
            "temperature": temperature,
        }

        if tools:
            payload["tools"] = tools

        return payload

    def _build_headers(self, token: str, token_type: str) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        }
        if token_type == "oauth":
            headers["Authorization"] = f"Bearer {token}"
        else:
            # Cookie-based auth
            headers["Cookie"] = f"__Secure-next-auth.session-token={token}"
        return headers

    async def _parse_response(self, resp: aiohttp.ClientResponse) -> LLMResponse:
        """Parse ChatGPT streaming response (SSE)."""
        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        model = self._model
        last_message: dict[str, Any] = {}

        async for line in resp.content:
            text = line.decode("utf-8", errors="replace").strip()
            if not text.startswith("data: "):
                continue
            data_str = text[6:]
            if data_str == "[DONE]":
                break

            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            message = data.get("message")
            if not message:
                continue

            last_message = message
            author_role = message.get("author", {}).get("role", "")
            if author_role != "assistant":
                continue

            msg_content = message.get("content", {})
            if msg_content.get("content_type") == "text":
                parts = msg_content.get("parts", [])
                if parts:
                    content_parts = [str(p) for p in parts if p]

            # Check for tool calls in the message
            if msg_content.get("content_type") == "tether_browsing_display":
                continue
            metadata = message.get("metadata", {})
            if metadata.get("model_slug"):
                model = metadata["model_slug"]

        final_content = "\n".join(content_parts) if content_parts else None
        return LLMResponse(
            content=final_content,
            tool_calls=tool_calls if tool_calls else None,
            model=model,
            usage={},
        )
