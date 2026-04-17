"""Proactive routine scheduler — fires promoted routines on triggers."""

from __future__ import annotations
import asyncio, json, time, logging, datetime
from typing import Any
from pathlib import Path

logger = logging.getLogger("neuralclaw.adaptive.scheduler")

class RoutineScheduler:
    """Connects promoted routines to the execution pipeline.

    Polls the control plane for promoted routines, checks trigger conditions,
    and fires actions through the task pipeline when conditions are met.
    Respects autonomy classes: only auto-runs routines whose autonomy_class
    allows it, otherwise generates suggestions.
    """

    POLL_INTERVAL = 60  # seconds between checks
    MAX_AUTO_RUNS_PER_CYCLE = 3

    def __init__(self, *, control_plane: Any, task_sender: Any = None, bus: Any = None) -> None:
        self._control_plane = control_plane
        self._task_sender = task_sender  # callable: async (task_text, metadata) -> result
        self._bus = bus
        self._running = False
        self._poll_task: asyncio.Task[None] | None = None
        self._last_run_map: dict[str, float] = {}  # routine_id -> last execution timestamp
        self._event_markers: dict[str, float] = {}

    async def start(self) -> None:
        """Start the scheduler polling loop."""
        if self._running:
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("RoutineScheduler started")

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        logger.info("RoutineScheduler stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._check_and_fire()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("RoutineScheduler poll error: %s", e)
            await asyncio.sleep(self.POLL_INTERVAL)

    async def _check_and_fire(self) -> None:
        """Check promoted routines and fire eligible ones."""
        routines = await self._control_plane.list_routines(status="promoted")
        now = time.time()
        fired = 0

        for routine in routines:
            if fired >= self.MAX_AUTO_RUNS_PER_CYCLE:
                break

            routine_id = routine.get("routine_id", "")
            autonomy_class = routine.get("autonomy_class", "suggest-first")
            trigger_pattern = routine.get("trigger_pattern", "")
            last_run = routine.get("last_run_at") or self._last_run_map.get(routine_id, 0)

            # Don't re-fire within 5 minutes
            if now - last_run < 300:
                continue

            # Check trigger conditions
            triggered = await self._check_trigger(trigger_pattern, routine)
            if not triggered:
                continue

            if autonomy_class in ("auto-run-low-risk", "policy-driven-autonomous"):
                # Auto-execute
                if routine.get("risk_level", "low") == "low" or autonomy_class == "policy-driven-autonomous":
                    await self._execute_routine(routine)
                    fired += 1
                    self._last_run_map[routine_id] = now
                else:
                    # Higher risk — generate suggestion instead
                    await self._suggest_routine(routine)
            elif autonomy_class == "suggest-first":
                await self._suggest_routine(routine)
            # observe-only: do nothing

    async def _check_trigger(self, trigger_pattern: str, routine: dict) -> bool:
        """Check if a routine's trigger condition is met."""
        if not trigger_pattern:
            return False

        trigger = trigger_pattern.lower().strip()
        now = time.time()

        # Time-based triggers: "every_morning", "daily", "hourly", "weekday_start"
        dt = datetime.datetime.fromtimestamp(now)
        last_run = routine.get("last_run_at") or self._last_run_map.get(routine.get("routine_id", ""), 0)
        elapsed = now - last_run if last_run else float("inf")

        if "hourly" in trigger and elapsed >= 3600:
            return True
        if "daily" in trigger and elapsed >= 86400:
            return True
        if "every_morning" in trigger and 7 <= dt.hour <= 9 and elapsed >= 86400:
            return True
        if "weekday_start" in trigger and dt.weekday() < 5 and 8 <= dt.hour <= 10 and elapsed >= 86400:
            return True
        if "weekly" in trigger and elapsed >= 604800:
            return True

        # Event-based triggers: "on_task_failure", "on_approval_pending", "on_project_switch"
        # These would be checked via bus events — for now they're stub-matchable
        if "on_" in trigger:
            marker = self._event_markers.get(trigger)
            return bool(marker and now - marker <= 300)

        return False

    async def observe_event(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        event_key = str(event_name or "").strip().lower()
        if not event_key:
            return
        self._event_markers[event_key] = time.time()
        if self._bus:
            try:
                await self._bus.publish("routine.event_observed", {
                    "event_name": event_key,
                    "payload": payload or {},
                }, source="adaptive.scheduler")
            except Exception:
                pass

    async def _execute_routine(self, routine: dict) -> None:
        """Execute a routine through the task pipeline."""
        routine_id = routine.get("routine_id", "")
        action_template = routine.get("action_template", "")

        if not action_template:
            return

        logger.info("Auto-executing routine %s: %s", routine_id, routine.get("title", ""))

        success = True
        try:
            if self._task_sender:
                await self._task_sender(action_template, {
                    "proactive_origin": routine_id,
                    "autonomy_mode": routine.get("autonomy_class", "auto-run-low-risk"),
                    "routine_title": routine.get("title", ""),
                })
        except Exception as e:
            logger.error("Routine execution failed for %s: %s", routine_id, e)
            success = False

        # Record outcome
        try:
            await self._control_plane.record_routine_outcome(routine_id, success)
        except Exception:
            pass

        if self._bus:
            try:
                await self._bus.publish("routine.executed", {
                    "routine_id": routine_id,
                    "title": routine.get("title", ""),
                    "success": success,
                }, source="adaptive.scheduler")
            except Exception:
                pass

    async def _suggest_routine(self, routine: dict) -> None:
        """Generate a suggestion for a routine instead of auto-executing."""
        if self._bus:
            try:
                await self._bus.publish("routine.suggested", {
                    "routine_id": routine.get("routine_id", ""),
                    "title": routine.get("title", ""),
                    "action_template": routine.get("action_template", ""),
                    "trigger_pattern": routine.get("trigger_pattern", ""),
                }, source="adaptive.scheduler")
            except Exception:
                pass

    async def force_run(self, routine_id: str) -> dict:
        """Manually trigger a routine regardless of schedule."""
        routines = await self._control_plane.list_routines()
        routine = next((r for r in routines if r.get("routine_id") == routine_id), None)
        if not routine:
            return {"ok": False, "error": f"Routine {routine_id} not found"}

        await self._execute_routine(routine)
        self._last_run_map[routine_id] = time.time()
        return {"ok": True, "routine_id": routine_id, "status": "executed"}
