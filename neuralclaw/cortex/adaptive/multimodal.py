"""Multimodal input routing -- STT, screenshot-to-action, recording replay via adaptive plane."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import aiosqlite

_VALID_INPUT_TYPES = {"voice", "screenshot", "recording", "diagram"}
_VALID_STATUSES = {"received", "processing", "routed", "completed", "failed"}


def _new_id(prefix: str = "mm") -> str:
    raw = f"{prefix}-{time.time_ns()}"
    return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


class MultimodalRouter:
    """Routes multimodal inputs (voice, screenshots, recordings, diagrams)
    through the adaptive plane to create actionable tasks.

    Each input is persisted, transcribed/interpreted, and optionally
    published to the NeuralBus for downstream processing.
    """

    def __init__(
        self,
        db_path: str | Path,
        bus: Any = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._bus = bus
        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create multimodal_inputs table."""
        if self._initialized:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS multimodal_inputs (
                    input_id          TEXT PRIMARY KEY,
                    input_type        TEXT NOT NULL,
                    source_path       TEXT,
                    transcription     TEXT,
                    extracted_action  TEXT,
                    task_id           TEXT,
                    receipt_id        TEXT,
                    status            TEXT NOT NULL DEFAULT 'received',
                    metadata_json     TEXT,
                    created_at        REAL NOT NULL,
                    updated_at        REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_mm_type   ON multimodal_inputs(input_type);
                CREATE INDEX IF NOT EXISTS idx_mm_status ON multimodal_inputs(status);
                CREATE INDEX IF NOT EXISTS idx_mm_task   ON multimodal_inputs(task_id);
                """
            )
        self._initialized = True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _insert_input(
        self,
        input_type: str,
        source_path: str | None,
        transcription: str | None,
        extracted_action: str | None,
        metadata: dict | None,
        status: str = "received",
    ) -> dict[str, Any]:
        """Insert a new multimodal input record and return its dict."""
        input_id = _new_id("mm")
        now = time.time()

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO multimodal_inputs
                    (input_id, input_type, source_path, transcription,
                     extracted_action, status, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    input_id,
                    input_type,
                    source_path,
                    transcription,
                    extracted_action,
                    status,
                    json.dumps(metadata or {}, default=str),
                    now,
                    now,
                ),
            )
            await db.commit()

        record = {
            "input_id": input_id,
            "input_type": input_type,
            "source_path": source_path,
            "transcription": transcription,
            "extracted_action": extracted_action,
            "task_id": None,
            "receipt_id": None,
            "status": status,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }
        return record

    async def _update_status(
        self,
        input_id: str,
        status: str,
        *,
        task_id: str | None = None,
        receipt_id: str | None = None,
        extracted_action: str | None = None,
    ) -> None:
        """Update the status (and optionally task/receipt linkage) of an input."""
        now = time.time()
        sets = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, now]
        if task_id is not None:
            sets.append("task_id = ?")
            params.append(task_id)
        if receipt_id is not None:
            sets.append("receipt_id = ?")
            params.append(receipt_id)
        if extracted_action is not None:
            sets.append("extracted_action = ?")
            params.append(extracted_action)
        params.append(input_id)

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                f"UPDATE multimodal_inputs SET {', '.join(sets)} WHERE input_id = ?",
                params,
            )
            await db.commit()

    async def _publish_to_bus(self, event_type: str, payload: dict) -> None:
        """Publish an event to the NeuralBus if available."""
        if self._bus is not None:
            try:
                await self._bus.publish(event_type, payload, source="adaptive.multimodal")
            except Exception:
                pass  # best-effort

    # ------------------------------------------------------------------
    # Public routing API
    # ------------------------------------------------------------------

    async def route_voice_input(
        self,
        audio_path: str | None = None,
        transcription: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Route voice/STT input to create a task through the normal pipeline.

        Either ``audio_path`` (for server-side STT) or ``transcription``
        (pre-transcribed) must be provided.
        """
        await self.initialize()
        if not audio_path and not transcription:
            return {"ok": False, "error": "Either audio_path or transcription is required"}

        record = await self._insert_input(
            input_type="voice",
            source_path=audio_path,
            transcription=transcription,
            extracted_action=transcription,  # voice input IS the action
            metadata=metadata,
            status="processing" if audio_path and not transcription else "routed",
        )

        await self._publish_to_bus(
            "multimodal.voice_received",
            {
                "input_id": record["input_id"],
                "has_audio": audio_path is not None,
                "has_transcription": transcription is not None,
            },
        )

        return {"ok": True, **record}

    async def route_screenshot(
        self,
        image_path: str | None = None,
        image_b64: str | None = None,
        description: str = "",
        metadata: dict | None = None,
    ) -> dict:
        """Route screenshot to extract actions and create a task.

        The screenshot is persisted; action extraction happens downstream
        (via vision model or manual review).
        """
        await self.initialize()
        if not image_path and not image_b64:
            return {"ok": False, "error": "Either image_path or image_b64 is required"}

        source = image_path
        if not source and image_b64:
            # Store base64 reference in metadata
            meta = dict(metadata or {})
            meta["image_b64_hash"] = hashlib.sha256(image_b64.encode()[:1024]).hexdigest()[:16]
            metadata = meta

        record = await self._insert_input(
            input_type="screenshot",
            source_path=source,
            transcription=description or None,
            extracted_action=None,  # to be filled by vision model
            metadata=metadata,
            status="processing",
        )

        await self._publish_to_bus(
            "multimodal.screenshot_received",
            {
                "input_id": record["input_id"],
                "has_image_path": image_path is not None,
                "has_b64": image_b64 is not None,
                "description": description[:200],
            },
        )

        return {"ok": True, **record}

    async def route_recording(
        self,
        recording_path: str,
        metadata: dict | None = None,
    ) -> dict:
        """Route screen recording for replay analysis and automation
        candidate extraction.

        The recording path is persisted; frame-by-frame analysis and
        action extraction happen downstream.
        """
        await self.initialize()
        if not recording_path:
            return {"ok": False, "error": "recording_path is required"}

        record = await self._insert_input(
            input_type="recording",
            source_path=recording_path,
            transcription=None,
            extracted_action=None,  # extracted during analysis
            metadata=metadata,
            status="processing",
        )

        await self._publish_to_bus(
            "multimodal.recording_received",
            {
                "input_id": record["input_id"],
                "recording_path": recording_path,
            },
        )

        return {"ok": True, **record}

    async def route_diagram(
        self,
        diagram_path: str | None = None,
        diagram_b64: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Route diagram for interpretation into workflow/code/plan.

        Diagrams (flowcharts, architecture diagrams, wireframes) are
        processed by a vision model to extract structured representations.
        """
        await self.initialize()
        if not diagram_path and not diagram_b64:
            return {"ok": False, "error": "Either diagram_path or diagram_b64 is required"}

        source = diagram_path
        if not source and diagram_b64:
            meta = dict(metadata or {})
            meta["diagram_b64_hash"] = hashlib.sha256(diagram_b64.encode()[:1024]).hexdigest()[:16]
            metadata = meta

        record = await self._insert_input(
            input_type="diagram",
            source_path=source,
            transcription=None,
            extracted_action=None,
            metadata=metadata,
            status="processing",
        )

        await self._publish_to_bus(
            "multimodal.diagram_received",
            {
                "input_id": record["input_id"],
                "has_diagram_path": diagram_path is not None,
                "has_b64": diagram_b64 is not None,
            },
        )

        return {"ok": True, **record}

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    async def list_inputs(
        self,
        input_type: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List multimodal inputs, optionally filtered by type."""
        await self.initialize()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            if input_type:
                cur = await db.execute(
                    "SELECT * FROM multimodal_inputs WHERE input_type = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (input_type, limit),
                )
            else:
                cur = await db.execute(
                    "SELECT * FROM multimodal_inputs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            rows = await cur.fetchall()

        return [
            {
                "input_id": r["input_id"],
                "input_type": r["input_type"],
                "source_path": r["source_path"],
                "transcription": r["transcription"],
                "extracted_action": r["extracted_action"],
                "task_id": r["task_id"],
                "receipt_id": r["receipt_id"],
                "status": r["status"],
                "metadata": json.loads(r["metadata_json"]) if r["metadata_json"] else {},
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    async def get_input(self, input_id: str) -> dict | None:
        """Get a single input record."""
        await self.initialize()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM multimodal_inputs WHERE input_id = ?",
                (input_id,),
            )
            row = await cur.fetchone()
            if not row:
                return None

        return {
            "input_id": row["input_id"],
            "input_type": row["input_type"],
            "source_path": row["source_path"],
            "transcription": row["transcription"],
            "extracted_action": row["extracted_action"],
            "task_id": row["task_id"],
            "receipt_id": row["receipt_id"],
            "status": row["status"],
            "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
