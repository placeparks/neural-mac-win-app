"""
Async provider circuit breaker with OPEN / HALF_OPEN / CLOSED states.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.errors import CircuitOpenError


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    success_threshold: int = 2
    timeout_seconds: float = 60.0
    slow_call_threshold_ms: float = 10_000.0


@dataclass
class CircuitBreaker:
    name: str
    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    bus: NeuralBus | None = field(default=None, repr=False)

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _last_failure: float = field(default=0.0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    @property
    def state(self) -> CircuitState:
        if (
            self._state == CircuitState.OPEN
            and self._last_failure
            and time.monotonic() - self._last_failure >= self.config.timeout_seconds
        ):
            self._state = CircuitState.HALF_OPEN
            self._success_count = 0
        return self._state

    async def call(self, coro: Awaitable[Any] | Callable[[], Awaitable[Any]]) -> Any:
        async with self._lock:
            state = self.state

        if state == CircuitState.OPEN:
            if not callable(coro) and hasattr(coro, "close"):
                coro.close()
            remaining = max(
                0.0,
                self.config.timeout_seconds - (time.monotonic() - self._last_failure),
            )
            raise CircuitOpenError(
                f"Circuit '{self.name}' is open. Retrying in {remaining:.1f}s."
            )

        start = time.monotonic()
        try:
            awaitable = coro() if callable(coro) else coro
            result = await awaitable
            elapsed_ms = (time.monotonic() - start) * 1000
            if elapsed_ms > self.config.slow_call_threshold_ms:
                await self._on_failure(f"slow call {elapsed_ms:.0f}ms")
            else:
                await self._on_success()
            return result
        except Exception as exc:
            await self._on_failure(str(exc))
            raise

    async def _on_success(self) -> None:
        event_name = ""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    event_name = "circuit_closed"
            else:
                self._failure_count = 0
        if event_name:
            await self._publish(event_name)

    async def _on_failure(self, reason: str) -> None:
        event_name = ""
        async with self._lock:
            self._failure_count += 1
            self._success_count = 0
            self._last_failure = time.monotonic()
            if self._failure_count >= self.config.failure_threshold and self._state != CircuitState.OPEN:
                self._state = CircuitState.OPEN
                event_name = "circuit_opened"
        if event_name:
            await self._publish(event_name, reason=reason)

    async def _publish(self, event: str, **extra: Any) -> None:
        if self.bus:
            await self.bus.publish(
                EventType.INFO,
                {
                    "circuit": self.name,
                    "state": self.state.value,
                    "event": event,
                    **extra,
                },
                source="circuit_breaker",
            )

    def reset(self) -> None:
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure = 0.0
