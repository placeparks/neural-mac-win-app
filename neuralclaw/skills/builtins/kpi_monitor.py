"""
Built-in Skill: KPI Monitor — Create and manage KPI monitoring agents that
watch metrics and alert when thresholds are breached.

Supports multiple check types:
  - http_status:      GET a URL, record the status code, alert if not 200
  - http_json_field:  GET a URL, extract a JSON field via dot-path, compare
                      against min/max thresholds
  - database_query:   Execute a query via the database_bi skill, record the
                      numeric result
  - file_metric:      Read a local file and extract a numeric value
  - custom_python:    Execute a Python snippet in a sandbox and record the result

Each monitor runs as an asyncio background task on a configurable interval.
Readings are stored in a per-monitor ring buffer (last 100 entries).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import re
import textwrap
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Deque

import aiohttp

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.skills.manifest import (
    SkillManifest,
    ToolDefinition,
    ToolParameter,
)

logger = logging.getLogger("neuralclaw.skills.kpi_monitor")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_HISTORY = 100
_DEFAULT_INTERVAL = 300  # seconds
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=15)
_USER_AGENT = (
    "Mozilla/5.0 (compatible; NeuralClaw-KPI/1.0; +https://github.com/neuralclaw)"
)

_VALID_CHECK_TYPES = frozenset({
    "http_status",
    "http_json_field",
    "database_query",
    "file_metric",
    "custom_python",
})

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

Reading = dict[str, Any]
"""A single KPI reading: {"timestamp", "value", "status", "message"}."""


@dataclass
class KPIMonitor:
    """A single KPI monitor definition and its runtime state."""

    name: str
    description: str
    check_type: str
    target: str  # URL, query, file path, or Python snippet
    field_path: str = ""  # dot-path for JSON extraction
    threshold_min: float | None = None
    threshold_max: float | None = None
    check_interval_seconds: int = _DEFAULT_INTERVAL
    alert_message_template: str = "KPI '{name}' is {status}: value={value}"

    # Runtime state (not serialisable)
    history: Deque[Reading] = field(default_factory=lambda: deque(maxlen=_MAX_HISTORY))
    _task: asyncio.Task[None] | None = field(default=None, repr=False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def last_reading(self) -> Reading | None:
        return self.history[-1] if self.history else None

    def to_dict(self) -> dict[str, Any]:
        """Serialise monitor metadata (no task handle)."""
        return {
            "name": self.name,
            "description": self.description,
            "check_type": self.check_type,
            "target": self.target,
            "field_path": self.field_path,
            "threshold_min": self.threshold_min,
            "threshold_max": self.threshold_max,
            "check_interval_seconds": self.check_interval_seconds,
            "alert_message_template": self.alert_message_template,
            "last_reading": self.last_reading,
            "history_length": len(self.history),
        }


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_monitors: dict[str, KPIMonitor] = {}

_alert_callback: Callable[[str, Reading], Coroutine[Any, Any, None]] | None = None


def set_alert_callback(
    cb: Callable[[str, Reading], Coroutine[Any, Any, None]],
) -> None:
    """Set the global alert callback (called by the gateway on startup)."""
    global _alert_callback
    _alert_callback = cb


# ---------------------------------------------------------------------------
# JSON dot-path extraction
# ---------------------------------------------------------------------------

def _extract_field(data: Any, dot_path: str) -> Any:
    """
    Traverse *data* using a dot-separated path.

    Supports dict keys and integer list indices:
        ``response.items.0.value``  ->  data["response"]["items"][0]["value"]
    """
    parts = dot_path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Key '{part}' not found in dict (path: {dot_path})")
            current = current[part]
        elif isinstance(current, (list, tuple)):
            try:
                idx = int(part)
            except ValueError:
                raise KeyError(
                    f"Expected integer index for list, got '{part}' (path: {dot_path})"
                )
            if idx < 0 or idx >= len(current):
                raise IndexError(
                    f"Index {idx} out of range for list of length {len(current)} "
                    f"(path: {dot_path})"
                )
            current = current[idx]
        else:
            raise TypeError(
                f"Cannot traverse into {type(current).__name__} with key '{part}' "
                f"(path: {dot_path})"
            )
    return current


# ---------------------------------------------------------------------------
# Threshold evaluation
# ---------------------------------------------------------------------------

def _evaluate_threshold(
    value: float,
    threshold_min: float | None,
    threshold_max: float | None,
) -> str:
    """Return ``'ok'``, ``'warning'``, or ``'critical'`` based on thresholds."""
    if threshold_min is not None and value < threshold_min:
        return "critical"
    if threshold_max is not None and value > threshold_max:
        return "critical"
    return "ok"


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

async def _check_http_status(monitor: KPIMonitor) -> Reading:
    """GET the target URL and record the HTTP status code."""
    now = datetime.datetime.utcnow().isoformat() + "Z"
    try:
        async with aiohttp.ClientSession(
            headers={"User-Agent": _USER_AGENT},
        ) as session:
            async with session.get(
                monitor.target,
                timeout=_HTTP_TIMEOUT,
                allow_redirects=True,
            ) as resp:
                status_code = resp.status
                status = "ok" if status_code == 200 else "critical"
                message = f"HTTP {status_code}"
                return {
                    "timestamp": now,
                    "value": status_code,
                    "status": status,
                    "message": message,
                }
    except Exception as exc:
        return {
            "timestamp": now,
            "value": 0,
            "status": "critical",
            "message": f"HTTP request failed: {exc}",
        }


async def _check_http_json_field(monitor: KPIMonitor) -> Reading:
    """GET the target URL, extract a JSON field, compare against thresholds."""
    now = datetime.datetime.utcnow().isoformat() + "Z"
    try:
        async with aiohttp.ClientSession(
            headers={"User-Agent": _USER_AGENT},
        ) as session:
            async with session.get(
                monitor.target,
                timeout=_HTTP_TIMEOUT,
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    return {
                        "timestamp": now,
                        "value": resp.status,
                        "status": "critical",
                        "message": f"HTTP {resp.status} (expected 200)",
                    }
                data = await resp.json(content_type=None)

        if not monitor.field_path:
            return {
                "timestamp": now,
                "value": str(data),
                "status": "warning",
                "message": "No field_path specified; returning raw response",
            }

        value = _extract_field(data, monitor.field_path)
        numeric_value = float(value)
        status = _evaluate_threshold(
            numeric_value, monitor.threshold_min, monitor.threshold_max,
        )
        return {
            "timestamp": now,
            "value": numeric_value,
            "status": status,
            "message": f"{monitor.field_path} = {numeric_value}",
        }
    except (ValueError, TypeError) as exc:
        return {
            "timestamp": now,
            "value": str(value) if "value" in dir() else "N/A",
            "status": "warning",
            "message": f"Non-numeric value at field path: {exc}",
        }
    except Exception as exc:
        return {
            "timestamp": now,
            "value": 0,
            "status": "critical",
            "message": f"JSON field check failed: {exc}",
        }


async def _check_database_query(monitor: KPIMonitor) -> Reading:
    """Execute a database query via the database_bi skill."""
    now = datetime.datetime.utcnow().isoformat() + "Z"
    try:
        # Lazy import to avoid hard dependency
        from neuralclaw.skills.builtins.database_bi import db_query

        result = await db_query(
            connection_name="default",
            query=monitor.target,
        )
        if "error" in result:
            return {
                "timestamp": now,
                "value": 0,
                "status": "critical",
                "message": f"Query error: {result['error']}",
            }

        rows = result.get("rows", [])
        if not rows or not rows[0]:
            return {
                "timestamp": now,
                "value": 0,
                "status": "warning",
                "message": "Query returned no rows",
            }

        # Take the first column of the first row as the metric value
        raw_value = rows[0][0] if isinstance(rows[0], (list, tuple)) else next(iter(rows[0].values()))
        numeric_value = float(raw_value)
        status = _evaluate_threshold(
            numeric_value, monitor.threshold_min, monitor.threshold_max,
        )
        return {
            "timestamp": now,
            "value": numeric_value,
            "status": status,
            "message": f"Query result = {numeric_value}",
        }
    except Exception as exc:
        return {
            "timestamp": now,
            "value": 0,
            "status": "critical",
            "message": f"Database check failed: {exc}",
        }


async def _check_file_metric(monitor: KPIMonitor) -> Reading:
    """Read a file and extract a numeric value."""
    now = datetime.datetime.utcnow().isoformat() + "Z"
    try:
        path = Path(monitor.target).expanduser().resolve()
        if not path.is_file():
            return {
                "timestamp": now,
                "value": 0,
                "status": "critical",
                "message": f"File not found: {path}",
            }

        content = path.read_text(encoding="utf-8", errors="replace").strip()

        # If field_path is set and file is JSON, extract field
        if monitor.field_path and content.startswith(("{", "[")):
            data = json.loads(content)
            raw_value = _extract_field(data, monitor.field_path)
            numeric_value = float(raw_value)
        else:
            # Try to find the first numeric value in the file
            match = re.search(r"-?\d+(?:\.\d+)?", content)
            if match:
                numeric_value = float(match.group())
            else:
                return {
                    "timestamp": now,
                    "value": content[:200],
                    "status": "warning",
                    "message": "No numeric value found in file",
                }

        status = _evaluate_threshold(
            numeric_value, monitor.threshold_min, monitor.threshold_max,
        )
        return {
            "timestamp": now,
            "value": numeric_value,
            "status": status,
            "message": f"File metric = {numeric_value}",
        }
    except Exception as exc:
        return {
            "timestamp": now,
            "value": 0,
            "status": "critical",
            "message": f"File metric check failed: {exc}",
        }


async def _check_custom_python(monitor: KPIMonitor) -> Reading:
    """Execute a Python snippet in a restricted sandbox and record the result."""
    now = datetime.datetime.utcnow().isoformat() + "Z"
    try:
        # Run the snippet in a subprocess for isolation
        snippet = monitor.target
        wrapper = textwrap.dedent(f"""\
            import json, sys
            try:
                _result = None
                exec({snippet!r})
                # The snippet should assign to _result
                print(json.dumps({{"value": _result}}))
            except Exception as e:
                print(json.dumps({{"error": str(e)}}))
        """)

        proc = await asyncio.create_subprocess_exec(
            "python", "-c", wrapper,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", errors="replace").strip()
            return {
                "timestamp": now,
                "value": 0,
                "status": "critical",
                "message": f"Python snippet failed (rc={proc.returncode}): {err_text[:500]}",
            }

        output = json.loads(stdout.decode("utf-8", errors="replace").strip())
        if "error" in output:
            return {
                "timestamp": now,
                "value": 0,
                "status": "critical",
                "message": f"Snippet error: {output['error']}",
            }

        raw_value = output.get("value")
        if raw_value is None:
            return {
                "timestamp": now,
                "value": "None",
                "status": "warning",
                "message": "Snippet did not assign to _result",
            }

        try:
            numeric_value = float(raw_value)
        except (ValueError, TypeError):
            return {
                "timestamp": now,
                "value": str(raw_value),
                "status": "ok",
                "message": f"Non-numeric result: {raw_value}",
            }

        status = _evaluate_threshold(
            numeric_value, monitor.threshold_min, monitor.threshold_max,
        )
        return {
            "timestamp": now,
            "value": numeric_value,
            "status": status,
            "message": f"Python result = {numeric_value}",
        }
    except asyncio.TimeoutError:
        return {
            "timestamp": now,
            "value": 0,
            "status": "critical",
            "message": "Python snippet timed out (30s limit)",
        }
    except Exception as exc:
        return {
            "timestamp": now,
            "value": 0,
            "status": "critical",
            "message": f"Custom Python check failed: {exc}",
        }


# Dispatch table
_CHECK_HANDLERS: dict[str, Callable[[KPIMonitor], Coroutine[Any, Any, Reading]]] = {
    "http_status": _check_http_status,
    "http_json_field": _check_http_json_field,
    "database_query": _check_database_query,
    "file_metric": _check_file_metric,
    "custom_python": _check_custom_python,
}


# ---------------------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------------------

async def _run_check(monitor: KPIMonitor) -> Reading:
    """Execute a single check for *monitor* and store the reading."""
    handler = _CHECK_HANDLERS.get(monitor.check_type)
    if handler is None:
        reading: Reading = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "value": 0,
            "status": "critical",
            "message": f"Unknown check type: {monitor.check_type}",
        }
    else:
        reading = await handler(monitor)

    monitor.history.append(reading)

    # Fire alert callback for non-ok readings
    if reading["status"] != "ok" and _alert_callback is not None:
        try:
            await _alert_callback(monitor.name, reading)
        except Exception:
            logger.exception("Alert callback failed for monitor %s", monitor.name)

    return reading


async def _monitor_loop(monitor: KPIMonitor) -> None:
    """Background loop that periodically checks a KPI monitor."""
    logger.info(
        "Starting monitor loop: %s (interval=%ds)",
        monitor.name,
        monitor.check_interval_seconds,
    )
    try:
        while True:
            try:
                await _run_check(monitor)
            except Exception:
                logger.exception("Unhandled error in monitor %s", monitor.name)
            await asyncio.sleep(monitor.check_interval_seconds)
    except asyncio.CancelledError:
        logger.info("Monitor loop cancelled: %s", monitor.name)


def _start_background_task(monitor: KPIMonitor) -> None:
    """Start (or restart) the asyncio background task for a monitor."""
    if monitor._task is not None and not monitor._task.done():
        monitor._task.cancel()
    monitor._task = asyncio.ensure_future(_monitor_loop(monitor))


def _stop_background_task(monitor: KPIMonitor) -> None:
    """Cancel the background task for a monitor."""
    if monitor._task is not None and not monitor._task.done():
        monitor._task.cancel()
        monitor._task = None


# ---------------------------------------------------------------------------
# Public tool handlers
# ---------------------------------------------------------------------------

async def kpi_create_monitor(
    name: str,
    description: str = "",
    check_type: str = "http_status",
    target: str = "",
    field_path: str = "",
    threshold_min: float | None = None,
    threshold_max: float | None = None,
    check_interval_seconds: int = _DEFAULT_INTERVAL,
    alert_message_template: str = "KPI '{name}' is {status}: value={value}",
    **kwargs: Any,
) -> dict[str, Any]:
    """Create a named KPI monitor and start its background check loop."""
    if not name:
        return {"error": "Monitor name is required"}
    if not target:
        return {"error": "Target (URL, query, path, or snippet) is required"}
    if check_type not in _VALID_CHECK_TYPES:
        return {
            "error": (
                f"Invalid check_type '{check_type}'. "
                f"Must be one of: {', '.join(sorted(_VALID_CHECK_TYPES))}"
            ),
        }
    if name in _monitors:
        return {"error": f"Monitor '{name}' already exists. Remove it first or choose another name."}
    if check_interval_seconds < 10:
        check_interval_seconds = 10  # enforce minimum

    monitor = KPIMonitor(
        name=name,
        description=description,
        check_type=check_type,
        target=target,
        field_path=field_path,
        threshold_min=threshold_min,
        threshold_max=threshold_max,
        check_interval_seconds=check_interval_seconds,
        alert_message_template=alert_message_template,
    )
    _monitors[name] = monitor
    _start_background_task(monitor)

    logger.info("Created KPI monitor: %s (%s)", name, check_type)
    return {
        "message": f"Monitor '{name}' created and started.",
        "monitor": monitor.to_dict(),
    }


async def kpi_list_monitors(**kwargs: Any) -> dict[str, Any]:
    """List all active KPI monitors with their last readings."""
    if not _monitors:
        return {"monitors": [], "message": "No KPI monitors are currently active."}
    return {
        "monitors": [m.to_dict() for m in _monitors.values()],
    }


async def kpi_remove_monitor(name: str, **kwargs: Any) -> dict[str, Any]:
    """Remove a KPI monitor by name, cancelling its background task."""
    if not name:
        return {"error": "Monitor name is required"}
    monitor = _monitors.pop(name, None)
    if monitor is None:
        return {"error": f"Monitor '{name}' not found."}
    _stop_background_task(monitor)
    logger.info("Removed KPI monitor: %s", name)
    return {"message": f"Monitor '{name}' removed.", "final_reading": monitor.last_reading}


async def kpi_check_now(name: str = "", **kwargs: Any) -> dict[str, Any]:
    """
    Manually trigger a check for a specific monitor, or all monitors if
    *name* is empty.
    """
    if name:
        monitor = _monitors.get(name)
        if monitor is None:
            return {"error": f"Monitor '{name}' not found."}
        reading = await _run_check(monitor)
        return {"monitor": name, "reading": reading}

    # Check all monitors
    if not _monitors:
        return {"error": "No monitors to check."}

    results: dict[str, Reading] = {}
    for mon_name, monitor in _monitors.items():
        results[mon_name] = await _run_check(monitor)
    return {"readings": results}


async def kpi_history(
    name: str,
    limit: int = 20,
    **kwargs: Any,
) -> dict[str, Any]:
    """Return the last *limit* readings for a monitor."""
    if not name:
        return {"error": "Monitor name is required"}
    monitor = _monitors.get(name)
    if monitor is None:
        return {"error": f"Monitor '{name}' not found."}
    limit = max(1, min(limit, _MAX_HISTORY))
    readings = list(monitor.history)[-limit:]
    return {
        "monitor": name,
        "total_readings": len(monitor.history),
        "returned": len(readings),
        "readings": readings,
    }


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="kpi_monitor",
        description=(
            "Create and manage KPI monitoring agents that watch metrics "
            "and alert when thresholds are breached"
        ),
        capabilities=[
            Capability.NETWORK_HTTP,
            Capability.FILESYSTEM_READ,
            Capability.SHELL_EXECUTE,
        ],
        tools=[
            ToolDefinition(
                name="kpi_create_monitor",
                description=(
                    "Create a named KPI monitor that periodically checks a metric "
                    "and alerts when thresholds are breached. Supported check types: "
                    "http_status, http_json_field, database_query, file_metric, "
                    "custom_python."
                ),
                parameters=[
                    ToolParameter(
                        name="name",
                        type="string",
                        description="Unique name for this KPI monitor",
                    ),
                    ToolParameter(
                        name="description",
                        type="string",
                        description="Human-readable description of what this monitor tracks",
                        required=False,
                        default="",
                    ),
                    ToolParameter(
                        name="check_type",
                        type="string",
                        description="Type of check to perform",
                        enum=[
                            "http_status",
                            "http_json_field",
                            "database_query",
                            "file_metric",
                            "custom_python",
                        ],
                    ),
                    ToolParameter(
                        name="target",
                        type="string",
                        description=(
                            "The target to check: a URL for http_status/http_json_field, "
                            "a SQL query for database_query, a file path for file_metric, "
                            "or a Python snippet for custom_python"
                        ),
                    ),
                    ToolParameter(
                        name="field_path",
                        type="string",
                        description=(
                            "Dot-separated path to extract a value from JSON response "
                            "or JSON file (e.g. 'data.metrics.cpu_usage'). "
                            "Used by http_json_field and file_metric check types."
                        ),
                        required=False,
                        default="",
                    ),
                    ToolParameter(
                        name="threshold_min",
                        type="number",
                        description=(
                            "Minimum acceptable value. Readings below this are critical."
                        ),
                        required=False,
                        default=None,
                    ),
                    ToolParameter(
                        name="threshold_max",
                        type="number",
                        description=(
                            "Maximum acceptable value. Readings above this are critical."
                        ),
                        required=False,
                        default=None,
                    ),
                    ToolParameter(
                        name="check_interval_seconds",
                        type="integer",
                        description=(
                            "How often to run the check in seconds (default 300, min 10)"
                        ),
                        required=False,
                        default=300,
                    ),
                    ToolParameter(
                        name="alert_message_template",
                        type="string",
                        description=(
                            "Template for alert messages. Available placeholders: "
                            "{name}, {status}, {value}."
                        ),
                        required=False,
                        default="KPI '{name}' is {status}: value={value}",
                    ),
                ],
                handler=kpi_create_monitor,
            ),
            ToolDefinition(
                name="kpi_list_monitors",
                description=(
                    "List all active KPI monitors with their configuration "
                    "and last readings."
                ),
                parameters=[],
                handler=kpi_list_monitors,
            ),
            ToolDefinition(
                name="kpi_remove_monitor",
                description="Remove a KPI monitor by name and stop its background task.",
                parameters=[
                    ToolParameter(
                        name="name",
                        type="string",
                        description="Name of the monitor to remove",
                    ),
                ],
                handler=kpi_remove_monitor,
            ),
            ToolDefinition(
                name="kpi_check_now",
                description=(
                    "Manually trigger an immediate check for a specific monitor "
                    "(by name) or all monitors (if name is empty)."
                ),
                parameters=[
                    ToolParameter(
                        name="name",
                        type="string",
                        description=(
                            "Name of the monitor to check. Leave empty to check all."
                        ),
                        required=False,
                        default="",
                    ),
                ],
                handler=kpi_check_now,
            ),
            ToolDefinition(
                name="kpi_history",
                description=(
                    "Return the last N readings for a named KPI monitor."
                ),
                parameters=[
                    ToolParameter(
                        name="name",
                        type="string",
                        description="Name of the monitor",
                    ),
                    ToolParameter(
                        name="limit",
                        type="integer",
                        description="Maximum number of readings to return (default 20, max 100)",
                        required=False,
                        default=20,
                    ),
                ],
                handler=kpi_history,
            ),
        ],
    )
