"""Tests for ChatGPT and Claude token-based providers."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neuralclaw.session.auth import TokenCredential


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_chatgpt_cred() -> TokenCredential:
    return TokenCredential(
        access_token="tok_chatgpt",
        provider="chatgpt",
        token_type="oauth",
        expires_at=time.time() + 7200,
        refresh_token="ref_tok",
    )


def _valid_claude_cred() -> TokenCredential:
    return TokenCredential(
        access_token="sk_claude",
        provider="claude",
        token_type="session_key",
        expires_at=time.time() + 86400 * 30,
    )


def _expired_cred(provider: str) -> TokenCredential:
    return TokenCredential(
        access_token="expired",
        provider=provider,
        token_type="oauth",
        expires_at=time.time() - 1000,
    )


# ---------------------------------------------------------------------------
# ChatGPTTokenProvider
# ---------------------------------------------------------------------------

class TestChatGPTTokenProvider:
    @patch("neuralclaw.session.auth._get_secret")
    async def test_is_available_with_valid_token(self, mock_get):
        mock_get.return_value = _valid_chatgpt_cred().to_json()
        from neuralclaw.providers.chatgpt_token import ChatGPTTokenProvider
        provider = ChatGPTTokenProvider(model="auto")
        assert await provider.is_available() is True

    @patch("neuralclaw.session.auth._get_secret", return_value=None)
    async def test_is_available_no_token(self, _):
        from neuralclaw.providers.chatgpt_token import ChatGPTTokenProvider
        provider = ChatGPTTokenProvider(model="auto")
        assert await provider.is_available() is False

    @patch("neuralclaw.session.auth._get_secret", return_value=None)
    async def test_complete_no_token_raises(self, _):
        from neuralclaw.providers.chatgpt_token import ChatGPTTokenProvider
        provider = ChatGPTTokenProvider(model="auto")
        with pytest.raises(RuntimeError, match="No valid ChatGPT token"):
            await provider.complete([{"role": "user", "content": "hello"}])

    def test_supports_tools(self):
        from neuralclaw.providers.chatgpt_token import ChatGPTTokenProvider
        provider = ChatGPTTokenProvider(model="auto")
        assert provider.supports_tools is True

    def test_name(self):
        from neuralclaw.providers.chatgpt_token import ChatGPTTokenProvider
        provider = ChatGPTTokenProvider(model="auto")
        assert provider.name == "chatgpt_token"

    @patch("neuralclaw.session.auth._get_secret")
    async def test_get_health(self, mock_get):
        mock_get.return_value = _valid_chatgpt_cred().to_json()
        from neuralclaw.providers.chatgpt_token import ChatGPTTokenProvider
        provider = ChatGPTTokenProvider(model="auto")
        health = await provider.get_health()
        assert health["has_token"] is True
        assert health["valid"] is True
        assert health["supports_tools"] is True

    def test_build_headers_oauth(self):
        from neuralclaw.providers.chatgpt_token import ChatGPTTokenProvider
        provider = ChatGPTTokenProvider(model="auto")
        headers = provider._build_headers("tok123", "oauth")
        assert headers["Authorization"] == "Bearer tok123"

    def test_build_headers_cookie(self):
        from neuralclaw.providers.chatgpt_token import ChatGPTTokenProvider
        provider = ChatGPTTokenProvider(model="auto")
        headers = provider._build_headers("sess_abc", "cookie")
        assert "Cookie" in headers
        assert "sess_abc" in headers["Cookie"]


# ---------------------------------------------------------------------------
# ClaudeTokenProvider
# ---------------------------------------------------------------------------

class TestClaudeTokenProvider:
    @patch("neuralclaw.session.auth._get_secret")
    async def test_is_available_with_valid_token(self, mock_get):
        mock_get.return_value = _valid_claude_cred().to_json()
        from neuralclaw.providers.claude_token import ClaudeTokenProvider
        provider = ClaudeTokenProvider(model="auto")
        assert await provider.is_available() is True

    @patch("neuralclaw.session.auth._get_secret", return_value=None)
    async def test_is_available_no_token(self, _):
        from neuralclaw.providers.claude_token import ClaudeTokenProvider
        provider = ClaudeTokenProvider(model="auto")
        assert await provider.is_available() is False

    @patch("neuralclaw.session.auth._get_secret", return_value=None)
    async def test_complete_no_token_raises(self, _):
        from neuralclaw.providers.claude_token import ClaudeTokenProvider
        provider = ClaudeTokenProvider(model="auto")
        with pytest.raises(RuntimeError, match="No valid Claude session key"):
            await provider.complete([{"role": "user", "content": "hello"}])

    def test_supports_tools_false(self):
        from neuralclaw.providers.claude_token import ClaudeTokenProvider
        provider = ClaudeTokenProvider(model="auto")
        assert provider.supports_tools is False

    def test_name(self):
        from neuralclaw.providers.claude_token import ClaudeTokenProvider
        provider = ClaudeTokenProvider(model="auto")
        assert provider.name == "claude_token"

    @patch("neuralclaw.session.auth._get_secret")
    async def test_get_health(self, mock_get):
        mock_get.return_value = _valid_claude_cred().to_json()
        from neuralclaw.providers.claude_token import ClaudeTokenProvider
        provider = ClaudeTokenProvider(model="auto")
        health = await provider.get_health()
        assert health["has_token"] is True
        assert health["valid"] is True
        assert health["supports_tools"] is False

    def test_build_headers(self):
        from neuralclaw.providers.claude_token import ClaudeTokenProvider
        provider = ClaudeTokenProvider(model="auto")
        headers = provider._build_headers("sk_abc")
        assert "Cookie" in headers
        assert "sessionKey=sk_abc" in headers["Cookie"]


# ---------------------------------------------------------------------------
# Messages to prompt (Claude)
# ---------------------------------------------------------------------------

class TestMessagesToPrompt:
    def test_basic_conversion(self):
        from neuralclaw.providers.claude_token import _messages_to_prompt
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        result = _messages_to_prompt(messages)
        assert "You are helpful." in result
        assert "User: Hello" in result

    def test_empty_messages(self):
        from neuralclaw.providers.claude_token import _messages_to_prompt
        result = _messages_to_prompt([])
        assert result == ""

    def test_skips_none_content(self):
        from neuralclaw.providers.claude_token import _messages_to_prompt
        messages = [
            {"role": "user", "content": None},
            {"role": "user", "content": "Hello"},
        ]
        result = _messages_to_prompt(messages)
        assert "Hello" in result
