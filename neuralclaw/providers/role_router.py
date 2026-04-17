"""
Role-based Model Router — deterministic model selection by call-site role.

Instead of routing by provider fallback, this router selects models by *role*:

    primary — deep reasoning, vision, complex agent tasks, user-facing responses
    fast    — tool call execution, skill dispatch, multi-step agent loops
    micro   — intent classification, routing, quick yes/no classifications
    embed   — embeddings (Nexus Memory, RAG, semantic search)

Each role maps to a specific model on the same Ollama (or OpenAI-compatible)
endpoint.  The router holds one LocalProvider per role and exposes a
``complete(role, ...)`` interface so call sites declare *what they need*, not
*which model* — the config decides the binding.

Dynamic model validation:
    On first use, the router queries the local endpoint for available models.
    If a configured role model is not served, the router auto-reassigns it to
    the closest available model — ensuring the system always works regardless
    of which models the user has pulled.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from neuralclaw.config import ModelRolesConfig
from neuralclaw.providers.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from neuralclaw.providers.local import LocalProvider
from neuralclaw.providers.router import LLMProvider, LLMResponse

logger = logging.getLogger("neuralclaw.providers.role_router")

# Roles that are valid for chat completions (embed is handled separately)
CHAT_ROLES = ("primary", "fast", "micro")
ALL_ROLES = ("primary", "fast", "micro", "embed")

# Rough size tiers for auto-assignment (descending preference per role)
_ROLE_SIZE_PREFERENCE: dict[str, str] = {
    "primary": "large",   # prefer the biggest model
    "fast": "medium",
    "micro": "small",     # prefer the smallest model
    "embed": "embed",
}


class RoleRouter:
    """Holds a LocalProvider per role and routes by call-site declaration.

    Usage::

        router = RoleRouter.from_config(model_roles_config)
        response = await router.complete("fast", messages, tools=tools)
        response = await router.complete("primary", messages)
    """

    def __init__(
        self,
        providers: dict[str, LocalProvider],
        config: ModelRolesConfig,
    ) -> None:
        self._providers = providers
        self._config = config
        self._validated = False

    @classmethod
    def from_config(
        cls,
        config: ModelRolesConfig,
        request_timeout_seconds: float = 600.0,
    ) -> "RoleRouter":
        """Build role-keyed LocalProvider instances from ModelRolesConfig."""
        providers: dict[str, LocalProvider] = {}
        for role in ALL_ROLES:
            model = config.get_model(role)
            providers[role] = LocalProvider(
                model=model,
                base_url=config.base_url,
                request_timeout_seconds=request_timeout_seconds,
            )
        return cls(providers=providers, config=config)

    def get_provider(self, role: str) -> LocalProvider:
        """Get the LocalProvider for a specific role."""
        if role not in self._providers:
            return self._providers["primary"]
        return self._providers[role]

    # ------------------------------------------------------------------
    # Dynamic model validation
    # ------------------------------------------------------------------

    async def validate_models(self) -> dict[str, str]:
        """Check that every role's model is actually served.

        If a model is missing, reassign the role to the best available
        model.  Returns a mapping of {role: model} after validation.
        """
        if self._validated:
            return self.model_map

        primary_provider = self._providers.get("primary")
        if not primary_provider:
            return self.model_map

        available = await primary_provider.list_models()
        if not available:
            logger.warning("No models discovered at %s — skipping validation", self.base_url)
            self._validated = True
            return self.model_map

        available_ids = {m["id"] for m in available}
        available_list = list(available)

        # Sort models by size for tiered assignment
        def _size_key(m: dict) -> float:
            ps = str(m.get("parameter_size", "0"))
            num = ""
            for ch in ps:
                if ch.isdigit() or ch == ".":
                    num += ch
            try:
                return float(num) if num else m.get("size", 0) / 1e9
            except ValueError:
                return 0.0

        available_sorted = sorted(available_list, key=_size_key, reverse=True)

        reassignments: dict[str, tuple[str, str]] = {}

        # Pre-compute embed candidate: models whose name contains "embed" or "nomic"
        embed_candidates = [
            m for m in available_sorted
            if "embed" in m["id"].lower() or "nomic" in m["id"].lower()
        ]

        for role in ALL_ROLES:
            provider = self._providers.get(role)
            if not provider:
                continue
            current_model = provider._model

            # --- Embed role: always pick a dedicated embed model ---
            if role == "embed":
                if embed_candidates:
                    new_model = embed_candidates[0]["id"]
                    if new_model != current_model:
                        provider._model = new_model
                        reassignments[role] = (current_model or "<auto>", new_model)
                elif available_sorted:
                    # No dedicated embed model; use the smallest available model
                    # as a stopgap so embeddings are not silently lost.
                    new_model = available_sorted[-1]["id"]
                    if new_model != current_model:
                        provider._model = new_model
                        reassignments[role] = (current_model or "<auto>", new_model)
                continue

            if current_model and current_model in available_ids:
                continue  # Configured model is available — nothing to do

            # Check partial name match (e.g. "qwen3:8b" prefix)
            if current_model:
                base_name = current_model.split(":")[0].lower()
                partial = [m for m in available_list if m["id"].lower().startswith(base_name)]
                if partial:
                    new_model = partial[0]["id"]
                    provider._model = new_model
                    reassignments[role] = (current_model, new_model)
                    continue

            # Auto-assign by size tier
            preference = _ROLE_SIZE_PREFERENCE.get(role, "medium")
            # Exclude embed-only models from chat role assignment
            chat_models = [
                m for m in available_sorted
                if "embed" not in m["id"].lower() and "nomic" not in m["id"].lower()
            ] or available_sorted  # fallback to all if only embed models exist
            if preference == "large" and chat_models:
                new_model = chat_models[0]["id"]
            elif preference == "small" and chat_models:
                new_model = chat_models[-1]["id"]
            elif chat_models:
                mid = len(chat_models) // 2
                new_model = chat_models[mid]["id"]
            else:
                continue

            provider._model = new_model
            reassignments[role] = (current_model or "<auto>", new_model)

        if reassignments:
            for role, (old, new) in reassignments.items():
                logger.info(
                    "Role '%s': configured model '%s' not found, reassigned to '%s'",
                    role, old, new,
                )

        self._validated = True
        logger.info("Role router validated. Model map: %s", self.model_map)
        return self.model_map

    async def list_available_models(self) -> list[dict[str, Any]]:
        """Return all models available at the local endpoint."""
        primary = self._providers.get("primary")
        if not primary:
            return []
        return await primary.list_models()

    # ------------------------------------------------------------------
    # Completion routing
    # ------------------------------------------------------------------

    async def complete(
        self,
        role: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Route a completion to the model assigned to *role*."""
        if not self._validated:
            await self.validate_models()

        provider = self.get_provider(role)
        breaker = self._get_breaker(role)
        import functools
        call_fn = functools.partial(
            provider.complete,
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return await breaker.call(call_fn)

    async def stream_complete(
        self,
        role: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream a completion from the model assigned to *role*."""
        if not self._validated:
            await self.validate_models()

        provider = self.get_provider(role)
        async for chunk in provider.stream_complete(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            yield chunk

    async def is_available(self) -> bool:
        """Check if the primary role's model server is reachable."""
        return await self._providers["primary"].is_available()

    @property
    def model_map(self) -> dict[str, str]:
        """Return role -> model name mapping for diagnostics."""
        return {role: p._model for role, p in self._providers.items()}

    @property
    def embed_model(self) -> str:
        """Return the currently resolved embedding model name."""
        provider = self._providers.get("embed")
        return provider._model if provider else ""

    @property
    def base_url(self) -> str:
        return self._config.base_url

    def _get_breaker(self, role: str) -> CircuitBreaker:
        """Get or create a per-role circuit breaker."""
        if not hasattr(self, "_breakers"):
            self._breakers: dict[str, CircuitBreaker] = {}
        if role not in self._breakers:
            self._breakers[role] = CircuitBreaker(
                name=f"role_router.{role}",
                config=CircuitBreakerConfig(
                    failure_threshold=3,
                    success_threshold=1,
                    timeout_seconds=30.0,
                ),
            )
        return self._breakers[role]
