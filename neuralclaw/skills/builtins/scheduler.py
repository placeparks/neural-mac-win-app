"""
Built-in Skill: Scheduler — Cron-based task scheduling and webhook ingestion.

Provides cron-based scheduled task execution and webhook endpoint registration
for the NeuralClaw agent framework. Schedules are stored in a module-level
registry and evaluated by an asyncio background loop every 30 seconds.

Webhook handlers can optionally verify inbound payloads with HMAC-SHA256.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Coroutine

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ScheduledTask:
    """A cron-scheduled task stored in the in-memory registry."""

    name: str
    cron_expression: str
    action_type: str  # "workflow" | "message" | "skill_call"
    action_payload: str  # JSON string
    enabled: bool = True
    last_run: datetime | None = None
    next_run: datetime | None = None
    run_count: int = 0


@dataclass
class WebhookHandler:
    """A registered webhook endpoint."""

    name: str
    path: str  # URL path, e.g. "/hooks/stripe"
    action_type: str  # "workflow" | "message" | "skill_call"
    action_payload_template: str  # JSON template with {{body}} placeholder
    secret: str | None = None  # HMAC-SHA256 secret


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_schedules: dict[str, ScheduledTask] = {}
_webhooks: dict[str, WebhookHandler] = {}

# Background asyncio task handle
_scheduler_task: asyncio.Task[None] | None = None

# Callback set by the gateway to execute actions
_action_callback: Callable[
    [str, str, str], Coroutine[Any, Any, dict[str, Any]]
] | None = None
# Signature: (action_type, action_payload_json, source_label) -> result dict


# ---------------------------------------------------------------------------
# Cron parsing
# ---------------------------------------------------------------------------


def _parse_cron_field(field_str: str, min_val: int, max_val: int) -> set[int]:
    """
    Parse a single cron field into a set of matching integer values.

    Supports:
      *        — all values in [min_val, max_val]
      N        — literal value
      N-M      — inclusive range
      */S      — every S values starting from min_val
      N-M/S    — every S values within the range N..M
      N,M,O    — comma-separated list (each element can be any of the above)
    """
    result: set[int] = set()

    for part in field_str.split(","):
        part = part.strip()
        if not part:
            continue

        # Handle step: either */S or N-M/S
        step = 1
        if "/" in part:
            range_part, step_str = part.split("/", 1)
            step = int(step_str)
        else:
            range_part = part

        # Determine the range
        if range_part == "*":
            start, end = min_val, max_val
        elif "-" in range_part:
            lo, hi = range_part.split("-", 1)
            start, end = int(lo), int(hi)
        else:
            # Single value (possibly with a step, which is unusual but valid)
            val = int(range_part)
            if step == 1:
                result.add(val)
                continue
            # e.g. "5/10" — start at 5, step 10, up to max_val
            start, end = val, max_val

        for v in range(start, end + 1, step):
            if min_val <= v <= max_val:
                result.add(v)

    return result


def _cron_matches(expression: str, dt: datetime) -> bool:
    """
    Return True if *expression* matches the given datetime.

    Standard 5-field cron: minute hour day_of_month month day_of_week
    day_of_week: 0 = Monday ... 6 = Sunday  (ISO weekday - 1).
    Also accepts 7 as Sunday for compatibility.
    """
    parts = expression.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Cron expression must have 5 fields, got {len(parts)}: {expression!r}")

    minutes = _parse_cron_field(parts[0], 0, 59)
    hours = _parse_cron_field(parts[1], 0, 23)
    days_of_month = _parse_cron_field(parts[2], 1, 31)
    months = _parse_cron_field(parts[3], 1, 12)
    days_of_week_raw = _parse_cron_field(parts[4], 0, 7)

    # Normalise: treat 7 as 0 (both mean Sunday).  We use 0=Mon..6=Sun internally
    # but cron traditionally uses 0=Sun. Convert: cron_dow -> python isoweekday-based.
    # Python: Monday=0 via dt.weekday(). Cron: 0 and 7 = Sunday, 1=Monday..6=Saturday.
    # So cron_val -> python_weekday: (cron_val - 1) % 7  when cron_val != 0 and != 7
    # cron 0 or 7 -> python weekday 6 (Sunday)
    python_days: set[int] = set()
    for d in days_of_week_raw:
        if d == 0 or d == 7:
            python_days.add(6)  # Sunday
        else:
            python_days.add(d - 1)  # cron 1 (Mon) -> python 0, etc.

    if dt.minute not in minutes:
        return False
    if dt.hour not in hours:
        return False
    if dt.day not in days_of_month:
        return False
    if dt.month not in months:
        return False
    if dt.weekday() not in python_days:
        return False

    return True


def _next_cron_run(expression: str, after_dt: datetime) -> datetime:
    """
    Compute the next datetime (minute-resolution) that matches *expression*,
    starting strictly after *after_dt*.

    Searches up to 366 days ahead; raises ValueError if no match is found.
    """
    # Start from the next whole minute
    candidate = after_dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = after_dt + timedelta(days=366)

    while candidate <= limit:
        if _cron_matches(expression, candidate):
            return candidate
        candidate += timedelta(minutes=1)

    raise ValueError(
        f"No matching time found within 366 days for cron expression: {expression!r}"
    )


# ---------------------------------------------------------------------------
# Background scheduler loop
# ---------------------------------------------------------------------------


async def _run_scheduler_loop() -> None:
    """Check every 30 seconds whether any schedule is due and fire it."""
    while True:
        try:
            now = datetime.now()
            for task in list(_schedules.values()):
                if not task.enabled:
                    continue
                if task.next_run is not None and now >= task.next_run:
                    await _execute_task(task)
                    task.last_run = now
                    task.run_count += 1
                    try:
                        task.next_run = _next_cron_run(task.cron_expression, now)
                    except ValueError:
                        task.enabled = False
                        logger.warning(
                            "Disabled schedule %r — no future match", task.name
                        )
        except Exception:
            logger.exception("Scheduler loop error")

        await asyncio.sleep(30)


async def _execute_task(task: ScheduledTask) -> None:
    """Dispatch a scheduled task via the action callback."""
    if _action_callback is not None:
        try:
            await _action_callback(
                task.action_type,
                task.action_payload,
                f"scheduler:{task.name}",
            )
        except Exception:
            logger.exception("Action callback failed for schedule %r", task.name)
    else:
        logger.warning(
            "No action callback registered — skipping execution of schedule %r",
            task.name,
        )


def _ensure_scheduler_running() -> None:
    """Start the background loop if it is not already running."""
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        loop = asyncio.get_event_loop()
        _scheduler_task = loop.create_task(_run_scheduler_loop())


# ---------------------------------------------------------------------------
# Gateway helpers
# ---------------------------------------------------------------------------


def set_action_callback(
    cb: Callable[[str, str, str], Coroutine[Any, Any, dict[str, Any]]],
) -> None:
    """Called by the gateway to register the action execution callback."""
    global _action_callback
    _action_callback = cb


def get_webhook_routes() -> dict[str, WebhookHandler]:
    """
    Return registered webhook handlers keyed by their URL path.

    The gateway uses this to mount aiohttp routes that forward inbound
    HTTP requests into the agent action pipeline.
    """
    return {wh.path: wh for wh in _webhooks.values()}


def verify_webhook_signature(
    secret: str,
    payload_bytes: bytes,
    signature_header: str,
) -> bool:
    """
    Verify an HMAC-SHA256 signature.

    *signature_header* is expected in the form ``sha256=<hex-digest>``.
    """
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        secret.encode(), payload_bytes, hashlib.sha256
    ).hexdigest()
    provided = signature_header[len("sha256="):]
    return hmac.compare_digest(expected, provided)


async def handle_webhook_request(
    handler: WebhookHandler,
    body: str,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Process an inbound webhook request.

    Verifies the HMAC signature (if a secret is configured), renders the
    payload template, and dispatches via the action callback.
    """
    headers = headers or {}

    # Signature verification
    if handler.secret:
        sig = headers.get("X-Signature-256") or headers.get("x-signature-256", "")
        if not verify_webhook_signature(handler.secret, body.encode(), sig):
            return {"error": "Invalid webhook signature", "status": 403}

    # Render the payload template
    rendered = handler.action_payload_template.replace("{{body}}", body)

    if _action_callback is not None:
        try:
            result = await _action_callback(
                handler.action_type,
                rendered,
                f"webhook:{handler.name}",
            )
            return {"ok": True, "result": result}
        except Exception as exc:
            logger.exception("Webhook action failed for %r", handler.name)
            return {"error": str(exc), "status": 500}

    return {"error": "No action callback registered", "status": 503}


