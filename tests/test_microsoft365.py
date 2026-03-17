from __future__ import annotations

import pytest

from neuralclaw.config import Microsoft365Config
from neuralclaw.skills.builtins import microsoft365


def test_manifest_loads_microsoft365_tools():
    manifest = microsoft365.get_manifest()

    assert manifest.name == "microsoft365"
    tool_names = {tool.name for tool in manifest.tools}
    assert "outlook_search" in tool_names
    assert "sharepoint_read" in tool_names


@pytest.mark.asyncio
async def test_microsoft365_auth_error_when_missing_token(monkeypatch):
    microsoft365.set_microsoft365_config(Microsoft365Config(enabled=True))
    monkeypatch.setattr(microsoft365, "_get_secret", lambda _key: None)

    result = await microsoft365.outlook_search("subject:hello")

    assert "auth required" in result["error"].lower()


@pytest.mark.asyncio
async def test_microsoft365_validates_outbound_url(monkeypatch):
    microsoft365.set_microsoft365_config(Microsoft365Config(enabled=True))
    monkeypatch.setattr(microsoft365, "_get_secret", lambda _key: "token")

    class BlockedResult:
        allowed = False
        reason = "dns_rebinding_blocked:test->127.0.0.1"

    async def fake_validate(_url: str):
        return BlockedResult()

    monkeypatch.setattr(microsoft365, "validate_url_with_dns", fake_validate)

    result = await microsoft365.outlook_search("hello")

    assert "Blocked URL" in result["error"]
