"""
Token-based authentication for ChatGPT and Claude app sessions.

Provides OAuth 2.0 flow for ChatGPT, session key extraction for Claude,
and unified token management with secure keyring storage.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import socket
import time
import webbrowser
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

from neuralclaw.config import _get_secret, _set_secret


# ---------------------------------------------------------------------------
# Token credential
# ---------------------------------------------------------------------------

@dataclass
class TokenCredential:
    """Stored auth credential for a provider."""

    access_token: str
    provider: str
    token_type: str  # "oauth" | "session_key" | "cookie"
    expires_at: float = 0.0  # Unix timestamp; 0 = unknown/never
    refresh_token: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> TokenCredential:
        data = json.loads(raw)
        return cls(**data)


# ---------------------------------------------------------------------------
# Token store — wraps keyring / .secrets.toml
# ---------------------------------------------------------------------------

EXPIRY_BUFFER = 300  # 5 minutes
REFRESH_BUFFER = 600  # 10 minutes


class TokenStore:
    """Persist and retrieve token credentials via OS keychain."""

    @staticmethod
    def _key(provider: str) -> str:
        return f"{provider}_token_credential"

    def save(self, provider: str, credential: TokenCredential) -> None:
        _set_secret(self._key(provider), credential.to_json())

    def load(self, provider: str) -> TokenCredential | None:
        raw = _get_secret(self._key(provider))
        if not raw:
            return None
        try:
            return TokenCredential.from_json(raw)
        except (json.JSONDecodeError, TypeError, KeyError):
            return None

    def delete(self, provider: str) -> None:
        _set_secret(self._key(provider), "")

    @staticmethod
    def is_expired(credential: TokenCredential) -> bool:
        if credential.expires_at <= 0:
            return False  # Unknown expiry → assume still valid
        return time.time() >= (credential.expires_at - EXPIRY_BUFFER)

    @staticmethod
    def needs_refresh(credential: TokenCredential) -> bool:
        if credential.expires_at <= 0:
            return False
        return time.time() >= (credential.expires_at - REFRESH_BUFFER)


# ---------------------------------------------------------------------------
# ChatGPT auth flow
# ---------------------------------------------------------------------------

# OpenAI OAuth constants (public client — no client_secret needed)
_OPENAI_AUTH_URL = "https://auth0.openai.com/authorize"
_OPENAI_TOKEN_URL = "https://auth0.openai.com/oauth/token"
_OPENAI_CLIENT_ID = "pdlLIX2Y72MIl2rhLhTE9VV9bN905kBh"  # Public web client
_OPENAI_AUDIENCE = "https://api.openai.com/v1"
_OPENAI_SCOPE = "openid email profile offline_access"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ChatGPTAuthFlow:
    """Handles ChatGPT token acquisition via OAuth or cookie extraction."""

    def oauth_flow(self, timeout: int = 120) -> TokenCredential:
        """Run OAuth 2.0 authorization code flow with local callback server."""
        port = _find_free_port()
        redirect_uri = f"http://localhost:{port}/callback"
        state = secrets.token_urlsafe(32)

        result: dict[str, Any] = {}
        error: str = ""

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                nonlocal result, error
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)

                if parsed.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return

                received_state = params.get("state", [""])[0]
                if received_state != state:
                    error = "OAuth state mismatch — possible CSRF attack"
                    self._respond("Authentication failed: state mismatch.")
                    return

                if "error" in params:
                    error = params["error"][0]
                    self._respond(f"Authentication failed: {error}")
                    return

                code = params.get("code", [""])[0]
                if not code:
                    error = "No authorization code received"
                    self._respond("Authentication failed: no code.")
                    return

                result["code"] = code
                self._respond(
                    "Authentication successful! You can close this tab and "
                    "return to the terminal."
                )

            def _respond(self, message: str) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                body = (
                    f"<html><body style='font-family:sans-serif;text-align:center;"
                    f"padding:60px'><h2>{message}</h2></body></html>"
                )
                self.wfile.write(body.encode())

            def log_message(self, *_args: Any) -> None:
                pass  # Suppress server logs

        server = HTTPServer(("127.0.0.1", port), CallbackHandler)
        server.timeout = timeout

        auth_params = urlencode({
            "response_type": "code",
            "client_id": _OPENAI_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": _OPENAI_SCOPE,
            "audience": _OPENAI_AUDIENCE,
            "state": state,
        })
        auth_url = f"{_OPENAI_AUTH_URL}?{auth_params}"

        webbrowser.open(auth_url)

        # Wait for callback in a thread
        thread = Thread(target=server.handle_request, daemon=True)
        thread.start()
        thread.join(timeout=timeout)
        server.server_close()

        if error:
            raise RuntimeError(f"OAuth flow failed: {error}")
        if "code" not in result:
            raise RuntimeError("OAuth flow timed out — no callback received")

        # Exchange code for tokens
        return self._exchange_code(result["code"], redirect_uri)

    def _exchange_code(self, code: str, redirect_uri: str) -> TokenCredential:
        """Exchange authorization code for access + refresh tokens."""
        token_data = {
            "grant_type": "authorization_code",
            "client_id": _OPENAI_CLIENT_ID,
            "code": code,
            "redirect_uri": redirect_uri,
        }

        async def _fetch() -> dict[str, Any]:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _OPENAI_TOKEN_URL,
                    json=token_data,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise RuntimeError(
                            f"Token exchange failed ({resp.status}): {body}"
                        )
                    return await resp.json()

        data = asyncio.get_event_loop().run_until_complete(_fetch())

        expires_in = data.get("expires_in", 3600)
        return TokenCredential(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", ""),
            expires_at=time.time() + expires_in,
            token_type="oauth",
            provider="chatgpt",
        )

    async def refresh_token(self, credential: TokenCredential) -> TokenCredential:
        """Refresh an expired ChatGPT OAuth token."""
        if not credential.refresh_token:
            raise RuntimeError("No refresh token available — re-authenticate required")

        token_data = {
            "grant_type": "refresh_token",
            "client_id": _OPENAI_CLIENT_ID,
            "refresh_token": credential.refresh_token,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                _OPENAI_TOKEN_URL,
                json=token_data,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(
                        f"Token refresh failed ({resp.status}): {body}"
                    )
                data = await resp.json()

        expires_in = data.get("expires_in", 3600)
        return TokenCredential(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", credential.refresh_token),
            expires_at=time.time() + expires_in,
            token_type="oauth",
            provider="chatgpt",
        )

    async def extract_cookie_from_profile(self, profile_dir: str) -> TokenCredential:
        """Extract ChatGPT session cookie from a Playwright profile."""
        from neuralclaw.session.runtime import ManagedBrowserSession, SessionRuntimeConfig

        runtime = ManagedBrowserSession(
            SessionRuntimeConfig(
                provider="chatgpt_app",
                profile_dir=profile_dir,
                site_url="https://chatgpt.com",
            )
        )
        try:
            cookies = await runtime.extract_cookies("chatgpt.com")
            for cookie in cookies:
                if cookie.get("name") == "__Secure-next-auth.session-token":
                    expires = cookie.get("expires", 0)
                    return TokenCredential(
                        access_token=cookie["value"],
                        expires_at=expires if expires > 0 else time.time() + 86400 * 30,
                        token_type="cookie",
                        provider="chatgpt",
                    )
            raise RuntimeError(
                "Session cookie not found. Log in to ChatGPT first: "
                "neuralclaw session login chatgpt"
            )
        finally:
            await runtime.close()


# ---------------------------------------------------------------------------
# Claude auth flow
# ---------------------------------------------------------------------------

class ClaudeAuthFlow:
    """Handles Claude session key extraction from browser cookies."""

    async def extract_session_key(self, profile_dir: str) -> TokenCredential:
        """Extract sessionKey cookie from a Playwright profile."""
        from neuralclaw.session.runtime import ManagedBrowserSession, SessionRuntimeConfig

        runtime = ManagedBrowserSession(
            SessionRuntimeConfig(
                provider="claude_app",
                profile_dir=profile_dir,
                site_url="https://claude.ai",
            )
        )
        try:
            cookies = await runtime.extract_cookies("claude.ai")
            for cookie in cookies:
                if cookie.get("name") == "sessionKey":
                    expires = cookie.get("expires", 0)
                    return TokenCredential(
                        access_token=cookie["value"],
                        expires_at=expires if expires > 0 else time.time() + 86400 * 30,
                        token_type="session_key",
                        provider="claude",
                    )
            raise RuntimeError(
                "Session key not found. Log in to Claude first: "
                "neuralclaw session login claude"
            )
        finally:
            await runtime.close()

    async def guided_browser_login(self, profile_dir: str) -> TokenCredential:
        """Open a headed browser for manual login, then extract session key."""
        from neuralclaw.session.runtime import ManagedBrowserSession, SessionRuntimeConfig

        runtime = ManagedBrowserSession(
            SessionRuntimeConfig(
                provider="claude_app",
                profile_dir=profile_dir,
                site_url="https://claude.ai",
                headless=False,
            )
        )
        try:
            await runtime.launch(force_page=True)
            # Wait for user to complete login (poll for session key)
            for _ in range(120):  # 2 minutes max
                cookies = await runtime.extract_cookies("claude.ai")
                for cookie in cookies:
                    if cookie.get("name") == "sessionKey":
                        expires = cookie.get("expires", 0)
                        return TokenCredential(
                            access_token=cookie["value"],
                            expires_at=(
                                expires if expires > 0
                                else time.time() + 86400 * 30
                            ),
                            token_type="session_key",
                            provider="claude",
                        )
                await asyncio.sleep(1)
            raise RuntimeError("Timed out waiting for Claude login")
        finally:
            await runtime.close()


# ---------------------------------------------------------------------------
# Auth manager — high-level coordinator
# ---------------------------------------------------------------------------

class AuthManager:
    """Unified auth manager for token-based providers."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        self._store = TokenStore()
        self._chatgpt_flow = ChatGPTAuthFlow() if provider == "chatgpt" else None
        self._claude_flow = ClaudeAuthFlow() if provider == "claude" else None

    async def get_valid_credential(self) -> TokenCredential | None:
        """Load credential, auto-refresh if possible, return None if invalid."""
        cred = self._store.load(self.provider)
        if cred is None:
            return None

        if not self._store.is_expired(cred):
            # Proactively refresh if approaching expiry (ChatGPT OAuth only)
            if (
                self._store.needs_refresh(cred)
                and cred.token_type == "oauth"
                and self._chatgpt_flow
            ):
                try:
                    cred = await self._chatgpt_flow.refresh_token(cred)
                    self._store.save(self.provider, cred)
                except Exception:
                    pass  # Still valid, just couldn't refresh yet
            return cred

        # Token is expired — try refresh for ChatGPT OAuth
        if cred.token_type == "oauth" and cred.refresh_token and self._chatgpt_flow:
            try:
                cred = await self._chatgpt_flow.refresh_token(cred)
                self._store.save(self.provider, cred)
                return cred
            except Exception:
                return None

        return None  # Expired and can't refresh

    def save_credential(self, credential: TokenCredential) -> None:
        self._store.save(self.provider, credential)

    def delete_credential(self) -> None:
        self._store.delete(self.provider)

    def health_check(self) -> dict[str, Any]:
        """Return token health status."""
        cred = self._store.load(self.provider)
        if cred is None:
            return {
                "provider": self.provider,
                "has_token": False,
                "valid": False,
                "message": "No token credential stored",
            }

        expired = self._store.is_expired(cred)
        needs_refresh = self._store.needs_refresh(cred)
        ttl = max(0, cred.expires_at - time.time()) if cred.expires_at > 0 else None

        return {
            "provider": self.provider,
            "has_token": True,
            "valid": not expired,
            "token_type": cred.token_type,
            "expires_at": cred.expires_at if cred.expires_at > 0 else None,
            "ttl_seconds": ttl,
            "needs_refresh": needs_refresh,
            "has_refresh_token": bool(cred.refresh_token),
            "message": (
                "Token expired" if expired
                else "Token valid (refresh recommended)" if needs_refresh
                else "Token valid"
            ),
        }


def redact_token(token: str) -> str:
    """Redact a token for safe logging — show only first/last 4 chars."""
    if len(token) <= 12:
        return "****"
    return f"{token[:4]}...{token[-4:]}"
