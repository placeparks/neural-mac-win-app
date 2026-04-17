"""
Built-in Skill: Clipboard Intelligence — Cross-platform clipboard monitoring,
entity extraction, and contextual action suggestions.

Polls the system clipboard at a configurable interval, maintains a ring
buffer of recent entries, and extracts structured entities (URLs, emails,
IPs, file paths, code snippets, JSON, numbers) from clipboard text.

No external dependencies beyond the standard library. Uses ``tkinter``
for clipboard access with ``pyperclip`` as a fallback.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import deque
from datetime import datetime, timezone
from typing import Any

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_HISTORY = 50
_POLL_INTERVAL = 2.0  # seconds

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_history: deque[dict[str, Any]] = deque(maxlen=_MAX_HISTORY)
_lock = asyncio.Lock()
_monitor_task: asyncio.Task[None] | None = None
_last_content: str = ""

# ---------------------------------------------------------------------------
# Clipboard access (cross-platform, no external deps)
# ---------------------------------------------------------------------------


def _clipboard_get() -> str:
    """Read current clipboard text. Tries tkinter first, then pyperclip."""
    # Attempt 1: tkinter (ships with CPython on all platforms)
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        try:
            text = root.clipboard_get()
        except tk.TclError:
            text = ""
        finally:
            root.destroy()
        return text
    except Exception:
        pass

    # Attempt 2: pyperclip (if installed)
    try:
        import pyperclip  # type: ignore[import-untyped]

        return pyperclip.paste() or ""
    except Exception:
        pass

    return ""


# ---------------------------------------------------------------------------
# Entity extraction (regex-only, no external deps)
# ---------------------------------------------------------------------------

_RE_URL = re.compile(
    r"https?://[^\s<>\"')\]]+",
    re.IGNORECASE,
)
_RE_EMAIL = re.compile(
    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
)
_RE_IPV4 = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
)
_RE_IPV6 = re.compile(
    r"\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b",
)
_RE_FILE_PATH_UNIX = re.compile(
    r"(?:^|(?<=\s))(?:/[^\s/]+)+/?",
    re.MULTILINE,
)
_RE_FILE_PATH_WIN = re.compile(
    r"[A-Za-z]:\\(?:[^\s\\/:*?\"<>|]+\\)*[^\s\\/:*?\"<>|]*",
)
_RE_NUMBER = re.compile(
    r"\b-?(?:\d[\d,]*\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\b",
)
_RE_CODE_FENCE = re.compile(
    r"```[\s\S]*?```",
)


def _extract_entities(text: str) -> dict[str, list[str]]:
    """Extract structured entities from *text* using regex patterns."""
    entities: dict[str, list[str]] = {}

    urls = _RE_URL.findall(text)
    if urls:
        entities["urls"] = list(dict.fromkeys(urls))

    emails = _RE_EMAIL.findall(text)
    if emails:
        entities["emails"] = list(dict.fromkeys(emails))

    ipv4 = _RE_IPV4.findall(text)
    ipv6 = _RE_IPV6.findall(text)
    ips = list(dict.fromkeys(ipv4 + ipv6))
    if ips:
        entities["ips"] = ips

    unix_paths = _RE_FILE_PATH_UNIX.findall(text)
    win_paths = _RE_FILE_PATH_WIN.findall(text)
    paths = list(dict.fromkeys(unix_paths + win_paths))
    if paths:
        entities["file_paths"] = paths

    code_blocks = _RE_CODE_FENCE.findall(text)
    if code_blocks:
        entities["code_snippets"] = code_blocks

    numbers = _RE_NUMBER.findall(text)
    if numbers:
        entities["numbers"] = list(dict.fromkeys(numbers))[:20]  # cap

    return entities


def _detect_content_type(text: str) -> str:
    """Classify *text* into a high-level content type."""
    stripped = text.strip()

    if not stripped:
        return "empty"

    # JSON
    if (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    ):
        try:
            json.loads(stripped)
            return "json"
        except (json.JSONDecodeError, ValueError):
            pass

    # Single URL
    if re.fullmatch(r"https?://\S+", stripped, re.IGNORECASE):
        return "url"

    # Single email
    if re.fullmatch(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", stripped):
        return "email"

    # Single IP address
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", stripped):
        return "ipv4"

    # File path
    if re.fullmatch(r"(/[^\s]+)+/?", stripped) or re.fullmatch(
        r"[A-Za-z]:\\[^\s]+", stripped
    ):
        return "file_path"

    # Code (heuristic: fenced blocks or common syntax)
    if "```" in stripped or re.search(
        r"(def |class |function |import |#include |package )", stripped
    ):
        return "code"

    # Multi-line text
    if "\n" in stripped:
        return "multiline_text"

    return "plain_text"


def _suggest_actions(content_type: str, entities: dict[str, list[str]]) -> list[str]:
    """Return a list of suggested contextual actions based on content."""
    actions: list[str] = []

    if content_type == "url":
        actions.append("fetch_url - Retrieve and extract page content")
        actions.append("web_search - Search for related information")
    elif content_type == "email":
        actions.append("compose_email - Draft a reply to this address")
        actions.append("web_search - Look up this contact")
    elif content_type == "json":
        actions.append("format_json - Pretty-print the JSON")
        actions.append("validate_json - Check structure and schema")
        actions.append("code_exec - Process or transform this data")
    elif content_type == "code":
        actions.append("code_exec - Run or evaluate the code snippet")
        actions.append("explain_code - Get an explanation of the code")
    elif content_type == "ipv4":
        actions.append("web_search - Look up IP geolocation / reputation")
    elif content_type == "file_path":
        actions.append("file_read - Read the contents of this file")
        actions.append("file_info - Get metadata about this path")

    if entities.get("urls"):
        actions.append("fetch_urls - Retrieve all detected URLs")
    if entities.get("emails") and content_type != "email":
        actions.append("extract_contacts - Collect email addresses")
    if entities.get("numbers"):
        actions.append("summarize_numbers - Basic statistics on detected numbers")

    if not actions:
        actions.append("web_search - Search the web for this text")
        actions.append("summarize - Summarize or paraphrase")

    return actions


# ---------------------------------------------------------------------------
# Monitoring loop
# ---------------------------------------------------------------------------


async def _poll_clipboard() -> None:
    """Background polling loop. Detects clipboard changes and records them."""
    global _last_content

    while True:
        await asyncio.sleep(_POLL_INTERVAL)
        try:
            current = await asyncio.get_event_loop().run_in_executor(
                None, _clipboard_get
            )
        except Exception:
            continue

        if not current or current == _last_content:
            continue

        _last_content = current
        entry = _build_entry(current)

        async with _lock:
            _history.append(entry)


def _build_entry(text: str) -> dict[str, Any]:
    """Build a history entry dict for *text*."""
    content_type = _detect_content_type(text)
    entities = _extract_entities(text)
    return {
        "text": text[:4096],  # cap stored text size
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entities": entities,
        "content_type": content_type,
    }


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------


async def clipboard_watch(action: str = "start", **kwargs: Any) -> dict[str, Any]:
    """
    Start or stop clipboard monitoring.

    When started, the clipboard is polled every 2 seconds and changes are
    recorded in the history ring buffer.
    """
    global _monitor_task

    action = action.lower().strip()

    if action == "start":
        if _monitor_task is not None and not _monitor_task.done():
            return {"status": "already_running", "message": "Clipboard monitor is already active."}
        _monitor_task = asyncio.create_task(_poll_clipboard())
        return {"status": "started", "message": "Clipboard monitoring started (polling every 2s)."}

    if action == "stop":
        if _monitor_task is None or _monitor_task.done():
            return {"status": "not_running", "message": "Clipboard monitor is not active."}
        _monitor_task.cancel()
        try:
            await _monitor_task
        except asyncio.CancelledError:
            pass
        _monitor_task = None
        return {"status": "stopped", "message": "Clipboard monitoring stopped."}

    if action == "status":
        running = _monitor_task is not None and not _monitor_task.done()
        async with _lock:
            count = len(_history)
        return {
            "status": "running" if running else "stopped",
            "history_count": count,
        }

    return {"error": f"Unknown action '{action}'. Use 'start', 'stop', or 'status'."}


async def clipboard_history(limit: int = 20, **kwargs: Any) -> dict[str, Any]:
    """
    Return the most recent clipboard entries from the ring buffer.

    Each entry includes the copied text, a UTC timestamp, detected entities,
    and the classified content type.
    """
    limit = max(1, min(limit, _MAX_HISTORY))

    async with _lock:
        entries = list(_history)

    # Return the most recent `limit` entries, newest first
    recent = list(reversed(entries))[:limit]
    return {
        "count": len(recent),
        "total_in_buffer": len(entries),
        "entries": recent,
    }


async def clipboard_analyze(**kwargs: Any) -> dict[str, Any]:
    """
    Analyze the current clipboard content.

    Reads the clipboard, classifies the content type, and extracts all
    detected entities (URLs, emails, IPs, file paths, code, JSON, numbers).
    """
    text = await asyncio.get_event_loop().run_in_executor(None, _clipboard_get)
    if not text:
        return {"error": "Clipboard is empty or inaccessible."}

    content_type = _detect_content_type(text)
    entities = _extract_entities(text)

    result: dict[str, Any] = {
        "content_type": content_type,
        "length": len(text),
        "preview": text[:500],
        "entities": entities,
    }

    # Add parsed JSON preview if applicable
    if content_type == "json":
        try:
            parsed = json.loads(text.strip())
            if isinstance(parsed, dict):
                result["json_keys"] = list(parsed.keys())[:30]
            elif isinstance(parsed, list):
                result["json_length"] = len(parsed)
        except (json.JSONDecodeError, ValueError):
            pass

    return result


async def clipboard_smart_paste(**kwargs: Any) -> dict[str, Any]:
    """
    Read the clipboard and return its content along with suggested actions
    based on the detected content type and extracted entities.
    """
    text = await asyncio.get_event_loop().run_in_executor(None, _clipboard_get)
    if not text:
        return {"error": "Clipboard is empty or inaccessible."}

    content_type = _detect_content_type(text)
    entities = _extract_entities(text)
    actions = _suggest_actions(content_type, entities)

    return {
        "content": text[:4096],
        "content_type": content_type,
        "entities": entities,
        "suggested_actions": actions,
    }


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="clipboard_intel",
        description=(
            "Cross-platform clipboard monitoring, entity extraction, and "
            "contextual action suggestions. Maintains a history ring buffer "
            "of recent clipboard entries."
        ),
        capabilities=[Capability.DESKTOP_CONTROL],
        tools=[
            ToolDefinition(
                name="clipboard_watch",
                description=(
                    "Start or stop clipboard monitoring. When active, polls "
                    "the system clipboard every 2 seconds and records changes "
                    "in a history ring buffer (last 50 entries)."
                ),
                parameters=[
                    ToolParameter(
                        name="action",
                        type="string",
                        description="Action to perform: 'start', 'stop', or 'status'",
                        required=False,
                        default="start",
                        enum=["start", "stop", "status"],
                    ),
                ],
                handler=clipboard_watch,
            ),
            ToolDefinition(
                name="clipboard_history",
                description=(
                    "Return recent clipboard entries from the ring buffer. "
                    "Each entry includes copied text, UTC timestamp, detected "
                    "entities, and content type classification."
                ),
                parameters=[
                    ToolParameter(
                        name="limit",
                        type="integer",
                        description="Number of entries to return (default 20, max 50)",
                        required=False,
                        default=20,
                    ),
                ],
                handler=clipboard_history,
            ),
            ToolDefinition(
                name="clipboard_analyze",
                description=(
                    "Analyze the current clipboard content. Detects content type "
                    "(URL, email, code, JSON, IP, file path, plain text) and "
                    "extracts all structured entities."
                ),
                parameters=[],
                handler=clipboard_analyze,
            ),
            ToolDefinition(
                name="clipboard_smart_paste",
                description=(
                    "Read the clipboard and return its content with suggested "
                    "contextual actions based on detected content type and "
                    "extracted entities."
                ),
                parameters=[],
                handler=clipboard_smart_paste,
            ),
        ],
    )
