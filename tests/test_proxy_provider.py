"""Tests for the ProxyProvider."""

import pytest

from neuralclaw.providers.proxy import ProxyProvider


class TestProxyProvider:
    def test_name(self):
        p = ProxyProvider(base_url="http://localhost:8080/v1")
        assert p.name == "proxy"

    def test_no_api_key_uses_placeholder(self):
        p = ProxyProvider(base_url="http://localhost:8080/v1")
        assert p._api_key == "proxy"

    def test_custom_api_key(self):
        p = ProxyProvider(base_url="http://localhost:8080/v1", api_key="my-secret")
        assert p._api_key == "my-secret"

    def test_custom_model(self):
        p = ProxyProvider(base_url="http://localhost:8080/v1", model="gpt-3.5-turbo")
        assert p._model == "gpt-3.5-turbo"

    def test_base_url_stored(self):
        p = ProxyProvider(base_url="http://localhost:8080/v1")
        assert p._base_url == "http://localhost:8080/v1"

    @pytest.mark.asyncio
    async def test_is_available_unreachable(self):
        p = ProxyProvider(base_url="http://localhost:59999/v1")
        assert await p.is_available() is False
