"""
Proxy Provider — Route through any OpenAI-compatible reverse proxy.

Users self-host a reverse proxy (e.g. one-api, chatgpt-to-api, LobeChat)
and point NeuralClaw at it.  This replaces the need for g4f-style web
scraping with a clean, user-controlled proxy layer.

Supports:
- ChatGPT Plus session proxies
- Claude Pro session proxies
- Any OpenAI-compatible relay endpoint
"""

from __future__ import annotations

import aiohttp

from neuralclaw.providers.openai import OpenAIProvider


class ProxyProvider(OpenAIProvider):
    """OpenAI-compatible reverse proxy provider.

    Like LocalProvider, but for remote self-hosted proxies.
    API key is optional (depends on the proxy's auth requirements).
    """

    name = "proxy"

    def __init__(
        self,
        base_url: str,
        model: str = "gpt-4",
        api_key: str = "",
    ) -> None:
        super().__init__(
            api_key=api_key or "proxy",
            model=model,
            base_url=base_url,
        )

    async def is_available(self) -> bool:
        """Check if the proxy endpoint is reachable."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/models",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    # 401/403 means the proxy exists but needs auth — still "available"
                    return resp.status in (200, 401, 403)
        except Exception:
            return False
