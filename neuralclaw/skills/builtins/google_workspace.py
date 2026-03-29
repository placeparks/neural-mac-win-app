"""
Built-in Skill: Google Workspace - Gmail, Calendar, Drive, Docs, and Sheets.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import aiohttp

from neuralclaw.config import GoogleWorkspaceConfig, _get_secret
from neuralclaw.cortex.action.network import validate_url_with_dns
from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

_config = GoogleWorkspaceConfig()
_service: "GoogleWorkspaceService" | None = None


def set_google_workspace_config(config: GoogleWorkspaceConfig) -> None:
    global _config, _service
    _config = config
    _service = GoogleWorkspaceService(_config)


class GoogleWorkspaceService:
    BASE_GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
    BASE_CAL = "https://www.googleapis.com/calendar/v3"
    BASE_DRIVE = "https://www.googleapis.com/drive/v3"
    BASE_UPLOAD = "https://www.googleapis.com/upload/drive/v3"
    BASE_DOCS = "https://docs.googleapis.com/v1"
    BASE_SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"

    def __init__(self, config: GoogleWorkspaceConfig | None = None) -> None:
        self._config = config or _config

    def _token(self) -> str:
        return (
            _get_secret("google_oauth_access")
            or _get_secret("google_oauth_refresh")
            or ""
        )

    def _guard(self) -> dict[str, Any] | None:
        if not self._config.enabled:
            return {"error": "Google Workspace skill is disabled"}
        if not self._token():
            return {"error": "Google Workspace auth required. Run `neuralclaw session auth google`."}
        return None

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        guard = self._guard()
        if guard:
            return guard
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
                        return {"error": f"Google API error ({resp.status}): {payload[:300]}"}
                    if not payload:
                        return {"success": True}
                    try:
                        return json.loads(payload)
                    except json.JSONDecodeError:
                        return {"success": True, "body": payload[: self._config.response_body_limit]}
        except Exception as exc:
            return {"error": str(exc)}

def _get_service() -> GoogleWorkspaceService:
    global _service
    if _service is None:
        _service = GoogleWorkspaceService(_config)
    return _service


async def gmail_search(query: str, max_results: int = 10, **kwargs: Any) -> dict[str, Any]:
    service = _get_service()
    result = await service._request(
        "GET",
        f"{service.BASE_GMAIL}/messages",
        params={"q": query, "maxResults": min(max_results, _config.max_email_results)},
    )
    if result.get("error"):
        return result
    return {"messages": result.get("messages", []), "count": len(result.get("messages", []))}


async def gmail_send(to: str, subject: str, body: str, **kwargs: Any) -> dict[str, Any]:
    service = _get_service()
    raw = base64.urlsafe_b64encode(f"To: {to}\r\nSubject: {subject}\r\n\r\n{body}".encode("utf-8")).decode("ascii")
    result = await service._request("POST", f"{service.BASE_GMAIL}/messages/send", json_body={"raw": raw})
    return result if result.get("error") else {"sent": True, "id": result.get("id", "")}


async def gmail_get(message_id: str, **kwargs: Any) -> dict[str, Any]:
    service = _get_service()
    return await service._request("GET", f"{service.BASE_GMAIL}/messages/{message_id}", params={"format": "full"})


async def gmail_label(message_id: str, add_labels: list[str] | None = None, remove_labels: list[str] | None = None, **kwargs: Any) -> dict[str, Any]:
    service = _get_service()
    result = await service._request(
        "POST",
        f"{service.BASE_GMAIL}/messages/{message_id}/modify",
        json_body={"addLabelIds": add_labels or [], "removeLabelIds": remove_labels or []},
    )
    return result if result.get("error") else {"updated": True, "id": message_id}


async def gmail_draft(to: str, subject: str, body: str, **kwargs: Any) -> dict[str, Any]:
    service = _get_service()
    raw = base64.urlsafe_b64encode(f"To: {to}\r\nSubject: {subject}\r\n\r\n{body}".encode("utf-8")).decode("ascii")
    result = await service._request("POST", f"{service.BASE_GMAIL}/drafts", json_body={"message": {"raw": raw}})
    return result if result.get("error") else {"draft_id": result.get("id", "")}


async def gcal_list_events(time_min: str = "", time_max: str = "", calendar_id: str = "", **kwargs: Any) -> dict[str, Any]:
    service = _get_service()
    result = await service._request(
        "GET",
        f"{service.BASE_CAL}/calendars/{calendar_id or _config.default_calendar_id}/events",
        params={k: v for k, v in {"timeMin": time_min, "timeMax": time_max}.items() if v},
    )
    return result if result.get("error") else {"events": result.get("items", []), "count": len(result.get("items", []))}


async def gcal_create_event(summary: str, start_time: str, end_time: str, calendar_id: str = "", **kwargs: Any) -> dict[str, Any]:
    service = _get_service()
    return await service._request(
        "POST",
        f"{service.BASE_CAL}/calendars/{calendar_id or _config.default_calendar_id}/events",
        json_body={"summary": summary, "start": {"dateTime": start_time}, "end": {"dateTime": end_time}},
    )


async def gcal_update_event(event_id: str, updates: dict[str, Any], calendar_id: str = "", **kwargs: Any) -> dict[str, Any]:
    service = _get_service()
    return await service._request(
        "PATCH",
        f"{service.BASE_CAL}/calendars/{calendar_id or _config.default_calendar_id}/events/{event_id}",
        json_body=updates,
    )


async def gcal_delete_event(event_id: str, calendar_id: str = "", **kwargs: Any) -> dict[str, Any]:
    service = _get_service()
    result = await service._request(
        "DELETE",
        f"{service.BASE_CAL}/calendars/{calendar_id or _config.default_calendar_id}/events/{event_id}",
    )
    return result if result.get("error") else {"deleted": True, "id": event_id}


async def gdrive_search(query: str, max_results: int = 10, **kwargs: Any) -> dict[str, Any]:
    service = _get_service()
    result = await service._request("GET", service.BASE_DRIVE + "/files", params={"q": query, "pageSize": min(max_results, _config.max_drive_results)})
    return result if result.get("error") else {"files": result.get("files", []), "count": len(result.get("files", []))}


async def gdrive_read(file_id: str, **kwargs: Any) -> dict[str, Any]:
    service = _get_service()
    return await service._request("GET", f"{service.BASE_DRIVE}/files/{file_id}", params={"alt": "media"})


async def gdrive_upload(file_path: str, name: str = "", mime_type: str = "application/octet-stream", **kwargs: Any) -> dict[str, Any]:
    service = _get_service()
    guard = service._guard()
    if guard:
        return guard
    path = Path(file_path).expanduser()
    if not path.exists():
        return {"error": f"File not found: {path}"}
    content = await asyncio.to_thread(path.read_bytes)
    result = await service._request(
        "POST",
        f"{service.BASE_UPLOAD}/files",
        params={"uploadType": "media"},
        data=content,
        headers={"Content-Type": mime_type},
    )
    return result if result.get("error") else {"uploaded": True, "name": name or path.name, "id": result.get("id", "")}


async def gdocs_read(document_id: str, **kwargs: Any) -> dict[str, Any]:
    service = _get_service()
    return await service._request("GET", f"{service.BASE_DOCS}/documents/{document_id}")


async def gdocs_append(document_id: str, text: str, **kwargs: Any) -> dict[str, Any]:
    doc = await gdocs_read(document_id)
    if doc.get("error"):
        return doc
    end_index = doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 1) - 1
    service = _get_service()
    return await service._request(
        "POST",
        f"{service.BASE_DOCS}/documents/{document_id}:batchUpdate",
        json_body={"requests": [{"insertText": {"location": {"index": max(1, end_index)}, "text": text}}]},
    )


async def gsheets_read(spreadsheet_id: str, range_name: str, **kwargs: Any) -> dict[str, Any]:
    service = _get_service()
    return await service._request("GET", f"{service.BASE_SHEETS}/{spreadsheet_id}/values/{range_name}")


async def gsheets_write(spreadsheet_id: str, range_name: str, values: list[list[Any]], **kwargs: Any) -> dict[str, Any]:
    service = _get_service()
    return await service._request(
        "PUT",
        f"{service.BASE_SHEETS}/{spreadsheet_id}/values/{range_name}",
        params={"valueInputOption": "RAW"},
        json_body={"range": range_name, "values": values},
    )


async def gmeet_create(summary: str = "NeuralClaw Meeting", **kwargs: Any) -> dict[str, Any]:
    event = await gcal_create_event(
        summary=summary,
        start_time="2030-01-01T09:00:00Z",
        end_time="2030-01-01T10:00:00Z",
    )
    if event.get("error"):
        return event
    return {"meet_link": event.get("hangoutLink", ""), "event": event}


def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="google_workspace",
        description="Access Gmail, Calendar, Drive, Docs, Sheets, and Meet.",
        capabilities=[
            Capability.GOOGLE_GMAIL,
            Capability.GOOGLE_CALENDAR,
            Capability.GOOGLE_DRIVE,
            Capability.GOOGLE_DOCS,
            Capability.GOOGLE_SHEETS,
        ],
        tools=[
            ToolDefinition("gmail_search", "Search Gmail with a query string.", [ToolParameter("query", "string", "Gmail search query"), ToolParameter("max_results", "integer", "Maximum messages to return", required=False, default=10)], gmail_search),
            ToolDefinition("gmail_send", "Send an email via Gmail.", [ToolParameter("to", "string", "Recipient email"), ToolParameter("subject", "string", "Subject"), ToolParameter("body", "string", "Email body")], gmail_send),
            ToolDefinition("gmail_get", "Fetch a Gmail message by id.", [ToolParameter("message_id", "string", "Gmail message id")], gmail_get),
            ToolDefinition("gmail_label", "Apply or remove labels on a Gmail message.", [ToolParameter("message_id", "string", "Gmail message id"), ToolParameter("add_labels", "array", "Labels to add", required=False), ToolParameter("remove_labels", "array", "Labels to remove", required=False)], gmail_label),
            ToolDefinition("gmail_draft", "Create a Gmail draft.", [ToolParameter("to", "string", "Recipient email"), ToolParameter("subject", "string", "Subject"), ToolParameter("body", "string", "Draft body")], gmail_draft),
            ToolDefinition("gcal_list_events", "List Google Calendar events.", [ToolParameter("time_min", "string", "Optional ISO start time", required=False), ToolParameter("time_max", "string", "Optional ISO end time", required=False), ToolParameter("calendar_id", "string", "Optional calendar id", required=False)], gcal_list_events),
            ToolDefinition("gcal_create_event", "Create a Google Calendar event.", [ToolParameter("summary", "string", "Event summary"), ToolParameter("start_time", "string", "ISO start time"), ToolParameter("end_time", "string", "ISO end time"), ToolParameter("calendar_id", "string", "Optional calendar id", required=False)], gcal_create_event),
            ToolDefinition("gcal_update_event", "Update a Google Calendar event.", [ToolParameter("event_id", "string", "Event id"), ToolParameter("updates", "object", "Fields to update"), ToolParameter("calendar_id", "string", "Optional calendar id", required=False)], gcal_update_event),
            ToolDefinition("gcal_delete_event", "Delete a Google Calendar event.", [ToolParameter("event_id", "string", "Event id"), ToolParameter("calendar_id", "string", "Optional calendar id", required=False)], gcal_delete_event),
            ToolDefinition("gdrive_search", "Search Google Drive files.", [ToolParameter("query", "string", "Drive search query"), ToolParameter("max_results", "integer", "Maximum files to return", required=False, default=10)], gdrive_search),
            ToolDefinition("gdrive_read", "Read a Google Drive file.", [ToolParameter("file_id", "string", "Drive file id")], gdrive_read),
            ToolDefinition("gdrive_upload", "Upload a file to Google Drive.", [ToolParameter("file_path", "string", "Local file path"), ToolParameter("name", "string", "Optional uploaded name", required=False, default=""), ToolParameter("mime_type", "string", "Upload mime type", required=False, default="application/octet-stream")], gdrive_upload),
            ToolDefinition("gdocs_read", "Read a Google Doc.", [ToolParameter("document_id", "string", "Document id")], gdocs_read),
            ToolDefinition("gdocs_append", "Append text to a Google Doc.", [ToolParameter("document_id", "string", "Document id"), ToolParameter("text", "string", "Text to append")], gdocs_append),
            ToolDefinition("gsheets_read", "Read values from a Google Sheet range.", [ToolParameter("spreadsheet_id", "string", "Spreadsheet id"), ToolParameter("range_name", "string", "A1 range")], gsheets_read),
            ToolDefinition("gsheets_write", "Write values to a Google Sheet range.", [ToolParameter("spreadsheet_id", "string", "Spreadsheet id"), ToolParameter("range_name", "string", "A1 range"), ToolParameter("values", "array", "Two-dimensional sheet values", items_type="array")], gsheets_write),
            ToolDefinition("gmeet_create", "Create a Meet-backed calendar event.", [ToolParameter("summary", "string", "Meeting summary", required=False, default="NeuralClaw Meeting")], gmeet_create),
        ],
    )
