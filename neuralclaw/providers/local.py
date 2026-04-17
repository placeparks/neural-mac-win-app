"""
Local Provider — Ollama / llama.cpp / vLLM via OpenAI-compatible API.

Connects to locally running models via the standard OpenAI-compatible
endpoint that Ollama and others expose.  Dynamically discovers whatever
models the user is currently serving.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

from neuralclaw.providers.openai import OpenAIProvider

logger = logging.getLogger("neuralclaw.providers.local")


class LocalProvider(OpenAIProvider):
    """Local model provider via OpenAI-compatible API (Ollama, vLLM, etc.).

    Key improvements over a plain OpenAI wrapper:
    - ``list_models()`` dynamically queries the endpoint for served models
    - ``auto_select_model()`` picks the best available model if the
      configured one is not currently loaded
    - Model cache with TTL avoids hammering the endpoint on every call
    """

    name = "local"

    # Cache TTL for model list (seconds)
    _MODEL_CACHE_TTL = 30.0

    def __init__(
        self,
        model: str = "qwen3.5:2b",
        base_url: str = "http://localhost:11434/v1",
        request_timeout_seconds: float = 120.0,
    ) -> None:
        # Local models don't need an API key, but the parent class expects one
        super().__init__(
            api_key="local",
            model=model,
            base_url=base_url,
            request_timeout_seconds=request_timeout_seconds,
        )
        self._cached_models: list[dict[str, Any]] = []
        self._cache_ts: float = 0.0
        self._model_validated: bool = False

    # ------------------------------------------------------------------
    # Dynamic model discovery
    # ------------------------------------------------------------------

    async def list_models(self) -> list[dict[str, Any]]:
        """Query the local endpoint for all served models.

        Returns a list of dicts with at minimum ``{"id": "model_name"}``.
        Works with Ollama, vLLM, llama.cpp, LocalAI, LM Studio, and any
        server exposing ``GET /models`` (OpenAI-compatible) or
        ``GET /api/tags`` (Ollama-native).
        """
        now = time.monotonic()
        if self._cached_models and (now - self._cache_ts) < self._MODEL_CACHE_TTL:
            return self._cached_models

        models: list[dict[str, Any]] = []

        # Strategy 1: OpenAI-compatible /models endpoint
        try:
            models = await self._fetch_openai_models()
        except Exception:
            pass

        # Strategy 2: Ollama-native /api/tags (richer metadata)
        if not models:
            try:
                models = await self._fetch_ollama_tags()
            except Exception:
                pass

        if models:
            self._cached_models = models
            self._cache_ts = now
            logger.debug(
                "Discovered %d models at %s: %s",
                len(models), self._base_url,
                [m["id"] for m in models[:10]],
            )
        return models

    async def _fetch_openai_models(self) -> list[dict[str, Any]]:
        """GET /models — standard OpenAI-compatible endpoint."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self._base_url}/models",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

        raw = data.get("data") or data.get("models") or []
        if isinstance(raw, list):
            models = []
            for entry in raw:
                if isinstance(entry, dict):
                    model_id = entry.get("id") or entry.get("name") or ""
                    if not model_id:
                        continue
                    models.append({
                        "id": model_id,
                        "name": entry.get("name", model_id),
                        "owned_by": entry.get("owned_by", "local"),
                        "object": entry.get("object", "model"),
                        "created": entry.get("created", 0),
                        "size": entry.get("size", 0),
                        "family": entry.get("details", {}).get("family", ""),
                        "parameter_size": entry.get("details", {}).get("parameter_size", ""),
                        "quantization": entry.get("details", {}).get("quantization_level", ""),
                    })
            return models
        return []

    async def _fetch_ollama_tags(self) -> list[dict[str, Any]]:
        """GET /api/tags — Ollama-native endpoint with richer metadata."""
        # Derive Ollama base from the /v1 endpoint
        ollama_base = self._base_url
        if ollama_base.endswith("/v1"):
            ollama_base = ollama_base[:-3]

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{ollama_base}/api/tags",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

        raw = data.get("models", [])
        models = []
        for entry in raw:
            name = entry.get("name", "")
            if not name:
                continue
            details = entry.get("details", {})
            models.append({
                "id": name,
                "name": name,
                "owned_by": "local",
                "object": "model",
                "created": 0,
                "size": entry.get("size", 0),
                "family": details.get("family", ""),
                "parameter_size": details.get("parameter_size", ""),
                "quantization": details.get("quantization_level", ""),
                "format": details.get("format", ""),
                "modified_at": entry.get("modified_at", ""),
                "digest": entry.get("digest", ""),
            })
        return models

    # ------------------------------------------------------------------
    # Auto-model selection
    # ------------------------------------------------------------------

    async def auto_select_model(self) -> str | None:
        """If the configured model is not available, pick the best one.

        Returns the selected model name, or None if no models are served.
        Prefers: configured model > largest model > first available.
        """
        models = await self.list_models()
        if not models:
            return None

        model_ids = [m["id"] for m in models]

        # 1. Configured model is available — use it
        if self._model in model_ids:
            return self._model

        # 2. Check if configured model matches without tag (e.g. "qwen3:8b" matches "qwen3:8b")
        base_name = self._model.split(":")[0].lower()
        for mid in model_ids:
            if mid.lower().startswith(base_name):
                logger.info(
                    "Configured model '%s' not found, using similar: '%s'",
                    self._model, mid,
                )
                self._model = mid
                return mid

        # 3. Pick the largest model by parameter size or file size
        def _sort_key(m: dict) -> int:
            ps = str(m.get("parameter_size", "0"))
            # Extract numeric part: "8B" -> 8, "70B" -> 70
            num = ""
            for ch in ps:
                if ch.isdigit() or ch == ".":
                    num += ch
            try:
                return int(float(num) * 1000) if num else m.get("size", 0)
            except ValueError:
                return m.get("size", 0)

        models_sorted = sorted(models, key=_sort_key, reverse=True)
        best = models_sorted[0]["id"]
        logger.info(
            "Configured model '%s' not found. Auto-selected: '%s' "
            "(from %d available models)",
            self._model, best, len(models),
        )
        self._model = best
        return best

    # ------------------------------------------------------------------
    # Health info
    # ------------------------------------------------------------------

    async def get_health(self) -> dict[str, Any]:
        """Return detailed health info about the local endpoint."""
        available = await self.is_available()
        models = await self.list_models() if available else []
        configured_available = any(m["id"] == self._model for m in models)

        return {
            "available": available,
            "endpoint": self._base_url,
            "configured_model": self._model,
            "configured_model_available": configured_available,
            "model_count": len(models),
            "models": [
                {
                    "id": m["id"],
                    "size": m.get("size", 0),
                    "family": m.get("family", ""),
                    "parameter_size": m.get("parameter_size", ""),
                    "quantization": m.get("quantization", ""),
                }
                for m in models
            ],
        }

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

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Any:
        """Complete with auto-model validation on first call."""
        if not self._model_validated:
            self._model_validated = True
            selected = await self.auto_select_model()
            if selected:
                logger.info("Local provider using model: %s", selected)

        return await super().complete(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
