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
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from neuralclaw.config import ModelRolesConfig
from neuralclaw.providers.local import LocalProvider
from neuralclaw.providers.router import LLMProvider, LLMResponse

# Roles that are valid for chat completions (embed is handled separately)
CHAT_ROLES = ("primary", "fast", "micro")
ALL_ROLES = ("primary", "fast", "micro", "embed")


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

    @classmethod
    def from_config(
        cls,
        config: ModelRolesConfig,
        request_timeout_seconds: float = 120.0,
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

    async def complete(
        self,
        role: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Route a completion to the model assigned to *role*."""
        provider = self.get_provider(role)
        return await provider.complete(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def stream_complete(
        self,
        role: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream a completion from the model assigned to *role*."""
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
        """Return role → model name mapping for diagnostics."""
        return {role: p._model for role, p in self._providers.items()}

    @property
    def base_url(self) -> str:
        return self._config.base_url
