"""
OpenRouter Provider — Multi-model API via OpenRouter.

Uses the OpenAI-compatible API format with OpenRouter's base URL.
"""

from __future__ import annotations

from neuralclaw.providers.openai import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter multi-model provider (OpenAI-compatible API)."""

    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model: str = "anthropic/claude-sonnet-4-6",
        base_url: str = "https://openrouter.ai/api/v1",
    ) -> None:
        super().__init__(api_key=api_key, model=model, base_url=base_url)
