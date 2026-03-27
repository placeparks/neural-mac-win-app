"""
Built-in Skill: API Client — Make authenticated HTTP requests.

Allows agents to call external APIs with user-provided credentials.
API keys are stored in the OS keychain (never in plaintext).  All
outbound requests go through SSRF validation.

Security:
- SSRF protection (private IPs, DNS rebinding, cloud metadata blocked)
- Redirect validation (redirects to private IPs blocked)
- Response body capped at 50 000 characters
- API keys stored in OS keychain, redacted in audit logs
"""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import urlencode, urlparse

import aiohttp

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.cortex.action.network import validate_url, validate_url_with_dns
from neuralclaw.config import _get_secret, _set_secret, update_config
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

# Loaded from config.toml [apis] section by gateway on init
_api_configs: dict[str, dict[str, Any]] = {}

RESPONSE_CAP = 50_000


def set_api_configs(configs: dict[str, dict[str, Any]]) -> None:
    """Set API configurations from config."""
    global _api_configs
    _api_configs = dict(configs) if configs else {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inject_auth(
    headers: dict[str, str],
    params: dict[str, str],
    api_name: str,
    api_config: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    """Inject authentication into headers / params based on stored config."""
    auth_type = api_config.get("auth_type", "bearer")
    api_key = _get_secret(f"api_{api_name}_key") or ""

    if not api_key:
        return headers, params

    if auth_type == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_type == "api_key_header":
        header_name = api_config.get("auth_header_name", "X-API-Key")
        headers[header_name] = api_key
    elif auth_type == "api_key_query":
        param_name = api_config.get("auth_query_param", "api_key")
        params[param_name] = api_key
    elif auth_type == "basic":
        encoded = base64.b64encode(api_key.encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"

    return headers, params


def _resolve_url(base_url: str, url: str) -> str:
    """If *url* is relative (starts with ``/``), prepend *base_url*."""
    if url.startswith("/") and base_url:
        return base_url.rstrip("/") + url
    return url


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

async def api_request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    query_params: dict[str, str] | None = None,
    api_name: str | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """Make an authenticated HTTP request."""
    method = method.upper()
    if method not in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
        return {"error": f"Unsupported HTTP method: {method}"}

    headers = dict(headers or {})
    params = dict(query_params or {})

    # If using a saved API config, resolve base URL and inject auth
    if api_name:
        api_config = _api_configs.get(api_name)
        if not api_config:
            return {"error": f"API config '{api_name}' not found. Use save_api_config first or list_api_configs to see available configs."}
        base_url = api_config.get("base_url", "")
        url = _resolve_url(base_url, url)
        headers, params = _inject_auth(headers, params, api_name, api_config)

    # SSRF validation
    url_check = await validate_url_with_dns(url)
    if not url_check.allowed:
        return {"error": f"URL blocked by security policy: {url_check.reason}"}

    # Build full URL with query params
    if params:
        separator = "&" if "?" in url else "?"
        url = url + separator + urlencode(params)

    timeout = min(max(timeout_seconds, 5), 60)

    try:
        async with aiohttp.ClientSession() as session:
            kwargs: dict[str, Any] = {
                "timeout": aiohttp.ClientTimeout(total=timeout),
                "allow_redirects": False,  # Manual redirect validation
            }
            if body and method in ("POST", "PUT", "PATCH"):
                # Try to parse as JSON
                try:
                    json_body = json.loads(body)
                    kwargs["json"] = json_body
                    if "Content-Type" not in headers:
                        headers["Content-Type"] = "application/json"
                except (json.JSONDecodeError, TypeError):
                    kwargs["data"] = body

            if headers:
                kwargs["headers"] = headers

            import time as _time
            start = _time.time()

            async with session.request(method, url, **kwargs) as resp:
                elapsed = round((_time.time() - start) * 1000, 1)

                # Handle redirects
                if resp.status in (301, 302, 303, 307, 308):
                    redirect_url = str(resp.headers.get("Location", ""))
                    if redirect_url:
                        redirect_check = await validate_url_with_dns(redirect_url)
                        if not redirect_check.allowed:
                            return {"error": f"Redirect blocked by SSRF policy: {redirect_check.reason}"}
                    return {
                        "success": True,
                        "status_code": resp.status,
                        "redirect_url": redirect_url,
                        "message": "Redirect detected — use the redirect URL for a follow-up request",
                        "elapsed_ms": elapsed,
                    }

                # Read response body
                content_type = resp.content_type or "text/plain"
                resp_headers = {k: v for k, v in resp.headers.items()}

                if "text" in content_type or "json" in content_type or "xml" in content_type:
                    text = await resp.text(errors="replace")
                    resp_body = text[:RESPONSE_CAP]
                else:
                    resp_body = f"[Binary content: {content_type}, {resp.content_length or 'unknown'} bytes]"

                return {
                    "success": 200 <= resp.status < 400,
                    "status_code": resp.status,
                    "headers": resp_headers,
                    "body": resp_body,
                    "content_type": content_type,
                    "elapsed_ms": elapsed,
                }

    except aiohttp.ClientError as e:
        return {"error": f"Request failed: {e}"}
    except Exception as e:
        return {"error": f"Unexpected error: {e}"}


async def save_api_config(
    name: str,
    base_url: str,
    auth_type: str,
    auth_key: str,
    auth_header_name: str = "X-API-Key",
    auth_query_param: str = "api_key",
    **_kwargs: Any,
) -> dict[str, Any]:
    """Save an API configuration for reuse."""
    if auth_type not in ("bearer", "api_key_header", "api_key_query", "basic"):
        return {"error": f"Invalid auth_type: {auth_type}. Must be one of: bearer, api_key_header, api_key_query, basic"}

    # Sanitise name
    import re
    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name).lower()
    if not safe_name:
        return {"error": "Invalid API name"}

    # SSRF-check the base URL
    if base_url:
        url_check = validate_url(base_url)
        if not url_check.allowed:
            return {"error": f"Base URL blocked by security policy: {url_check.reason}"}

    # Store the key securely in keychain
    _set_secret(f"api_{safe_name}_key", auth_key)

    # Store non-secret config in config.toml
    api_config: dict[str, Any] = {
        "base_url": base_url,
        "auth_type": auth_type,
    }
    if auth_type == "api_key_header":
        api_config["auth_header_name"] = auth_header_name
    if auth_type == "api_key_query":
        api_config["auth_query_param"] = auth_query_param

    update_config({"apis": {safe_name: api_config}})

    # Update in-memory config
    _api_configs[safe_name] = api_config

    return {
        "success": True,
        "name": safe_name,
        "base_url": base_url,
        "auth_type": auth_type,
        "message": f"API config '{safe_name}' saved. Key stored securely in keychain.",
    }


async def list_api_configs() -> dict[str, Any]:
    """List saved API configurations (keys are never exposed)."""
    apis: list[dict[str, Any]] = []
    for name, config in _api_configs.items():
        has_key = bool(_get_secret(f"api_{name}_key"))
        apis.append({
            "name": name,
            "base_url": config.get("base_url", ""),
            "auth_type": config.get("auth_type", "bearer"),
            "has_key": has_key,
        })
    return {"apis": apis}


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="api_client",
        description="Make authenticated HTTP API requests",
        capabilities=[Capability.API_CLIENT, Capability.NETWORK_HTTP],
        tools=[
            ToolDefinition(
                name="api_request",
                description=(
                    "Make an authenticated HTTP request to an API. "
                    "Supports GET, POST, PUT, DELETE, PATCH. "
                    "Use api_name to auto-inject saved credentials."
                ),
                parameters=[
                    ToolParameter(
                        name="method", type="string",
                        description="HTTP method (GET, POST, PUT, DELETE, PATCH)",
                    ),
                    ToolParameter(
                        name="url", type="string",
                        description="Full URL or relative path (if api_name is provided, relative paths use its base_url)",
                    ),
                    ToolParameter(
                        name="headers", type="object",
                        description="Custom request headers as key-value pairs",
                        required=False,
                    ),
                    ToolParameter(
                        name="body", type="string",
                        description="Request body (JSON string for POST/PUT/PATCH)",
                        required=False,
                    ),
                    ToolParameter(
                        name="query_params", type="object",
                        description="URL query parameters as key-value pairs",
                        required=False,
                    ),
                    ToolParameter(
                        name="api_name", type="string",
                        description="Name of a saved API config (from save_api_config) for auto-authentication",
                        required=False,
                    ),
                    ToolParameter(
                        name="timeout_seconds", type="integer",
                        description="Request timeout in seconds (default 30, max 60)",
                        required=False, default=30,
                    ),
                ],
                handler=api_request,
            ),
            ToolDefinition(
                name="save_api_config",
                description=(
                    "Save an API configuration for reuse. "
                    "The API key is stored securely in the OS keychain."
                ),
                parameters=[
                    ToolParameter(
                        name="name", type="string",
                        description="Unique name for this API (e.g. 'openweather', 'github')",
                    ),
                    ToolParameter(
                        name="base_url", type="string",
                        description="Base URL for the API (e.g. 'https://api.openweathermap.org/data/2.5')",
                    ),
                    ToolParameter(
                        name="auth_type", type="string",
                        description="Authentication type: bearer, api_key_header, api_key_query, or basic",
                        enum=["bearer", "api_key_header", "api_key_query", "basic"],
                    ),
                    ToolParameter(
                        name="auth_key", type="string",
                        description="The API key or token value",
                    ),
                    ToolParameter(
                        name="auth_header_name", type="string",
                        description="Header name for api_key_header auth type (default: X-API-Key)",
                        required=False,
                    ),
                    ToolParameter(
                        name="auth_query_param", type="string",
                        description="Query param name for api_key_query auth type (default: api_key)",
                        required=False,
                    ),
                ],
                handler=save_api_config,
            ),
            ToolDefinition(
                name="list_api_configs",
                description="List all saved API configurations (keys are never shown)",
                parameters=[],
                handler=list_api_configs,
            ),
        ],
    )
