"""
Provider router with retries, fallback chains, and circuit breakers.
"""

from __future__ import annotations

import asyncio
import json
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.errors import CircuitOpenError, ProviderError
from neuralclaw.providers.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
)


@dataclass
class ToolCall:
    """A tool call from the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments),
            },
        }


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""

    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    name: str = "base"
    supports_tools: bool = True

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Send a completion request to the provider."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if the provider is configured and reachable."""
        ...

    async def list_models(self) -> list[dict[str, Any]]:
        """Return models available from this provider.

        Each entry: {"id": str, "name": str, "owned_by": str, ...}
        Default implementation returns an empty list; providers override
        with live API queries where supported.
        """
        return []

    async def stream_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Default buffered streaming fallback for providers without native streams."""
        response = await self.complete(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        for chunk in _chunk_text(response.content or ""):
            yield chunk


CircuitBreakerOpen = CircuitOpenError

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404}


def is_retryable_error(error: Exception) -> bool:
    """Check if an error is retryable (rate limit, server error, timeout)."""
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return True

    error_name = type(error).__name__
    if "Connection" in error_name or "Timeout" in error_name:
        return True

    status = getattr(error, "status", None) or getattr(error, "status_code", None)
    if isinstance(status, int):
        if status in _NON_RETRYABLE_STATUS_CODES:
            return False
        if status in _RETRYABLE_STATUS_CODES:
            return True

    msg = str(error).lower()
    retryable_phrases = [
        "rate limit",
        "too many requests",
        "server error",
        "timeout",
        "overloaded",
    ]
    return any(phrase in msg for phrase in retryable_phrases)


class ProviderRouter:
    """
    Smart model routing with fallback chain, circuit breaker, retry logic,
    and **offline mode** — automatically falls back to a local provider
    when the network is unreachable.
    """

    def __init__(
        self,
        primary: LLMProvider,
        fallbacks: list[LLMProvider] | None = None,
        max_retries: int = 2,
        circuit_breaker: CircuitBreaker | None = None,
        breaker_config: CircuitBreakerConfig | None = None,
        bus: NeuralBus | None = None,
        offline_fallback: bool = True,
    ) -> None:
        self._primary = primary
        self._fallbacks = fallbacks or []
        self._max_retries = max_retries
        self._bus = bus
        self._offline_fallback = offline_fallback
        self._offline_mode = False
        self._breaker_config = breaker_config or CircuitBreakerConfig()
        self._breakers: dict[str, CircuitBreaker] = {
            primary.name: circuit_breaker
            or CircuitBreaker(
                name=primary.name,
                config=self._breaker_config,
                bus=self._bus,
            ),
        }
        for fb in self._fallbacks:
            self._breakers[fb.name] = CircuitBreaker(
                name=fb.name,
                config=self._breaker_config,
                bus=self._bus,
            )

    def _get_breaker(self, provider: LLMProvider) -> CircuitBreaker:
        """Get or create a circuit breaker for a provider."""
        if provider.name not in self._breakers:
            self._breakers[provider.name] = CircuitBreaker(
                name=provider.name,
                config=self._breaker_config,
                bus=self._bus,
            )
        return self._breakers[provider.name]

    @property
    def name(self) -> str:
        return self._primary.name

    def get_circuit_states(self) -> dict[str, str]:
        """Get the circuit breaker state for each provider."""
        return {name: breaker.state.value for name, breaker in self._breakers.items()}

    def reset_circuit(self, provider_name: str) -> bool:
        """Manually reset a provider circuit breaker."""
        breaker = self._breakers.get(provider_name)
        if not breaker:
            return False
        breaker.reset()
        return True

    @property
    def is_offline(self) -> bool:
        """Check if the router is currently in offline mode."""
        return self._offline_mode

    async def _check_network(self) -> bool:
        """Quick connectivity check — try to reach a reliable endpoint."""
        import aiohttp
        for url in ("https://1.1.1.1", "https://8.8.8.8"):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.head(
                        url, timeout=aiohttp.ClientTimeout(total=3),
                        allow_redirects=False,
                    ) as resp:
                        return True
            except Exception:
                continue
        return False

    def _find_local_fallback(self) -> LLMProvider | None:
        """Find a local provider in the fallback chain."""
        for fb in self._fallbacks:
            if getattr(fb, "name", "") == "local":
                return fb
        return None

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Route completion request with circuit breaker, fallback, and offline mode."""
        last_error: Exception | None = None

        # If previously offline, proactively check network before attempting cloud
        if self._offline_mode:
            try:
                has_network = await self._check_network()
            except Exception:
                has_network = False
            if not has_network:
                # Skip cloud providers entirely, go straight to local fallback
                return await self._offline_complete(
                    messages=messages, tools=tools,
                    temperature=temperature, max_tokens=max_tokens,
                )

        for provider in [self._primary, *self._fallbacks]:
            try:
                result = await self._call_provider(
                    provider=provider,
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                # Recovered from offline
                if self._offline_mode:
                    self._offline_mode = False
                    await self._publish_info(
                        provider.name, "offline_recovered",
                        message="Network restored, back to normal routing.",
                    )
                return result
            except CircuitOpenError as exc:
                last_error = exc
                await self._publish_info(
                    provider.name,
                    "provider_skipped",
                    reason=str(exc),
                )
                continue
            except Exception as exc:
                last_error = exc
                continue

        # All providers failed — try offline fallback to local model
        if self._offline_fallback:
            return await self._offline_complete(
                messages=messages, tools=tools,
                temperature=temperature, max_tokens=max_tokens,
            )

        raise ProviderError(
            f"All providers failed. Primary: {self._primary.name}. "
            f"Circuit states: {self.get_circuit_states()}. "
            f"Last error: {last_error}"
        )

    async def _offline_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Attempt completing via a local provider when cloud is unreachable."""
        local = self._find_local_fallback()
        tried_in_main_chain = local is not None and local in [self._primary, *self._fallbacks]

        if not tried_in_main_chain and local is None:
            # Try to create an ad-hoc local provider
            try:
                from neuralclaw.providers.local import LocalProvider
                local = LocalProvider()
            except Exception:
                local = None

        if local and await local.is_available():
            self._offline_mode = True
            await self._publish_info(
                "local", "offline_mode_activated",
                message="All cloud providers failed. Falling back to local model.",
            )
            return await local.complete(
                messages=messages, tools=tools,
                temperature=temperature, max_tokens=max_tokens,
            )

        raise ProviderError(
            f"All providers failed and no local fallback available. "
            f"Circuit states: {self.get_circuit_states()}"
        )

    async def _call_provider(
        self,
        provider: LLMProvider,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        breaker = self._get_breaker(provider)
        if tools and not getattr(provider, "supports_tools", True):
            raise ProviderError(f"Provider '{provider.name}' does not support tool calls.")

        if provider is not self._primary and not await provider.is_available():
            raise ProviderError(f"Fallback provider '{provider.name}' is unavailable.")

        import functools
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                # Use functools.partial to capture values (not references)
                call_fn = functools.partial(
                    provider.complete,
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return await breaker.call(call_fn)
            except CircuitOpenError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < self._max_retries and is_retryable_error(exc):
                    delay = (2**attempt) + random.random()
                    await self._publish_info(
                        provider.name,
                        "provider_retry",
                        attempt=attempt + 1,
                        delay_seconds=round(delay, 3),
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        assert last_error is not None
        raise last_error

    async def stream_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Route a streaming completion with buffered fallback behavior."""
        response = await self.complete(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        for chunk in _chunk_text(response.content or ""):
            yield chunk

    async def list_models(self) -> list[dict[str, Any]]:
        """List models from the primary provider."""
        return await self._primary.list_models()

    async def is_available(self) -> bool:
        """Check if any provider is available."""
        if await self._primary.is_available():
            return True
        return any(await provider.is_available() for provider in self._fallbacks)

    async def ping_primary(self) -> bool:
        """Cheap readiness check for the primary provider."""
        try:
            if self._get_breaker(self._primary).state.value == "open":
                return False
            return bool(await self._primary.is_available())
        except Exception:
            return False

    async def _publish_info(self, provider: str, event: str, **extra: Any) -> None:
        if self._bus:
            await self._bus.publish(
                EventType.INFO,
                {"provider": provider, "event": event, **extra},
                source="provider_router",
            )


def _chunk_text(text: str, chunk_size: int = 24) -> list[str]:
    """Split text into UI-friendly chunks for buffered streaming fallbacks."""
    if not text:
        return []
    parts: list[str] = []
    cursor = 0
    while cursor < len(text):
        end = min(len(text), cursor + chunk_size)
        if end < len(text):
            split = text.rfind(" ", cursor, end)
            if split > cursor:
                end = split + 1
        parts.append(text[cursor:end])
        cursor = end
    return parts
