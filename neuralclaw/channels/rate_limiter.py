"""
Inbound and outbound channel rate limiting primitives.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class RateLimitConfig:
    user_requests_per_minute: int = 20
    user_requests_per_hour: int = 200
    channel_sends_per_second: float = 1.0
    channel_sends_per_minute: int = 20
    max_concurrent_requests: int = 10
    security_block_cooldown_seconds: int = 300


class TokenBucketRateLimiter:
    """Async token bucket for outbound platform send pacing."""

    def __init__(self, rate_per_second: float, burst: int = 5) -> None:
        self._rate = max(rate_per_second, 0.001)
        self._burst = max(burst, 1)
        self._tokens = float(self._burst)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._last = now
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)

            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._last = time.monotonic()
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


class SlidingWindowUserLimiter:
    """Per-user inbound request limiter using minute/hour sliding windows."""

    def __init__(self, config: RateLimitConfig) -> None:
        self._config = config
        self._windows: dict[str, deque[float]] = {}

    def check(self, user_id: str) -> tuple[bool, float]:
        now = time.monotonic()
        window = self._windows.setdefault(user_id, deque())

        while window and now - window[0] > 3600:
            window.popleft()

        per_minute = sum(1 for t in window if now - t < 60)
        per_hour = len(window)

        if per_minute >= self._config.user_requests_per_minute:
            retry_after = 60 - (now - window[-self._config.user_requests_per_minute])
            return False, max(0.0, retry_after)

        if per_hour >= self._config.user_requests_per_hour:
            retry_after = 3600 - (now - window[0])
            return False, max(0.0, retry_after)

        window.append(now)
        return True, 0.0

    def reset(self, user_id: str) -> None:
        self._windows.pop(user_id, None)

    def prune_windows(self, max_age_seconds: float = 3600.0) -> int:
        """Drop stale user windows so long-lived gateways don't retain dead users forever."""
        now = time.monotonic()
        stale_users: list[str] = []
        for user_id, window in self._windows.items():
            while window and now - window[0] > max_age_seconds:
                window.popleft()
            if not window:
                stale_users.append(user_id)

        for user_id in stale_users:
            self._windows.pop(user_id, None)
        return len(stale_users)
