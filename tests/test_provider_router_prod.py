from __future__ import annotations

import pytest

from neuralclaw.errors import ProviderError
from neuralclaw.providers.circuit_breaker import CircuitState
from neuralclaw.providers.circuit_breaker import CircuitBreakerConfig
from neuralclaw.providers.router import LLMResponse, ProviderRouter


class FailingProvider:
    def __init__(self, name: str, message: str = "boom") -> None:
        self.name = name
        self.supports_tools = True
        self._message = message

    async def complete(self, messages, tools=None, temperature=0.7, max_tokens=4096):
        raise RuntimeError(self._message)

    async def is_available(self):
        return True


class SuccessProvider:
    def __init__(self, name: str, content: str = "ok") -> None:
        self.name = name
        self.supports_tools = True
        self._content = content

    async def complete(self, messages, tools=None, temperature=0.7, max_tokens=4096):
        return LLMResponse(content=self._content, model=self.name)

    async def is_available(self):
        return True


@pytest.mark.asyncio
async def test_router_falls_back_when_primary_circuit_opens():
    primary = FailingProvider("primary")
    fallback = SuccessProvider("fallback", content="from fallback")
    router = ProviderRouter(
        primary=primary,
        fallbacks=[fallback],
        max_retries=0,
        breaker_config=CircuitBreakerConfig(
            failure_threshold=1,
            success_threshold=1,
            timeout_seconds=60.0,
        ),
    )

    first = await router.complete([{"role": "user", "content": "hello"}])
    second = await router.complete([{"role": "user", "content": "hello again"}])

    assert first.content == "from fallback"
    assert second.content == "from fallback"
    assert router.get_circuit_states()["primary"] == "open"


@pytest.mark.asyncio
async def test_router_raises_provider_error_when_all_providers_fail():
    router = ProviderRouter(
        primary=FailingProvider("primary", "primary failed"),
        fallbacks=[FailingProvider("fallback", "fallback failed")],
        max_retries=0,
        breaker_config=CircuitBreakerConfig(failure_threshold=1),
    )

    with pytest.raises(ProviderError) as exc:
        await router.complete([{"role": "user", "content": "hello"}])

    assert "All providers failed" in str(exc.value)


def test_router_reset_circuit():
    router = ProviderRouter(
        primary=SuccessProvider("primary"),
        fallbacks=[SuccessProvider("fallback")],
        max_retries=0,
    )
    router._breakers["primary"]._state = CircuitState.OPEN

    assert router.reset_circuit("primary") is True
    assert router.get_circuit_states()["primary"] == "closed"
    assert router.reset_circuit("missing") is False
