from __future__ import annotations

import pytest

from neuralclaw.config import GoogleWorkspaceConfig
from neuralclaw.skills.builtins import google_workspace


def test_manifest_loads_google_workspace_tools():
    manifest = google_workspace.get_manifest()

    assert manifest.name == "google_workspace"
    tool_names = {tool.name for tool in manifest.tools}
    assert "gmail_search" in tool_names
    assert "gmeet_create" in tool_names


@pytest.mark.asyncio
async def test_google_workspace_auth_error_when_missing_token(monkeypatch):
    google_workspace.set_google_workspace_config(GoogleWorkspaceConfig(enabled=True))
    monkeypatch.setattr(google_workspace, "_get_secret", lambda _key: None)

    result = await google_workspace.gmail_search("from:test@example.com")

    assert "auth required" in result["error"].lower()


@pytest.mark.asyncio
async def test_google_workspace_validates_outbound_url(monkeypatch):
    google_workspace.set_google_workspace_config(GoogleWorkspaceConfig(enabled=True))
    monkeypatch.setattr(google_workspace, "_get_secret", lambda _key: "token")

    class BlockedResult:
        allowed = False
        reason = "blocked_hostname:test"

    async def fake_validate(_url: str):
        return BlockedResult()

    monkeypatch.setattr(google_workspace, "validate_url_with_dns", fake_validate)

    result = await google_workspace.gmail_search("invoice")

    assert "Blocked URL" in result["error"]
