"""Tests for neuralclaw.session.auth — token store, credential management, auth flows."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neuralclaw.session.auth import (
    EXPIRY_BUFFER,
    REFRESH_BUFFER,
    AuthManager,
    ChatGPTAuthFlow,
    ClaudeAuthFlow,
    TokenCredential,
    TokenStore,
    redact_token,
)


# ---------------------------------------------------------------------------
# TokenCredential
# ---------------------------------------------------------------------------

class TestTokenCredential:
    def test_roundtrip_json(self):
        cred = TokenCredential(
            access_token="tok_abc123",
            provider="chatgpt",
            token_type="oauth",
            expires_at=1700000000.0,
            refresh_token="ref_xyz",
        )
        raw = cred.to_json()
        restored = TokenCredential.from_json(raw)
        assert restored.access_token == "tok_abc123"
        assert restored.refresh_token == "ref_xyz"
        assert restored.provider == "chatgpt"
        assert restored.token_type == "oauth"
        assert restored.expires_at == 1700000000.0

    def test_from_json_invalid(self):
        with pytest.raises((json.JSONDecodeError, TypeError, KeyError)):
            TokenCredential.from_json("not json")


# ---------------------------------------------------------------------------
# TokenStore
# ---------------------------------------------------------------------------

class TestTokenStore:
    @patch("neuralclaw.session.auth._get_secret")
    @patch("neuralclaw.session.auth._set_secret")
    def test_save_and_load(self, mock_set, mock_get):
        store = TokenStore()
        cred = TokenCredential(
            access_token="tok",
            provider="chatgpt",
            token_type="oauth",
            expires_at=time.time() + 3600,
        )
        store.save("chatgpt", cred)
        mock_set.assert_called_once()
        key_used = mock_set.call_args[0][0]
        assert key_used == "chatgpt_token_credential"

        # Simulate load
        mock_get.return_value = cred.to_json()
        loaded = store.load("chatgpt")
        assert loaded is not None
        assert loaded.access_token == "tok"

    @patch("neuralclaw.session.auth._get_secret", return_value=None)
    def test_load_missing(self, _):
        store = TokenStore()
        assert store.load("chatgpt") is None

    @patch("neuralclaw.session.auth._get_secret", return_value="bad json")
    def test_load_corrupt(self, _):
        store = TokenStore()
        assert store.load("chatgpt") is None

    def test_is_expired_with_buffer(self):
        # Expires in 2 minutes (< 5 min buffer) → expired
        cred = TokenCredential(
            access_token="tok", provider="chatgpt", token_type="oauth",
            expires_at=time.time() + 120,
        )
        assert TokenStore.is_expired(cred) is True

    def test_is_not_expired(self):
        cred = TokenCredential(
            access_token="tok", provider="chatgpt", token_type="oauth",
            expires_at=time.time() + 3600,
        )
        assert TokenStore.is_expired(cred) is False

    def test_unknown_expiry_not_expired(self):
        cred = TokenCredential(
            access_token="tok", provider="chatgpt", token_type="cookie",
            expires_at=0,
        )
        assert TokenStore.is_expired(cred) is False

    def test_needs_refresh_true(self):
        # Expires in 8 minutes (< 10 min buffer)
        cred = TokenCredential(
            access_token="tok", provider="chatgpt", token_type="oauth",
            expires_at=time.time() + 480,
        )
        assert TokenStore.needs_refresh(cred) is True

    def test_needs_refresh_false(self):
        cred = TokenCredential(
            access_token="tok", provider="chatgpt", token_type="oauth",
            expires_at=time.time() + 7200,
        )
        assert TokenStore.needs_refresh(cred) is False

    @patch("neuralclaw.session.auth._set_secret")
    def test_delete(self, mock_set):
        store = TokenStore()
        store.delete("chatgpt")
        mock_set.assert_called_once_with("chatgpt_token_credential", "")


# ---------------------------------------------------------------------------
# AuthManager
# ---------------------------------------------------------------------------

class TestAuthManager:
    @patch("neuralclaw.session.auth._get_secret", return_value=None)
    async def test_no_credential(self, _):
        mgr = AuthManager("chatgpt")
        result = await mgr.get_valid_credential()
        assert result is None

    @patch("neuralclaw.session.auth._get_secret")
    async def test_valid_credential(self, mock_get):
        cred = TokenCredential(
            access_token="tok", provider="chatgpt", token_type="oauth",
            expires_at=time.time() + 7200,
        )
        mock_get.return_value = cred.to_json()
        mgr = AuthManager("chatgpt")
        result = await mgr.get_valid_credential()
        assert result is not None
        assert result.access_token == "tok"

    @patch("neuralclaw.session.auth._set_secret")
    @patch("neuralclaw.session.auth._get_secret")
    async def test_expired_no_refresh_token(self, mock_get, mock_set):
        cred = TokenCredential(
            access_token="tok", provider="chatgpt", token_type="oauth",
            expires_at=time.time() - 100,
        )
        mock_get.return_value = cred.to_json()
        mgr = AuthManager("chatgpt")
        result = await mgr.get_valid_credential()
        assert result is None

    @patch("neuralclaw.session.auth._set_secret")
    @patch("neuralclaw.session.auth._get_secret")
    async def test_auto_refresh_chatgpt(self, mock_get, mock_set):
        cred = TokenCredential(
            access_token="old_tok", provider="chatgpt", token_type="oauth",
            expires_at=time.time() - 100,
            refresh_token="ref_tok",
        )
        mock_get.return_value = cred.to_json()
        new_cred = TokenCredential(
            access_token="new_tok", provider="chatgpt", token_type="oauth",
            expires_at=time.time() + 3600,
            refresh_token="ref_tok",
        )
        mgr = AuthManager("chatgpt")
        mgr._chatgpt_flow = MagicMock()
        mgr._chatgpt_flow.refresh_token = AsyncMock(return_value=new_cred)

        result = await mgr.get_valid_credential()
        assert result is not None
        assert result.access_token == "new_tok"

    @patch("neuralclaw.session.auth._set_secret")
    @patch("neuralclaw.session.auth._get_secret", return_value=None)
    async def test_recovers_missing_chatgpt_credential_from_profile(self, mock_get, mock_set):
        mgr = AuthManager("chatgpt")
        recovered = TokenCredential(
            access_token="cookie_tok",
            provider="chatgpt",
            token_type="cookie",
            expires_at=time.time() + 3600,
        )
        mgr._chatgpt_flow = MagicMock()
        mgr._chatgpt_flow.extract_cookie_from_profile = AsyncMock(return_value=recovered)

        result = await mgr.get_valid_credential("C:/profiles/chatgpt")
        assert result is not None
        assert result.access_token == "cookie_tok"
        mock_set.assert_called()

    @patch("neuralclaw.session.auth._set_secret")
    @patch("neuralclaw.session.auth._get_secret")
    async def test_recovers_expired_claude_credential_from_profile(self, mock_get, mock_set):
        expired = TokenCredential(
            access_token="old_sk",
            provider="claude",
            token_type="session_key",
            expires_at=time.time() - 10,
        )
        mock_get.return_value = expired.to_json()
        mgr = AuthManager("claude")
        recovered = TokenCredential(
            access_token="new_sk",
            provider="claude",
            token_type="session_key",
            expires_at=time.time() + 86400,
        )
        mgr._claude_flow = MagicMock()
        mgr._claude_flow.extract_session_key = AsyncMock(return_value=recovered)

        result = await mgr.get_valid_credential("C:/profiles/claude")
        assert result is not None
        assert result.access_token == "new_sk"
        mock_set.assert_called()

    @patch("neuralclaw.session.auth._set_secret")
    @patch("neuralclaw.session.auth._get_secret")
    async def test_force_refresh_claude_recovers_from_profile(self, mock_get, mock_set):
        existing = TokenCredential(
            access_token="old_sk",
            provider="claude",
            token_type="session_key",
            expires_at=time.time() + 100,
        )
        mock_get.return_value = existing.to_json()
        mgr = AuthManager("claude")
        recovered = TokenCredential(
            access_token="fresh_sk",
            provider="claude",
            token_type="session_key",
            expires_at=time.time() + 86400,
        )
        mgr._claude_flow = MagicMock()
        mgr._claude_flow.extract_session_key = AsyncMock(return_value=recovered)

        result = await mgr.force_refresh("C:/profiles/claude")
        assert result.access_token == "fresh_sk"
        mock_set.assert_called()

    @patch("neuralclaw.session.auth._get_secret", return_value=None)
    def test_health_check_no_token(self, _):
        mgr = AuthManager("chatgpt")
        health = mgr.health_check()
        assert health["has_token"] is False
        assert health["valid"] is False

    @patch("neuralclaw.session.auth._get_secret")
    def test_health_check_valid(self, mock_get):
        cred = TokenCredential(
            access_token="tok", provider="chatgpt", token_type="oauth",
            expires_at=time.time() + 7200,
        )
        mock_get.return_value = cred.to_json()
        mgr = AuthManager("chatgpt")
        health = mgr.health_check()
        assert health["has_token"] is True
        assert health["valid"] is True
        assert health["token_type"] == "oauth"

    @patch("neuralclaw.session.auth._get_secret")
    def test_health_check_expired(self, mock_get):
        cred = TokenCredential(
            access_token="tok", provider="chatgpt", token_type="oauth",
            expires_at=time.time() - 100,
        )
        mock_get.return_value = cred.to_json()
        mgr = AuthManager("chatgpt")
        health = mgr.health_check()
        assert health["has_token"] is True
        assert health["valid"] is False


# ---------------------------------------------------------------------------
# ChatGPTAuthFlow — cookie extraction
# ---------------------------------------------------------------------------

class TestChatGPTAuthFlow:
    async def test_extract_cookie_success(self):
        mock_runtime = AsyncMock()
        mock_runtime.extract_cookies.return_value = [
            {"name": "__Secure-next-auth.session-token", "value": "sess_abc", "domain": ".chatgpt.com", "expires": time.time() + 86400},
        ]
        mock_runtime.close = AsyncMock()

        with patch("neuralclaw.session.runtime.ManagedBrowserSession", return_value=mock_runtime):
            flow = ChatGPTAuthFlow()
            cred = await flow.extract_cookie_from_profile("/tmp/profile")
            assert cred.access_token == "sess_abc"
            assert cred.token_type == "cookie"
            assert cred.provider == "chatgpt"

    async def test_extract_cookie_not_found(self):
        mock_runtime = AsyncMock()
        mock_runtime.extract_cookies.return_value = [
            {"name": "other_cookie", "value": "val", "domain": ".chatgpt.com"},
        ]
        mock_runtime.close = AsyncMock()

        with patch("neuralclaw.session.runtime.ManagedBrowserSession", return_value=mock_runtime):
            flow = ChatGPTAuthFlow()
            with pytest.raises(RuntimeError, match="Session cookie not found"):
                await flow.extract_cookie_from_profile("/tmp/profile")

    async def test_extract_cookie_supports_legacy_cookie_name(self):
        mock_runtime = AsyncMock()
        mock_runtime.extract_cookies.side_effect = [
            [],
            [{"name": "next-auth.session-token", "value": "legacy_cookie", "domain": ".chat.openai.com"}],
        ]
        mock_runtime.close = AsyncMock()

        with patch("neuralclaw.session.runtime.ManagedBrowserSession", return_value=mock_runtime):
            flow = ChatGPTAuthFlow()
            cred = await flow.extract_cookie_from_profile("/tmp/profile")
            assert cred.access_token == "legacy_cookie"
            assert cred.token_type == "cookie"

    async def test_guided_browser_login_extracts_cookie(self):
        mock_runtime = AsyncMock()
        mock_runtime.launch = AsyncMock()
        mock_runtime.current_state = AsyncMock(return_value=("ready", True, "session ready", ""))
        mock_runtime.extract_cookies.side_effect = [
            [],
            [{"name": "__Secure-next-auth.session-token", "value": "guided_cookie", "domain": ".chatgpt.com", "expires": time.time() + 86400}],
        ]
        mock_runtime.close = AsyncMock()

        with patch("neuralclaw.session.runtime.ManagedBrowserSession", return_value=mock_runtime):
            flow = ChatGPTAuthFlow()
            cred = await flow.guided_browser_login("/tmp/profile")
            assert cred.access_token == "guided_cookie"
            assert cred.token_type == "cookie"
            assert cred.provider == "chatgpt"


# ---------------------------------------------------------------------------
# ClaudeAuthFlow — session key extraction
# ---------------------------------------------------------------------------

class TestClaudeAuthFlow:
    async def test_extract_session_key_success(self):
        mock_runtime = AsyncMock()
        mock_runtime.extract_cookies.return_value = [
            {"name": "sessionKey", "value": "sk_claude_xyz", "domain": ".claude.ai", "expires": time.time() + 86400 * 30},
        ]
        mock_runtime.close = AsyncMock()

        with patch("neuralclaw.session.runtime.ManagedBrowserSession", return_value=mock_runtime):
            flow = ClaudeAuthFlow()
            cred = await flow.extract_session_key("/tmp/profile")
            assert cred.access_token == "sk_claude_xyz"
            assert cred.token_type == "session_key"
            assert cred.provider == "claude"

    async def test_extract_session_key_not_found(self):
        mock_runtime = AsyncMock()
        mock_runtime.extract_cookies.return_value = []
        mock_runtime.close = AsyncMock()

        with patch("neuralclaw.session.runtime.ManagedBrowserSession", return_value=mock_runtime):
            flow = ClaudeAuthFlow()
            with pytest.raises(RuntimeError, match="Session key not found"):
                await flow.extract_session_key("/tmp/profile")


# ---------------------------------------------------------------------------
# redact_token
# ---------------------------------------------------------------------------

class TestRedactToken:
    def test_short_token(self):
        assert redact_token("abc") == "****"

    def test_long_token(self):
        result = redact_token("abcdefghijklmnop")
        assert result == "abcd...mnop"
        assert "efgh" not in result
