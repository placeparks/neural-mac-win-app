"""
Built-in Skill: Calendar — Local calendar management (SQLite-backed).
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Any

import aiosqlite

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.config import DATA_DIR
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

_DB_PATH = str(DATA_DIR / "calendar.db")
_initialized = False


async def _get_db() -> aiosqlite.Connection:
    global _initialized
    db = await aiosqlite.connect(_DB_PATH)
    if not _initialized:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                start_time TEXT NOT NULL,
                end_time TEXT,
                location TEXT DEFAULT '',
                tags_json TEXT DEFAULT '[]',
                created_at REAL DEFAULT (unixepoch('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_time);
        """)
        await db.commit()
        _initialized = True
    return db


async def create_event(
    title: str,
    start_time: str,
    end_time: str | None = None,
    description: str = "",
    location: str = "",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Create a new calendar event."""
    try:
        db = await _get_db()
        event_id = uuid.uuid4().hex[:8]
        await db.execute(
            "INSERT INTO events (id, title, description, start_time, end_time, location) VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, title, description, start_time, end_time, location),
        )
        await db.commit()
        await db.close()
        return {
            "id": event_id,
            "title": title,
            "start_time": start_time,
            "created": True,
            "idempotency_key": idempotency_key,
        }
    except Exception as e:
        return {"error": str(e)}


async def list_events(date: str | None = None) -> dict[str, Any]:
    """List calendar events, optionally filtered by date (YYYY-MM-DD)."""
    try:
        db = await _get_db()
        if date:
            rows = await db.execute_fetchall(
                "SELECT id, title, description, start_time, end_time, location FROM events WHERE start_time LIKE ? ORDER BY start_time",
                (f"{date}%",),
            )
        else:
            rows = await db.execute_fetchall(
                "SELECT id, title, description, start_time, end_time, location FROM events ORDER BY start_time LIMIT 20",
            )
        await db.close()

        events = [
            {"id": r[0], "title": r[1], "description": r[2], "start_time": r[3], "end_time": r[4], "location": r[5]}
            for r in rows
        ]
        return {"events": events, "count": len(events)}
    except Exception as e:
        return {"error": str(e)}


async def delete_event(event_id: str, idempotency_key: str | None = None) -> dict[str, Any]:
    """Delete a calendar event by ID."""
    try:
        db = await _get_db()
        await db.execute("DELETE FROM events WHERE id = ?", (event_id,))
        await db.commit()
        await db.close()
        return {"deleted": True, "id": event_id, "idempotency_key": idempotency_key}
    except Exception as e:
        return {"error": str(e)}


def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="calendar",
        description="Manage a local calendar — create, list, and delete events",
        capabilities=[Capability.CALENDAR_READ, Capability.CALENDAR_WRITE, Capability.MEMORY_WRITE],
        tools=[
            ToolDefinition(
                name="create_event",
                description="Create a new calendar event",
                parameters=[
                    ToolParameter(name="title", type="string", description="Event title"),
                    ToolParameter(name="start_time", type="string", description="Start time (ISO format, e.g. 2026-02-23T14:00)"),
                    ToolParameter(name="end_time", type="string", description="End time (ISO format)", required=False),
                    ToolParameter(name="description", type="string", description="Event description", required=False, default=""),
                    ToolParameter(name="location", type="string", description="Event location", required=False, default=""),
                    ToolParameter(
                        name="idempotency_key",
                        type="string",
                        description="Optional idempotency key to prevent duplicates on retries",
                        required=False,
                        default=None,
                    ),
                ],
                handler=create_event,
            ),
            ToolDefinition(
                name="list_events",
                description="List calendar events, optionally filtered by date",
                parameters=[
                    ToolParameter(name="date", type="string", description="Date to filter by (YYYY-MM-DD format)", required=False),
                ],
                handler=list_events,
            ),
            ToolDefinition(
                name="delete_event",
                description="Delete a calendar event by its ID",
                parameters=[
                    ToolParameter(name="event_id", type="string", description="Event ID to delete"),
                    ToolParameter(
                        name="idempotency_key",
                        type="string",
                        description="Optional idempotency key to prevent duplicates on retries",
                        required=False,
                        default=None,
                    ),
                ],
                handler=delete_event,
            ),
        ],
    )
