"""Teaching artifact processor -- converts teaching transcripts into reusable templates and skill candidates."""

from __future__ import annotations

import hashlib
import json
import textwrap
import time
from pathlib import Path
from typing import Any

import aiosqlite


def _new_id(prefix: str = "ta") -> str:
    """Generate a short, unique artifact ID."""
    raw = f"{prefix}-{time.time_ns()}"
    return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


class TeachingProcessor:
    """Converts teaching-mode transcripts into reusable workflow templates
    and skill candidates that can be promoted into the skill registry."""

    def __init__(
        self,
        db_path: str | Path,
        skills_dir: str | Path | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._skills_dir = (
            Path(skills_dir) if skills_dir else Path.cwd() / ".neuralclaw" / "skills"
        )
        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create tables if needed."""
        if self._initialized:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS teaching_artifacts (
                    artifact_id       TEXT PRIMARY KEY,
                    task_id           TEXT,
                    transcript_json   TEXT NOT NULL,
                    template_json     TEXT,
                    skill_candidate_path TEXT,
                    promotion_status  TEXT NOT NULL DEFAULT 'draft',
                    tags_json         TEXT,
                    created_at        REAL NOT NULL,
                    updated_at        REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ta_status ON teaching_artifacts(promotion_status);
                CREATE INDEX IF NOT EXISTS idx_ta_task   ON teaching_artifacts(task_id);
                """
            )
        self._initialized = True

    # ------------------------------------------------------------------
    # Template extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_template(transcript: list[dict]) -> dict[str, Any]:
        """Auto-extract a reusable template from transcript steps.

        A transcript is a list of dicts, each with at least a ``role``
        (``user`` or ``assistant``) and ``content`` key.  The template
        captures the step sequence, action verbs, and placeholders.
        """
        steps: list[dict[str, Any]] = []
        for idx, turn in enumerate(transcript):
            role = turn.get("role", "unknown")
            content = str(turn.get("content", ""))
            action = turn.get("action")  # optional structured action tag
            step: dict[str, Any] = {
                "index": idx,
                "role": role,
                "summary": content[:200],
            }
            if action:
                step["action"] = action
            # Look for tool calls embedded in the transcript
            if "tool_call" in turn:
                step["tool_call"] = turn["tool_call"]
            steps.append(step)

        return {
            "step_count": len(steps),
            "steps": steps,
            "extracted_at": time.time(),
        }

    @staticmethod
    def _generate_skill_code(
        skill_name: str,
        template: dict[str, Any],
        description: str = "",
    ) -> str:
        """Generate a Python skill stub from a teaching template."""
        safe_name = skill_name.replace("-", "_").replace(" ", "_")
        steps_comment = "\n".join(
            f"    #   {s['index']+1}. [{s['role']}] {s['summary'][:60]}"
            for s in template.get("steps", [])
        )
        return textwrap.dedent(f'''\
            """Auto-generated skill: {safe_name}

            {description or "Generated from a teaching artifact."}
            """

            from __future__ import annotations
            from typing import Any
            from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter


            MANIFEST = SkillManifest(
                name="{safe_name}",
                description="""{description or f"Skill generated from teaching artifact ({template.get('step_count', 0)} steps)."}""",
                version="0.1.0",
                author="teaching-processor",
                tools=[
                    ToolDefinition(
                        name="{safe_name}_run",
                        description="Execute the learned workflow.",
                        parameters=[
                            ToolParameter(
                                name="input_text",
                                type="string",
                                description="The input to process through this workflow.",
                            ),
                        ],
                        handler=run,
                    ),
                ],
            )

            # Workflow steps extracted from teaching transcript:
            {steps_comment}


            async def run(input_text: str = "", **kwargs: Any) -> dict[str, Any]:
                """Execute the learned workflow."""
                results: list[dict[str, Any]] = []
                # TODO: implement step execution logic
                return {{
                    "ok": True,
                    "skill": "{safe_name}",
                    "input": input_text,
                    "steps_executed": {template.get("step_count", 0)},
                    "results": results,
                }}
        ''')

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def capture_artifact(
        self,
        task_id: str,
        transcript: list[dict],
        tags: list[str] | None = None,
    ) -> str:
        """Capture a teaching session transcript as an artifact. Returns artifact_id."""
        await self.initialize()
        artifact_id = _new_id("ta")
        now = time.time()
        template = self._extract_template(transcript)

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO teaching_artifacts
                    (artifact_id, task_id, transcript_json, template_json,
                     promotion_status, tags_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)
                """,
                (
                    artifact_id,
                    task_id,
                    json.dumps(transcript, default=str),
                    json.dumps(template, default=str),
                    json.dumps(tags or []),
                    now,
                    now,
                ),
            )
            await db.commit()
        return artifact_id

    async def promote_to_template(self, artifact_id: str) -> dict:
        """Convert artifact into a reusable workflow template."""
        await self.initialize()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM teaching_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            )
            row = await cur.fetchone()
            if not row:
                return {"ok": False, "error": f"Artifact {artifact_id} not found"}

            transcript = json.loads(row["transcript_json"])
            template = self._extract_template(transcript)
            now = time.time()

            await db.execute(
                """
                UPDATE teaching_artifacts
                SET template_json = ?, promotion_status = 'template', updated_at = ?
                WHERE artifact_id = ?
                """,
                (json.dumps(template, default=str), now, artifact_id),
            )
            await db.commit()

        return {
            "ok": True,
            "artifact_id": artifact_id,
            "status": "template",
            "template": template,
        }

    async def promote_to_skill(self, artifact_id: str, skill_name: str) -> dict:
        """Generate a skill candidate from the teaching artifact."""
        await self.initialize()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM teaching_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            )
            row = await cur.fetchone()
            if not row:
                return {"ok": False, "error": f"Artifact {artifact_id} not found"}

            template_raw = row["template_json"]
            if not template_raw:
                # Auto-extract first
                transcript = json.loads(row["transcript_json"])
                template = self._extract_template(transcript)
            else:
                template = json.loads(template_raw)

            tags = json.loads(row["tags_json"]) if row["tags_json"] else []
            description = f"Skill from teaching artifact. Tags: {', '.join(tags)}" if tags else ""
            code = self._generate_skill_code(skill_name, template, description)

            safe_name = skill_name.replace("-", "_").replace(" ", "_")
            skill_path = self._skills_dir / f"{safe_name}.py"
            skill_path.write_text(code, encoding="utf-8")

            now = time.time()
            await db.execute(
                """
                UPDATE teaching_artifacts
                SET skill_candidate_path = ?, promotion_status = 'skill_candidate', updated_at = ?
                WHERE artifact_id = ?
                """,
                (str(skill_path), now, artifact_id),
            )
            await db.commit()

        return {
            "ok": True,
            "artifact_id": artifact_id,
            "status": "skill_candidate",
            "skill_name": safe_name,
            "skill_path": str(skill_path),
        }

    async def list_artifacts(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List teaching artifacts, optionally filtered by promotion status."""
        await self.initialize()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            if status:
                cur = await db.execute(
                    "SELECT * FROM teaching_artifacts WHERE promotion_status = ? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (status, limit),
                )
            else:
                cur = await db.execute(
                    "SELECT * FROM teaching_artifacts ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                )
            rows = await cur.fetchall()

        return [
            {
                "artifact_id": r["artifact_id"],
                "task_id": r["task_id"],
                "promotion_status": r["promotion_status"],
                "tags": json.loads(r["tags_json"]) if r["tags_json"] else [],
                "skill_candidate_path": r["skill_candidate_path"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    async def get_artifact(self, artifact_id: str) -> dict | None:
        """Get a single artifact with full details."""
        await self.initialize()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM teaching_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            )
            row = await cur.fetchone()
            if not row:
                return None

        return {
            "artifact_id": row["artifact_id"],
            "task_id": row["task_id"],
            "transcript": json.loads(row["transcript_json"]),
            "template": json.loads(row["template_json"]) if row["template_json"] else None,
            "skill_candidate_path": row["skill_candidate_path"],
            "promotion_status": row["promotion_status"],
            "tags": json.loads(row["tags_json"]) if row["tags_json"] else [],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
