"""
Local Provider — Ollama / llama.cpp / vLLM via OpenAI-compatible API.

Connects to locally running models via the standard OpenAI-compatible
endpoint that Ollama and others expose.
"""

from __future__ import annotations

import aiohttp

from neuralclaw.providers.openai import OpenAIProvider


class LocalProvider(OpenAIProvider):
    """Local model provider via OpenAI-compatible API (Ollama, vLLM, etc.)."""

    name = "local"

    def __init__(
        self,
        model: str = "llama3",
        base_url: str = "http://localhost:11434/v1",
    ) -> None:
        # Local models don't need an API key, but the parent class expects one
        super().__init__(api_key="local", model=model, base_url=base_url)

    async def is_available(self) -> bool:
        """Check if local model server is running."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/models",
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False
