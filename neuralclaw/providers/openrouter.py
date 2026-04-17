"""
OpenRouter Provider — Multi-model API via OpenRouter.

Uses the OpenAI-compatible API format with OpenRouter's base URL.
"""

from __future__ import annotations

from typing import Any

from neuralclaw.providers.openai import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter multi-model provider (OpenAI-compatible API)."""

    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model: str = "anthropic/claude-sonnet-4-6",
        base_url: str = "https://openrouter.ai/api/v1",
        request_timeout_seconds: float = 120.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            request_timeout_seconds=request_timeout_seconds,
        )

    async def list_models(self) -> list[dict[str, Any]]:
        """Fetch available models from OpenRouter's /models endpoint."""
        try:
            import aiohttp
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/models",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
            raw = data.get("data", [])
            return [
                {
                    "id": m.get("id", ""),
                    "name": m.get("name", m.get("id", "")),
                    "owned_by": m.get("id", "").split("/")[0] if "/" in m.get("id", "") else "",
                    "object": "model",
                    "context_length": m.get("context_length", 0),
                    "pricing": m.get("pricing", {}),
                }
                for m in raw if m.get("id")
            ]
        except Exception:
            return []
