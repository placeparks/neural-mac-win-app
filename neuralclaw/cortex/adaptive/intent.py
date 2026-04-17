"""Intent prediction — pattern-based prediction of user's next action."""

from __future__ import annotations
import json, time, hashlib, re, datetime
from collections import Counter, defaultdict
from typing import Any
from pathlib import Path
import aiosqlite

class IntentPredictor:
    """Predicts likely next actions based on temporal patterns, task sequences,
    project state, and integration events."""

    CONFIDENCE_THRESHOLD = 0.4
    MIN_PATTERN_OCCURRENCES = 2

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS intent_observations (
                    obs_id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    action_detail TEXT NOT NULL,
                    context_json TEXT,
                    hour_of_day INTEGER,
                    day_of_week INTEGER,
                    project_id TEXT,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_io_action ON intent_observations(action_type);
                CREATE INDEX IF NOT EXISTS idx_io_project ON intent_observations(project_id);
                CREATE INDEX IF NOT EXISTS idx_io_time ON intent_observations(created_at);

                CREATE TABLE IF NOT EXISTS intent_predictions (
                    prediction_id TEXT PRIMARY KEY,
                    predicted_action TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reasoning TEXT NOT NULL,
                    pattern_type TEXT NOT NULL,
                    context_json TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    resolved_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_ip_status ON intent_predictions(status);
            """)
        self._initialized = True

    async def observe(self, action_type: str, action_detail: str,
                       context: dict | None = None, project_id: str = "") -> None:
        """Record an observed user action for pattern building."""
        await self.initialize()
        now = time.time()
        dt = datetime.datetime.fromtimestamp(now)
        obs_id = f"obs-{hashlib.sha256(f'{action_type}:{now}'.encode()).hexdigest()[:12]}"
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                INSERT INTO intent_observations
                    (obs_id, action_type, action_detail, context_json, hour_of_day, day_of_week, project_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (obs_id, action_type, action_detail[:500], json.dumps(context or {}),
                  dt.hour, dt.weekday(), project_id, now))
            await db.commit()

    async def predict(self, *, project_id: str = "", current_hour: int | None = None,
                       current_day: int | None = None, recent_actions: list[str] | None = None,
                       limit: int = 5) -> list[dict]:
        """Generate predictions based on observed patterns."""
        await self.initialize()
        now = time.time()
        dt = datetime.datetime.fromtimestamp(now)
        hour = current_hour if current_hour is not None else dt.hour
        day = current_day if current_day is not None else dt.weekday()

        predictions: list[dict] = []

        # Pattern 1: Time-based patterns (what does user usually do at this hour/day?)
        time_preds = await self._predict_temporal(hour, day)
        predictions.extend(time_preds)

        # Pattern 2: Sequential patterns (what usually follows the recent actions?)
        if recent_actions:
            seq_preds = await self._predict_sequential(recent_actions)
            predictions.extend(seq_preds)

        # Pattern 3: Project-based patterns (what's common in this project context?)
        if project_id:
            proj_preds = await self._predict_project(project_id)
            predictions.extend(proj_preds)

        # Deduplicate by action, keeping highest confidence
        seen: dict[str, dict] = {}
        for pred in predictions:
            key = pred["predicted_action"]
            if key not in seen or pred["confidence"] > seen[key]["confidence"]:
                seen[key] = pred

        # Sort by confidence descending
        result = sorted(seen.values(), key=lambda p: p["confidence"], reverse=True)
        result = [p for p in result if p["confidence"] >= self.CONFIDENCE_THRESHOLD][:limit]

        # Persist predictions
        for pred in result:
            action_key = pred["predicted_action"]
            pred_id = f"pred-{hashlib.sha256(f'{action_key}:{now}'.encode()).hexdigest()[:12]}"
            pred["prediction_id"] = pred_id
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO intent_predictions
                        (prediction_id, predicted_action, confidence, reasoning, pattern_type, context_json, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """, (pred_id, pred["predicted_action"], pred["confidence"], pred["reasoning"],
                      pred["pattern_type"], json.dumps(pred.get("context", {})), now))
                await db.commit()

        return result

    async def _predict_temporal(self, hour: int, day: int) -> list[dict]:
        """Find actions that commonly occur at this time."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            # Look at actions in the same hour window (+-1) and same day
            cur = await db.execute("""
                SELECT action_type, action_detail, COUNT(*) as cnt
                FROM intent_observations
                WHERE hour_of_day BETWEEN ? AND ? AND day_of_week = ?
                GROUP BY action_type, action_detail
                HAVING cnt >= ?
                ORDER BY cnt DESC
                LIMIT 5
            """, (max(0, hour - 1), min(23, hour + 1), day, self.MIN_PATTERN_OCCURRENCES))
            rows = await cur.fetchall()

            # Get total observations to compute confidence
            cur2 = await db.execute("SELECT COUNT(*) FROM intent_observations")
            total = (await cur2.fetchone())[0] or 1

        predictions: list[dict] = []
        for row in rows:
            count = row["cnt"]
            confidence = min(0.9, 0.3 + (count / max(total, 1)) * 5)
            predictions.append({
                "predicted_action": f"{row['action_type']}: {row['action_detail'][:100]}",
                "confidence": round(confidence, 2),
                "reasoning": f"You've done this {count} times at this time of day on this weekday",
                "pattern_type": "temporal",
                "context": {"hour": hour, "day": day, "occurrences": count},
            })
        return predictions

    async def _predict_sequential(self, recent_actions: list[str]) -> list[dict]:
        """Find actions that typically follow the recent action sequence."""
        if not recent_actions:
            return []
        last_action = recent_actions[-1]
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            # Find observations that occurred shortly after the same action type
            cur = await db.execute("""
                SELECT b.action_type, b.action_detail, COUNT(*) as cnt
                FROM intent_observations a
                JOIN intent_observations b ON b.created_at > a.created_at
                    AND b.created_at < a.created_at + 300
                    AND b.obs_id != a.obs_id
                WHERE a.action_type = ?
                GROUP BY b.action_type, b.action_detail
                HAVING cnt >= ?
                ORDER BY cnt DESC
                LIMIT 5
            """, (last_action.split(":")[0].strip() if ":" in last_action else last_action,
                  self.MIN_PATTERN_OCCURRENCES))
            rows = await cur.fetchall()

        predictions: list[dict] = []
        for row in rows:
            count = row["cnt"]
            confidence = min(0.85, 0.35 + count * 0.1)
            predictions.append({
                "predicted_action": f"{row['action_type']}: {row['action_detail'][:100]}",
                "confidence": round(confidence, 2),
                "reasoning": f"After '{last_action[:50]}', you usually do this ({count} times observed)",
                "pattern_type": "sequential",
                "context": {"preceded_by": last_action, "occurrences": count},
            })
        return predictions

    async def _predict_project(self, project_id: str) -> list[dict]:
        """Find common actions for this project."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("""
                SELECT action_type, action_detail, COUNT(*) as cnt
                FROM intent_observations
                WHERE project_id = ?
                GROUP BY action_type, action_detail
                HAVING cnt >= ?
                ORDER BY cnt DESC
                LIMIT 5
            """, (project_id, self.MIN_PATTERN_OCCURRENCES))
            rows = await cur.fetchall()

        predictions: list[dict] = []
        for row in rows:
            count = row["cnt"]
            confidence = min(0.8, 0.3 + count * 0.08)
            predictions.append({
                "predicted_action": f"{row['action_type']}: {row['action_detail'][:100]}",
                "confidence": round(confidence, 2),
                "reasoning": f"Common action in this project ({count} times)",
                "pattern_type": "project",
                "context": {"project_id": project_id, "occurrences": count},
            })
        return predictions

    async def resolve_prediction(self, prediction_id: str, matched: bool) -> None:
        """Mark a prediction as matched or missed (for feedback loop)."""
        await self.initialize()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                UPDATE intent_predictions SET status = ?, resolved_at = ? WHERE prediction_id = ?
            """, ("matched" if matched else "missed", time.time(), prediction_id))
            await db.commit()

    async def get_accuracy_stats(self) -> dict:
        """Get prediction accuracy statistics."""
        await self.initialize()
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute("""
                SELECT status, COUNT(*) as cnt FROM intent_predictions GROUP BY status
            """)
            rows = await cur.fetchall()
        stats = {row[0]: row[1] for row in rows}
        total_resolved = stats.get("matched", 0) + stats.get("missed", 0)
        return {
            "total_predictions": sum(stats.values()),
            "matched": stats.get("matched", 0),
            "missed": stats.get("missed", 0),
            "pending": stats.get("pending", 0),
            "accuracy": round(stats.get("matched", 0) / max(total_resolved, 1), 2),
        }