# ---------------------------------------------------------------------------
# Tool handlers — Schedules
# ---------------------------------------------------------------------------


async def schedule_create(
    name: str,
    cron_expression: str,
    action_type: str,
    action_payload: str,
    enabled: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    """Create a new scheduled task and start the background loop."""
    if name in _schedules:
        return {"error": f"Schedule {name!r} already exists"}

    valid_types = ("workflow", "message", "skill_call")
    if action_type not in valid_types:
        return {"error": f"action_type must be one of {valid_types}"}

    # Validate cron expression
    try:
        now = datetime.now()
        next_run = _next_cron_run(cron_expression, now) if enabled else None
    except ValueError as exc:
        return {"error": f"Invalid cron expression: {exc}"}

    # Validate action_payload is valid JSON
    try:
        json.loads(action_payload)
    except json.JSONDecodeError as exc:
        return {"error": f"action_payload must be valid JSON: {exc}"}

    task = ScheduledTask(
        name=name,
        cron_expression=cron_expression,
        action_type=action_type,
        action_payload=action_payload,
        enabled=enabled,
        next_run=next_run,
    )
    _schedules[name] = task

    _ensure_scheduler_running()

    return {
        "created": True,
        "name": name,
        "cron_expression": cron_expression,
        "action_type": action_type,
        "enabled": enabled,
        "next_run": next_run.isoformat() if next_run else None,
    }


async def schedule_list(**kwargs: Any) -> dict[str, Any]:
    """List all scheduled tasks with their next run time."""
    items = []
    for t in _schedules.values():
        items.append({
            "name": t.name,
            "cron_expression": t.cron_expression,
            "action_type": t.action_type,
            "action_payload": t.action_payload,
            "enabled": t.enabled,
            "last_run": t.last_run.isoformat() if t.last_run else None,
            "next_run": t.next_run.isoformat() if t.next_run else None,
            "run_count": t.run_count,
        })
    return {"schedules": items, "count": len(items)}


async def schedule_remove(name: str, **kwargs: Any) -> dict[str, Any]:
    """Remove a scheduled task by name."""
    if name not in _schedules:
        return {"error": f"Schedule {name!r} not found"}
    del _schedules[name]
    return {"removed": True, "name": name}


async def schedule_pause(name: str, **kwargs: Any) -> dict[str, Any]:
    """Pause a scheduled task."""
    if name not in _schedules:
        return {"error": f"Schedule {name!r} not found"}
    _schedules[name].enabled = False
    return {"paused": True, "name": name}


async def schedule_resume(name: str, **kwargs: Any) -> dict[str, Any]:
    """Resume a paused scheduled task and recompute next run."""
    if name not in _schedules:
        return {"error": f"Schedule {name!r} not found"}
    task = _schedules[name]
    task.enabled = True
    try:
        task.next_run = _next_cron_run(task.cron_expression, datetime.now())
    except ValueError as exc:
        task.enabled = False
        return {"error": f"Cannot resume — no future match: {exc}"}

    _ensure_scheduler_running()

    return {
        "resumed": True,
        "name": name,
        "next_run": task.next_run.isoformat() if task.next_run else None,
    }


# ---------------------------------------------------------------------------
# Tool handlers — Webhooks
# ---------------------------------------------------------------------------


async def webhook_register(
    name: str,
    path: str,
    action_type: str,
    action_payload_template: str,
    secret: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Register a webhook handler."""
    if name in _webhooks:
        return {"error": f"Webhook {name!r} already exists"}

    valid_types = ("workflow", "message", "skill_call")
    if action_type not in valid_types:
        return {"error": f"action_type must be one of {valid_types}"}

    if not path.startswith("/"):
        return {"error": "path must start with /"}

    # Check for path collision
    existing_paths = {wh.path for wh in _webhooks.values()}
    if path in existing_paths:
        return {"error": f"Path {path!r} is already registered by another webhook"}

    handler = WebhookHandler(
        name=name,
        path=path,
        action_type=action_type,
        action_payload_template=action_payload_template,
        secret=secret,
    )
    _webhooks[name] = handler

    return {
        "registered": True,
        "name": name,
        "path": path,
        "action_type": action_type,
        "has_secret": secret is not None,
    }


async def webhook_list(**kwargs: Any) -> dict[str, Any]:
    """List all registered webhook endpoints."""
    items = []
    for wh in _webhooks.values():
        items.append({
            "name": wh.name,
            "path": wh.path,
            "action_type": wh.action_type,
            "action_payload_template": wh.action_payload_template,
            "has_secret": wh.secret is not None,
        })
    return {"webhooks": items, "count": len(items)}


async def webhook_remove(name: str, **kwargs: Any) -> dict[str, Any]:
    """Remove a webhook handler by name."""
    if name not in _webhooks:
        return {"error": f"Webhook {name!r} not found"}
    del _webhooks[name]
    return {"removed": True, "name": name}


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="scheduler",
        description="Cron-based task scheduling and webhook ingestion for automated agent actions",
        version="0.1.0",
        capabilities=[Capability.NETWORK_HTTP],
        tools=[
            # --- Schedules ---
            ToolDefinition(
                name="schedule_create",
                description=(
                    "Create a cron-based scheduled task. The task will fire "
                    "automatically on the cron schedule and dispatch the action "
                    "via the agent runtime."
                ),
                parameters=[
                    ToolParameter(
                        name="name",
                        type="string",
                        description="Unique name for the scheduled task",
                    ),
                    ToolParameter(
                        name="cron_expression",
                        type="string",
                        description=(
                            "Standard 5-field cron expression: minute hour day_of_month month day_of_week. "
                            'Examples: "0 9 * * 1-5" (weekdays 9am), "*/15 * * * *" (every 15 min), '
                            '"0 0 1 * *" (first of month midnight)'
                        ),
                    ),
                    ToolParameter(
                        name="action_type",
                        type="string",
                        description="Type of action to execute when the schedule fires",
                        enum=["workflow", "message", "skill_call"],
                    ),
                    ToolParameter(
                        name="action_payload",
                        type="string",
                        description=(
                            "JSON string with action details. For workflow: "
                            '{"workflow": "name"}. For message: {"text": "..."}. '
                            'For skill_call: {"skill": "name", "tool": "name", "args": {}}'
                        ),
                    ),
                    ToolParameter(
                        name="enabled",
                        type="boolean",
                        description="Whether the schedule starts enabled (default true)",
                        required=False,
                        default=True,
                    ),
                ],
                handler=schedule_create,
            ),
            ToolDefinition(
                name="schedule_list",
                description="List all scheduled tasks with their next run time and status",
                parameters=[],
                handler=schedule_list,
            ),
            ToolDefinition(
                name="schedule_remove",
                description="Remove a scheduled task by name",
                parameters=[
                    ToolParameter(
                        name="name",
                        type="string",
                        description="Name of the scheduled task to remove",
                    ),
                ],
                handler=schedule_remove,
            ),
            ToolDefinition(
                name="schedule_pause",
                description="Pause a scheduled task so it will not fire until resumed",
                parameters=[
                    ToolParameter(
                        name="name",
                        type="string",
                        description="Name of the scheduled task to pause",
                    ),
                ],
                handler=schedule_pause,
            ),
            ToolDefinition(
                name="schedule_resume",
                description="Resume a paused scheduled task and recompute its next run time",
                parameters=[
                    ToolParameter(
                        name="name",
                        type="string",
                        description="Name of the scheduled task to resume",
                    ),
                ],
                handler=schedule_resume,
            ),
            # --- Webhooks ---
            ToolDefinition(
                name="webhook_register",
                description=(
                    "Register a webhook endpoint that dispatches an action when "
                    "an HTTP request is received at the given path. Supports "
                    "optional HMAC-SHA256 signature verification."
                ),
                parameters=[
                    ToolParameter(
                        name="name",
                        type="string",
                        description="Unique name for the webhook handler",
                    ),
                    ToolParameter(
                        name="path",
                        type="string",
                        description='URL path to listen on, e.g. "/hooks/stripe" or "/hooks/github"',
                    ),
                    ToolParameter(
                        name="action_type",
                        type="string",
                        description="Type of action to execute when the webhook fires",
                        enum=["workflow", "message", "skill_call"],
                    ),
                    ToolParameter(
                        name="action_payload_template",
                        type="string",
                        description=(
                            "JSON template for the action payload. Use {{body}} as a "
                            "placeholder that will be replaced with the raw request body. "
                            'Example: {"text": "Webhook received: {{body}}"}'
                        ),
                    ),
                    ToolParameter(
                        name="secret",
                        type="string",
                        description=(
                            "Optional HMAC-SHA256 secret for verifying inbound requests. "
                            "The sender must include an X-Signature-256 header with "
                            "sha256=<hex-digest>."
                        ),
                        required=False,
                        default=None,
                    ),
                ],
                handler=webhook_register,
            ),
            ToolDefinition(
                name="webhook_list",
                description="List all registered webhook endpoints",
                parameters=[],
                handler=webhook_list,
            ),
            ToolDefinition(
                name="webhook_remove",
                description="Remove a registered webhook endpoint by name",
                parameters=[
                    ToolParameter(
                        name="name",
                        type="string",
                        description="Name of the webhook handler to remove",
                    ),
                ],
                handler=webhook_remove,
            ),
        ],
    )
