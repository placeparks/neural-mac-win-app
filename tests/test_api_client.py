"""Tests for the api_client builtin skill."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neuralclaw.skills.builtins.api_client import (
    _inject_auth,
    _resolve_url,
    api_request,
    list_api_configs,
    save_api_config,
    set_api_configs,
)


# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------


class TestResolveUrl:
    def test_absolute_url_unchanged(self):
        assert _resolve_url("https://api.example.com", "https://other.com/v1/data") == "https://other.com/v1/data"

    def test_relative_path_prepended(self):
        assert _resolve_url("https://api.example.com/v2", "/weather") == "https://api.example.com/v2/weather"

    def test_trailing_slash_handled(self):
        assert _resolve_url("https://api.example.com/v2/", "/weather") == "https://api.example.com/v2/weather"

    def test_empty_base_url(self):
        assert _resolve_url("", "/weather") == "/weather"


# ---------------------------------------------------------------------------
# Auth injection
# ---------------------------------------------------------------------------


class TestInjectAuth:
    def test_bearer(self):
        with patch("neuralclaw.skills.builtins.api_client._get_secret", return_value="sk-test123"):
            headers, params = _inject_auth({}, {}, "myapi", {"auth_type": "bearer"})
            assert headers["Authorization"] == "Bearer sk-test123"

    def test_api_key_header(self):
        with patch("neuralclaw.skills.builtins.api_client._get_secret", return_value="key123"):
            headers, params = _inject_auth({}, {}, "myapi", {
                "auth_type": "api_key_header",
                "auth_header_name": "X-Custom-Key",
            })
            assert headers["X-Custom-Key"] == "key123"

    def test_api_key_header_default_name(self):
        with patch("neuralclaw.skills.builtins.api_client._get_secret", return_value="key123"):
            headers, _ = _inject_auth({}, {}, "myapi", {"auth_type": "api_key_header"})
            assert headers["X-API-Key"] == "key123"

    def test_api_key_query(self):
        with patch("neuralclaw.skills.builtins.api_client._get_secret", return_value="key123"):
            headers, params = _inject_auth({}, {}, "myapi", {
                "auth_type": "api_key_query",
                "auth_query_param": "appid",
            })
            assert params["appid"] == "key123"

    def test_api_key_query_default_param(self):
        with patch("neuralclaw.skills.builtins.api_client._get_secret", return_value="key123"):
            _, params = _inject_auth({}, {}, "myapi", {"auth_type": "api_key_query"})
            assert params["api_key"] == "key123"

    def test_basic_auth(self):
        with patch("neuralclaw.skills.builtins.api_client._get_secret", return_value="user:pass"):
            headers, _ = _inject_auth({}, {}, "myapi", {"auth_type": "basic"})
            assert headers["Authorization"].startswith("Basic ")

    def test_no_key_found(self):
        with patch("neuralclaw.skills.builtins.api_client._get_secret", return_value=None):
            headers, params = _inject_auth({}, {}, "myapi", {"auth_type": "bearer"})
            assert "Authorization" not in headers


# ---------------------------------------------------------------------------
# api_request — SSRF protection
# ---------------------------------------------------------------------------


class TestApiRequestSSRF:
    @pytest.mark.asyncio
    async def test_localhost_blocked(self):
        result = await api_request("GET", "http://localhost:8080/api")
        assert "error" in result
        assert "blocked" in result["error"].lower() or "denied" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_private_ip_blocked(self):
        result = await api_request("GET", "http://192.168.1.1/api")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_cloud_metadata_blocked(self):
        result = await api_request("GET", "http://169.254.169.254/latest/meta-data")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_method(self):
        result = await api_request("INVALID", "https://api.example.com")
        assert "error" in result
        assert "Unsupported" in result["error"]


# ---------------------------------------------------------------------------
# api_request — with api_name
# ---------------------------------------------------------------------------


class TestApiRequestWithConfig:
    @pytest.mark.asyncio
    async def test_unknown_api_name(self):
        set_api_configs({})
        result = await api_request("GET", "/endpoint", api_name="nonexistent")
        assert "error" in result
        assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# save_api_config
# ---------------------------------------------------------------------------


class TestSaveApiConfig:
    @pytest.mark.asyncio
    async def test_invalid_auth_type(self):
        result = await save_api_config("test", "https://api.example.com", "invalid_type", "key123")
        assert "error" in result
        assert "auth_type" in result["error"]

    @pytest.mark.asyncio
    async def test_stores_key_in_keychain(self):
        with (
            patch("neuralclaw.skills.builtins.api_client._set_secret") as mock_set,
            patch("neuralclaw.skills.builtins.api_client.update_config") as mock_update,
            patch("neuralclaw.skills.builtins.api_client.validate_url") as mock_validate,
        ):
            mock_validate.return_value = MagicMock(allowed=True)
            result = await save_api_config("weather", "https://api.weather.com", "bearer", "sk-key123")

            assert result["success"] is True
            mock_set.assert_called_once_with("api_weather_key", "sk-key123")
            mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_sanitises_name(self):
        with (
            patch("neuralclaw.skills.builtins.api_client._set_secret"),
            patch("neuralclaw.skills.builtins.api_client.update_config"),
            patch("neuralclaw.skills.builtins.api_client.validate_url") as mock_validate,
        ):
            mock_validate.return_value = MagicMock(allowed=True)
            result = await save_api_config("My API!", "https://api.example.com", "bearer", "key")
            assert result["name"] == "my_api_"

    @pytest.mark.asyncio
    async def test_ssrf_blocks_private_base_url(self):
        result = await save_api_config("test", "http://192.168.1.1:8080", "bearer", "key")
        assert "error" in result
        assert "blocked" in result["error"].lower()


# ---------------------------------------------------------------------------
# list_api_configs
# ---------------------------------------------------------------------------


class TestListApiConfigs:
    @pytest.mark.asyncio
    async def test_empty(self):
        set_api_configs({})
        result = await list_api_configs()
        assert result["apis"] == []

    @pytest.mark.asyncio
    async def test_returns_configs_without_keys(self):
        set_api_configs({
            "weather": {"base_url": "https://api.weather.com", "auth_type": "bearer"},
            "github": {"base_url": "https://api.github.com", "auth_type": "api_key_header"},
        })
        with patch("neuralclaw.skills.builtins.api_client._get_secret", return_value="secret"):
            result = await list_api_configs()

        assert len(result["apis"]) == 2
        for api in result["apis"]:
            assert "name" in api
            assert "base_url" in api
            assert "has_key" in api
            # Ensure no actual key value is returned
            assert "auth_key" not in api
            assert "secret" not in json.dumps(api)

    @pytest.mark.asyncio
    async def test_has_key_false_when_missing(self):
        set_api_configs({"test": {"base_url": "https://example.com", "auth_type": "bearer"}})
        with patch("neuralclaw.skills.builtins.api_client._get_secret", return_value=None):
            result = await list_api_configs()
        assert result["apis"][0]["has_key"] is False
