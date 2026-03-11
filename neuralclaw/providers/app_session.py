"""
Browser/app session providers for ChatGPT and Claude subscriptions.
"""

from __future__ import annotations

from typing import Any

from neuralclaw.providers.router import LLMProvider, LLMResponse
from neuralclaw.session.runtime import ManagedBrowserSession, SessionRuntimeConfig


class AppSessionProvider(LLMProvider):
    """Common provider adapter for browser-backed app sessions."""

    name = "app-session"
    supports_tools = False

    def __init__(
        self,
        *,
        provider_name: str,
        model: str,
        profile_dir: str,
        site_url: str,
        headless: bool = False,
        browser_channel: str = "",
    ) -> None:
        self.name = provider_name
        self._model = model or "auto"
        self._runtime = ManagedBrowserSession(
            SessionRuntimeConfig(
                provider=provider_name,
                profile_dir=profile_dir,
                site_url=site_url,
                model=model,
                headless=headless,
                browser_channel=browser_channel,
            )
        )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        prompt = _messages_to_prompt(messages)
        content = await self._runtime.complete(prompt)
        return LLMResponse(content=content, tool_calls=None, model=self._model, usage={})

    async def is_available(self) -> bool:
        health = await self._runtime.health()
        return health.ready and health.logged_in

    async def get_health(self) -> dict[str, Any]:
        health = await self._runtime.health()
        return {
            "provider": health.provider,
            "ready": health.ready,
            "logged_in": health.logged_in,
            "state": health.state,
            "message": health.message,
            "recommendation": health.recommendation,
            "last_completion_at": health.last_completion_at,
            "supports_tools": False,
        }

    async def login(self) -> None:
        await self._runtime.login()

    async def repair(self) -> None:
        await self._runtime.repair()


class ChatGPTAppProvider(AppSessionProvider):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(provider_name="chatgpt_app", **kwargs)


class ClaudeAppProvider(AppSessionProvider):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(provider_name="claude_app", **kwargs)


def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")
        if content is None:
            continue
        chunks.append(f"{role.upper()}: {content}")
    chunks.append("ASSISTANT:")
    return "\n\n".join(chunks)
