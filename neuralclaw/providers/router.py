"""
Provider Router — Smart model routing with fallback chains.

Defines the LLMProvider ABC and routes requests to the configured
primary provider with automatic fallback on failure.

Reliability features:
- Circuit breaker (in-memory, opens after N failures in M seconds)
- Exponential backoff with jitter
- Retryable vs non-retryable error classification
- Automatic fallback chain
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# LLM response models
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Abstract base provider
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Circuit Breaker (in-memory)
# ---------------------------------------------------------------------------

class CircuitBreakerOpen(Exception):
    """Raised when the circuit breaker is open."""
    def __init__(self, provider_name: str, cooldown_remaining: float) -> None:
        self.provider_name = provider_name
        self.cooldown_remaining = cooldown_remaining
        super().__init__(
            f"Circuit breaker OPEN for {provider_name}. "
            f"Retry in {cooldown_remaining:.1f}s"
        )


@dataclass
class CircuitBreaker:
    """
    In-memory circuit breaker for provider calls.

    States:
    - CLOSED: Normal operation, failures are counted.
    - OPEN: After threshold failures, all calls fail fast.
    - HALF_OPEN: After cooldown, one test call is allowed through.
    """
    failure_threshold: int = 5
    failure_window_seconds: float = 60.0
    cooldown_seconds: float = 30.0

    def __post_init__(self) -> None:
        self._failures: list[float] = []
        self._opened_at: float | None = None
        self._half_open: bool = False
        self._state: str = "closed"

    @property
    def state(self) -> str:
        self._update_state()
        return self._state

    @property
    def is_open(self) -> bool:
        return self.state == "open"

    def _update_state(self) -> None:
        """Recompute state based on current time."""
        now = time.time()

        if self._state == "open" and self._opened_at:
            if now - self._opened_at >= self.cooldown_seconds:
                self._state = "half_open"
                self._half_open = True

    def record_success(self) -> None:
        """Record a successful call — resets the breaker."""
        self._failures.clear()
        self._opened_at = None
        self._half_open = False
        self._state = "closed"

    def record_failure(self) -> None:
        """Record a failed call — may trip the breaker."""
        now = time.time()
        self._failures.append(now)

        # Prune failures outside the window
        cutoff = now - self.failure_window_seconds
        self._failures = [t for t in self._failures if t > cutoff]

        if len(self._failures) >= self.failure_threshold:
            self._state = "open"
            self._opened_at = now
            self._half_open = False

    def check(self, provider_name: str = "unknown") -> None:
        """
        Check if the circuit breaker allows a call.

        Raises CircuitBreakerOpen if the breaker is open.
        """
        self._update_state()

        if self._state == "open":
            remaining = 0.0
            if self._opened_at:
                remaining = max(0.0, self.cooldown_seconds - (time.time() - self._opened_at))
            raise CircuitBreakerOpen(provider_name, remaining)

        # Half-open: allow one test call (marking it as no longer half-open)
        if self._state == "half_open":
            self._half_open = False


# ---------------------------------------------------------------------------
# Retryable error classification
# ---------------------------------------------------------------------------

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404}


def is_retryable_error(error: Exception) -> bool:
    """Check if an error is retryable (rate limit, server error, timeout)."""
    # Timeout errors
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return True

    # Connection errors
    error_name = type(error).__name__
    if "Connection" in error_name or "Timeout" in error_name:
        return True

    # Check for HTTP status code in error message or attributes
    status = getattr(error, "status", None) or getattr(error, "status_code", None)
    if isinstance(status, int):
        if status in _NON_RETRYABLE_STATUS_CODES:
            return False
        if status in _RETRYABLE_STATUS_CODES:
            return True

    # Check error message for common retryable indicators
    msg = str(error).lower()
    retryable_phrases = ["rate limit", "too many requests", "server error", "timeout", "overloaded"]
    return any(phrase in msg for phrase in retryable_phrases)


# ---------------------------------------------------------------------------
# Provider Router
# ---------------------------------------------------------------------------

class ProviderRouter:
    """
    Smart model routing with fallback chain, circuit breaker, and retry logic.

    Tries the primary provider first. On failure, tries each fallback
    in order. Implements exponential backoff with jitter and circuit
    breaker protection.
    """

    def __init__(
        self,
        primary: LLMProvider,
        fallbacks: list[LLMProvider] | None = None,
        max_retries: int = 2,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._primary = primary
        self._fallbacks = fallbacks or []
        self._max_retries = max_retries
        # Each provider gets its own circuit breaker
        self._breakers: dict[str, CircuitBreaker] = {
            primary.name: circuit_breaker or CircuitBreaker(),
        }
        for fb in self._fallbacks:
            self._breakers[fb.name] = CircuitBreaker()

    def _get_breaker(self, provider: LLMProvider) -> CircuitBreaker:
        """Get or create a circuit breaker for a provider."""
        if provider.name not in self._breakers:
            self._breakers[provider.name] = CircuitBreaker()
        return self._breakers[provider.name]

    @property
    def name(self) -> str:
        return self._primary.name

    def get_circuit_states(self) -> dict[str, str]:
        """Get the circuit breaker state for each provider."""
        return {name: cb.state for name, cb in self._breakers.items()}

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Route completion request with circuit breaker and fallback logic."""

        last_error: Exception | None = None

        # Try primary with retries
        breaker = self._get_breaker(self._primary)
        try:
            if tools and not getattr(self._primary, "supports_tools", True):
                raise RuntimeError(f"Provider {self._primary.name} does not support tool calls")
            breaker.check(self._primary.name)

            for attempt in range(self._max_retries + 1):
                try:
                    response = await self._primary.complete(
                        messages=messages,
                        tools=tools,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    breaker.record_success()
                    return response
                except Exception as e:
                    last_error = e
                    if attempt < self._max_retries and is_retryable_error(e):
                        # Exponential backoff with jitter: 2^attempt + random(0, 1)
                        delay = (2 ** attempt) + random.random()
                        await asyncio.sleep(delay)
                        continue
                    breaker.record_failure()
                    break

        except CircuitBreakerOpen:
            last_error = CircuitBreakerOpen(self._primary.name, 0)

        # Try fallbacks
        for provider in self._fallbacks:
            fb_breaker = self._get_breaker(provider)
            try:
                if tools and not getattr(provider, "supports_tools", True):
                    continue
                fb_breaker.check(provider.name)
                if await provider.is_available():
                    response = await provider.complete(
                        messages=messages,
                        tools=tools,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    fb_breaker.record_success()
                    return response
            except CircuitBreakerOpen:
                continue
            except Exception:
                fb_breaker.record_failure()
                continue

        raise RuntimeError(
            f"All providers failed. Primary: {self._primary.name}. "
            f"Circuit states: {self.get_circuit_states()}. "
            f"Last error: {last_error}"
        )

    async def is_available(self) -> bool:
        """Check if any provider is available."""
        if await self._primary.is_available():
            return True
        return any(
            await p.is_available() for p in self._fallbacks
        )
