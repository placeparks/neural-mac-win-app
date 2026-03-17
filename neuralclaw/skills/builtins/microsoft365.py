"""
Built-in Skill: Microsoft 365 - Outlook, Calendar, Teams, OneDrive, SharePoint.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiohttp

from neuralclaw.config import Microsoft365Config, _get_secret
from neuralclaw.cortex.action.network import validate_url_with_dns
from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

_config = Microsoft365Config()
_service: "Microsoft365Service" | None = None


def set_microsoft365_config(config: Microsoft365Config) -> None:
    global _config, _service
    _config = config
    _service = Microsoft365Service(_config)


class Microsoft365Service:
    BASE_GRAPH = "https://graph.microsoft.com/v1.0"

    def __init__(self, config: Microsoft365Config | None = None) -> None:
        self._config = config or _config

    def _token(self) -> str:
        return (
            _get_secret("microsoft365_oauth_access")
            or _get_secret("microsoft_oauth_refresh")
            or ""
        )

    def _guard(self) -> dict[str, Any] | None:
        if not self._config.enabled:
            return {"error": "Microsoft 365 skill is disabled"}
        if not self._token():
            return {"error": "Microsoft 365 auth required. Run `neuralclaw session auth microsoft`."}
        return None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        guard = self._guard()
        if guard:
            return guard
        url = self.BASE_GRAPH + path
        url_check = await validate_url_with_dns(url)
        if not url_check.allowed:
            return {"error": f"Blocked URL: {url_check.reason}"}
        req_headers = {
            "Authorization": f"Bearer {self._token()}",
        }
        if headers:
            req_headers.update(headers)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    data=data,
                    headers=req_headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    payload = await resp.text()
                    if resp.status >= 400:
                        return {"error": f"Microsoft Graph error ({resp.status}): {payload[:300]}"}
                    if not payload:
                        return {"success": True}
                    try:
                        return json.loads(payload)
                    except json.JSONDecodeError:
                        return {"success": True, "body": payload[:20000]}
        except Exception as exc:
            return {"error": str(exc)}

def _get_service() -> Microsoft365Service:
    global _service
    if _service is None:
        _service = Microsoft365Service(_config)
    return _service


async def outlook_search(query: str, max_results: int = 10) -> dict[str, Any]:
    service = _get_service()
    result = await service._request(
        "GET",
        f"/users/{_config.default_user}/messages",
        params={"$search": f'"{query}"', "$top": min(max_results, _config.max_email_results)},
        headers={"ConsistencyLevel": "eventual"},
    )
    return result if result.get("error") else {"messages": result.get("value", []), "count": len(result.get("value", []))}


async def outlook_send(to: str, subject: str, body: str) -> dict[str, Any]:
    service = _get_service()
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        "saveToSentItems": True,
    }
    result = await service._request("POST", f"/users/{_config.default_user}/sendMail", json_body=payload)
    return result if result.get("error") else {"sent": True, "to": to}


async def outlook_get(message_id: str) -> dict[str, Any]:
    service = _get_service()
    return await service._request("GET", f"/users/{_config.default_user}/messages/{message_id}")


async def ms_cal_list(start_time: str = "", end_time: str = "") -> dict[str, Any]:
    service = _get_service()
    params = {}
    if start_time:
        params["startDateTime"] = start_time
    if end_time:
        params["endDateTime"] = end_time
    path = f"/users/{_config.default_user}/calendarView" if params else f"/users/{_config.default_user}/events"
    result = await service._request("GET", path, params=params or None)
    return result if result.get("error") else {"events": result.get("value", []), "count": len(result.get("value", []))}


async def ms_cal_create(subject: str, start_time: str, end_time: str) -> dict[str, Any]:
    service = _get_service()
    return await service._request(
        "POST",
        f"/users/{_config.default_user}/events",
        json_body={
            "subject": subject,
            "start": {"dateTime": start_time, "timeZone": "UTC"},
            "end": {"dateTime": end_time, "timeZone": "UTC"},
        },
    )


async def ms_cal_delete(event_id: str) -> dict[str, Any]:
    service = _get_service()
    result = await service._request("DELETE", f"/users/{_config.default_user}/events/{event_id}")
    return result if result.get("error") else {"deleted": True, "id": event_id}


async def teams_send(chat_or_channel_id: str, text: str) -> dict[str, Any]:
    service = _get_service()
    payload = {"body": {"contentType": "html", "content": text}}
    return await service._request("POST", f"/chats/{chat_or_channel_id}/messages", json_body=payload)


async def teams_list_channels(team_id: str) -> dict[str, Any]:
    service = _get_service()
    result = await service._request("GET", f"/teams/{team_id}/channels")
    return result if result.get("error") else {"channels": result.get("value", []), "count": len(result.get("value", []))}


async def onedrive_search(query: str, max_results: int = 10) -> dict[str, Any]:
    service = _get_service()
    result = await service._request("GET", f"/users/{_config.default_user}/drive/root/search(q='{query}')")
    files = result.get("value", []) if not result.get("error") else []
    return result if result.get("error") else {"files": files[: min(max_results, _config.max_file_results)], "count": len(files[: min(max_results, _config.max_file_results)])}


async def onedrive_read(item_id: str) -> dict[str, Any]:
    service = _get_service()
    return await service._request("GET", f"/users/{_config.default_user}/drive/items/{item_id}/content")


async def onedrive_upload(file_path: str, remote_name: str = "") -> dict[str, Any]:
    service = _get_service()
    guard = service._guard()
    if guard:
        return guard
    path = Path(file_path).expanduser()
    if not path.exists():
        return {"error": f"File not found: {path}"}
    content = await asyncio.to_thread(path.read_bytes)
    name = remote_name or path.name
    result = await service._request(
        "PUT",
        f"/users/{_config.default_user}/drive/root:/{name}:/content",
        data=content,
        headers={"Content-Type": "application/octet-stream"},
    )
    return result if result.get("error") else {"uploaded": True, "name": name, "id": result.get("id", "")}


async def sharepoint_search(query: str) -> dict[str, Any]:
    service = _get_service()
    return await service._request("POST", "/search/query", json_body={"requests": [{"entityTypes": ["driveItem", "listItem"], "query": {"queryString": query}}]})


async def sharepoint_read(item_path: str) -> dict[str, Any]:
    service = _get_service()
    return await service._request("GET", item_path if item_path.startswith("/") else f"/{item_path}")


def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="microsoft365",
        description="Access Outlook, Teams, OneDrive, SharePoint, and Microsoft Calendar.",
        capabilities=[
            Capability.MS_OUTLOOK,
            Capability.MS_CALENDAR,
            Capability.MS_TEAMS,
            Capability.MS_ONEDRIVE,
            Capability.MS_SHAREPOINT,
        ],
        tools=[
            ToolDefinition("outlook_search", "Search Outlook mail.", [ToolParameter("query", "string", "Search query"), ToolParameter("max_results", "integer", "Maximum messages", required=False, default=10)], outlook_search),
            ToolDefinition("outlook_send", "Send Outlook email.", [ToolParameter("to", "string", "Recipient email"), ToolParameter("subject", "string", "Subject"), ToolParameter("body", "string", "Email body")], outlook_send),
            ToolDefinition("outlook_get", "Fetch Outlook email by id.", [ToolParameter("message_id", "string", "Outlook message id")], outlook_get),
            ToolDefinition("ms_cal_list", "List Microsoft calendar events.", [ToolParameter("start_time", "string", "Optional ISO start time", required=False), ToolParameter("end_time", "string", "Optional ISO end time", required=False)], ms_cal_list),
            ToolDefinition("ms_cal_create", "Create Microsoft calendar event.", [ToolParameter("subject", "string", "Event subject"), ToolParameter("start_time", "string", "ISO start time"), ToolParameter("end_time", "string", "ISO end time")], ms_cal_create),
            ToolDefinition("ms_cal_delete", "Delete Microsoft calendar event.", [ToolParameter("event_id", "string", "Event id")], ms_cal_delete),
            ToolDefinition("teams_send", "Send a Teams chat message.", [ToolParameter("chat_or_channel_id", "string", "Teams chat or channel id"), ToolParameter("text", "string", "Message body")], teams_send),
            ToolDefinition("teams_list_channels", "List channels for a Team.", [ToolParameter("team_id", "string", "Team id")], teams_list_channels),
            ToolDefinition("onedrive_search", "Search OneDrive.", [ToolParameter("query", "string", "Search query"), ToolParameter("max_results", "integer", "Maximum files", required=False, default=10)], onedrive_search),
            ToolDefinition("onedrive_read", "Read a OneDrive item.", [ToolParameter("item_id", "string", "Drive item id")], onedrive_read),
            ToolDefinition("onedrive_upload", "Upload a file to OneDrive.", [ToolParameter("file_path", "string", "Local file path"), ToolParameter("remote_name", "string", "Optional remote filename", required=False, default="")], onedrive_upload),
            ToolDefinition("sharepoint_search", "Search SharePoint.", [ToolParameter("query", "string", "Search query")], sharepoint_search),
            ToolDefinition("sharepoint_read", "Read a SharePoint resource path.", [ToolParameter("item_path", "string", "Graph API item path")], sharepoint_read),
        ],
    )
