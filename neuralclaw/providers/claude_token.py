"""
Claude token-based provider — uses session key for API access.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import aiohttp

from neuralclaw.providers.router import LLMProvider, LLMResponse
from neuralclaw.session.auth import AuthManager

_CLAUDE_API_BASE = "https://claude.ai/api"


class ClaudeTokenProvider(LLMProvider):
    """Claude provider using session key from browser cookies."""

    name = "claude_token"
    supports_tools = False

    def __init__(self, *, model: str = "auto") -> None:
        self._model = model or "auto"
        self._auth = AuthManager("claude")
        self._org_id: str | None = None

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
                "No valid Claude session key. Run: neuralclaw session auth claude"
            )

        headers = self._build_headers(cred.access_token)

        # Ensure we have the org ID
        if not self._org_id:
            self._org_id = await self._fetch_org_id(headers)

        # Create a new conversation
        conv_id = await self._create_conversation(headers)

        # Send the prompt
        prompt = _messages_to_prompt(messages)
        content = await self._send_message(headers, conv_id, prompt)

        return LLMResponse(
            content=content,
            tool_calls=None,
            model=self._model,
            usage={},
        )

    async def is_available(self) -> bool:
        cred = await self._auth.get_valid_credential()
        return cred is not None

    async def get_health(self) -> dict[str, Any]:
        health = self._auth.health_check()
        health["supports_tools"] = False
        return health

    def _build_headers(self, session_key: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Cookie": f"sessionKey={session_key}",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        }

    async def _fetch_org_id(self, headers: dict[str, str]) -> str:
        """Fetch the user's organization ID from Claude API."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{_CLAUDE_API_BASE}/organizations",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 401:
                    raise RuntimeError(
                        "Claude session key rejected. Run: neuralclaw session auth claude"
                    )
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"Failed to fetch Claude orgs ({resp.status}): {body[:500]}")
                data = await resp.json()

        if not data:
            raise RuntimeError("No organizations found for Claude account")
        return data[0]["uuid"]

    async def _create_conversation(self, headers: dict[str, str]) -> str:
        """Create a new conversation and return its UUID."""
        payload = {
            "uuid": str(uuid.uuid4()),
            "name": "",
            "model": self._model if self._model != "auto" else None,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{_CLAUDE_API_BASE}/organizations/{self._org_id}/chat_conversations",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    raise RuntimeError(
                        f"Failed to create Claude conversation ({resp.status}): {body[:500]}"
                    )
                data = await resp.json()

        return data["uuid"]

    async def _send_message(
        self, headers: dict[str, str], conv_id: str, prompt: str
    ) -> str:
        """Send a message to a Claude conversation and collect the response."""
        payload = {
            "completion": {
                "prompt": prompt,
                "timezone": "UTC",
                "model": self._model if self._model != "auto" else None,
            },
            "organization_uuid": self._org_id,
            "conversation_uuid": conv_id,
            "text": prompt,
            "attachments": [],
        }

        content_parts: list[str] = []

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{_CLAUDE_API_BASE}/organizations/{self._org_id}/chat_conversations/"
                f"{conv_id}/completion",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status == 401:
                    raise RuntimeError(
                        "Claude session key expired. Run: neuralclaw session auth claude"
                    )
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(
                        f"Claude completion failed ({resp.status}): {body[:500]}"
                    )

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

                    completion = data.get("completion", "")
                    if completion:
                        content_parts.append(completion)

        return "".join(content_parts) if content_parts else ""


def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    """Convert standard messages to a single prompt string."""
    chunks: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")
        if content is None:
            continue
        if role == "system":
            chunks.append(content)
        else:
            chunks.append(f"\n\n{role.title()}: {content}")
    return "".join(chunks).strip()
