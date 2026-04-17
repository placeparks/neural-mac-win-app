"""
Built-in Skill: Digest --- Summarize and digest information into briefings.

Provides tools for creating summaries, morning briefings, thread digests,
and comparative analysis. Uses the LLM provider for intelligent
summarization and the memory provider for episodic recall.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from neuralclaw.cortex.action.capabilities import Capability
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level providers (set by gateway on init)
# ---------------------------------------------------------------------------

_llm_provider: Any | None = None
_memory_provider: Any | None = None


def set_llm_provider(provider: Any) -> None:
    """Set the LLM provider instance for summarization calls."""
    global _llm_provider
    _llm_provider = provider


def set_memory_provider(provider: Any) -> None:
    """Set the memory provider instance for episodic memory access."""
    global _memory_provider
    _memory_provider = provider


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _llm_complete(system_prompt: str, user_prompt: str, max_tokens: int = 1024) -> str:
    """Send a completion request to the LLM provider and return the text."""
    if not _llm_provider:
        raise RuntimeError("LLM provider is not configured")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # The LLM provider exposes a chat/complete interface; adapt to
    # whichever method is available.
    if hasattr(_llm_provider, "chat"):
        response = await _llm_provider.chat(messages, max_tokens=max_tokens)
    elif hasattr(_llm_provider, "complete"):
        response = await _llm_provider.complete(messages, max_tokens=max_tokens)
    elif hasattr(_llm_provider, "generate"):
        response = await _llm_provider.generate(messages, max_tokens=max_tokens)
    else:
        raise RuntimeError(
            "LLM provider does not expose a recognised completion method "
            "(expected chat, complete, or generate)"
        )

    # Normalise response to plain text
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        return (
            response.get("content")
            or response.get("text")
            or response.get("message", "")
        )
    # Fallback: stringify
    return str(response)


def _truncate(text: str, max_length: int) -> str:
    """Truncate text to *max_length* characters on a word boundary."""
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")
    if last_space > max_length * 0.6:
        truncated = truncated[:last_space]
    return truncated.rstrip() + "..."


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def digest_create(
    title: str,
    content: str,
    format: str = "bullet",
    max_length: int = 500,
    **kwargs: Any,
) -> dict[str, Any]:
    """Create a digest / briefing from provided text content."""
    if not _llm_provider:
        return {"error": "LLM provider is not configured"}

    format_instructions = {
        "bullet": (
            "Produce the summary as a concise bulleted list. "
            "Each bullet should capture one key point."
        ),
        "paragraph": (
            "Produce the summary as one or two cohesive paragraphs "
            "written in clear, professional prose."
        ),
        "executive": (
            "Produce an executive summary with a one-line headline, "
            "followed by 3-5 key takeaways as bullet points, and "
            "conclude with a brief recommendation or next-step sentence."
        ),
    }

    fmt_instruction = format_instructions.get(
        format, format_instructions["bullet"]
    )

    system_prompt = (
        "You are a precise summarisation assistant. "
        "Summarise the provided content faithfully without adding information "
        "that is not present. Keep the output under the requested length. "
        f"{fmt_instruction}"
    )

    user_prompt = (
        f"Title: {title}\n\n"
        f"Content:\n{content}\n\n"
        f"Maximum length: {max_length} characters."
    )

    try:
        summary = await _llm_complete(system_prompt, user_prompt, max_tokens=max_length * 2)
        summary = _truncate(summary.strip(), max_length)
        return {
            "title": title,
            "format": format,
            "summary": summary,
            "original_length": len(content),
            "summary_length": len(summary),
        }
    except Exception as exc:
        logger.error("digest_create failed: %s", exc)
        return {"error": f"Summarisation failed: {exc}"}


async def digest_morning_briefing(**kwargs: Any) -> dict[str, Any]:
    """
    Generate a morning briefing combining episodic memory highlights,
    pending tasks, calendar events, and KPI alerts.
    """
    if not _llm_provider:
        return {"error": "LLM provider is not configured"}

    now = datetime.now(timezone.utc)
    sections: dict[str, str] = {}

    # -- Episodic memory highlights ------------------------------------------
    if _memory_provider:
        try:
            if hasattr(_memory_provider, "recall"):
                memories = await _memory_provider.recall(
                    query="recent important events and highlights",
                    top_k=10,
                )
            elif hasattr(_memory_provider, "search"):
                memories = await _memory_provider.search(
                    "recent important events and highlights",
                    top_k=10,
                )
            else:
                memories = []

            if memories:
                if isinstance(memories, list):
                    lines = []
                    for m in memories:
                        if isinstance(m, dict):
                            lines.append(
                                m.get("content") or m.get("text") or str(m)
                            )
                        else:
                            lines.append(str(m))
                    sections["recent_memories"] = "\n".join(lines)
                else:
                    sections["recent_memories"] = str(memories)
        except Exception as exc:
            logger.warning("Could not retrieve episodic memories: %s", exc)
            sections["recent_memories"] = "(unavailable)"

        # -- Pending tasks ---------------------------------------------------
        try:
            if hasattr(_memory_provider, "get_pending_tasks"):
                tasks = await _memory_provider.get_pending_tasks()
            elif hasattr(_memory_provider, "recall"):
                tasks = await _memory_provider.recall(
                    query="pending tasks and action items",
                    top_k=10,
                )
            else:
                tasks = []

            if tasks:
                if isinstance(tasks, list):
                    task_lines = []
                    for t in tasks:
                        if isinstance(t, dict):
                            task_lines.append(
                                t.get("content") or t.get("text") or str(t)
                            )
                        else:
                            task_lines.append(str(t))
                    sections["pending_tasks"] = "\n".join(task_lines)
                else:
                    sections["pending_tasks"] = str(tasks)
        except Exception as exc:
            logger.warning("Could not retrieve pending tasks: %s", exc)
            sections["pending_tasks"] = "(unavailable)"

        # -- Calendar events -------------------------------------------------
        try:
            if hasattr(_memory_provider, "get_calendar_events"):
                events = await _memory_provider.get_calendar_events()
            elif hasattr(_memory_provider, "recall"):
                events = await _memory_provider.recall(
                    query="upcoming calendar events and meetings",
                    top_k=5,
                )
            else:
                events = []

            if events:
                if isinstance(events, list):
                    event_lines = []
                    for e in events:
                        if isinstance(e, dict):
                            event_lines.append(
                                e.get("content") or e.get("text") or str(e)
                            )
                        else:
                            event_lines.append(str(e))
                    sections["calendar_events"] = "\n".join(event_lines)
                else:
                    sections["calendar_events"] = str(events)
        except Exception as exc:
            logger.warning("Could not retrieve calendar events: %s", exc)
            sections["calendar_events"] = "(unavailable)"

        # -- KPI alerts ------------------------------------------------------
        try:
            if hasattr(_memory_provider, "get_kpi_alerts"):
                alerts = await _memory_provider.get_kpi_alerts()
            elif hasattr(_memory_provider, "recall"):
                alerts = await _memory_provider.recall(
                    query="KPI alerts metrics warnings",
                    top_k=5,
                )
            else:
                alerts = []

            if alerts:
                if isinstance(alerts, list):
                    alert_lines = []
                    for a in alerts:
                        if isinstance(a, dict):
                            alert_lines.append(
                                a.get("content") or a.get("text") or str(a)
                            )
                        else:
                            alert_lines.append(str(a))
                    sections["kpi_alerts"] = "\n".join(alert_lines)
                else:
                    sections["kpi_alerts"] = str(alerts)
        except Exception as exc:
            logger.warning("Could not retrieve KPI alerts: %s", exc)
            sections["kpi_alerts"] = "(unavailable)"
    else:
        sections["recent_memories"] = "(memory provider not configured)"
        sections["pending_tasks"] = "(memory provider not configured)"
        sections["calendar_events"] = "(memory provider not configured)"
        sections["kpi_alerts"] = "(memory provider not configured)"

    # -- Build the briefing via LLM -----------------------------------------
    assembled = ""
    for label, body in sections.items():
        assembled += f"## {label.replace('_', ' ').title()}\n{body}\n\n"

    system_prompt = (
        "You are a concise executive briefing assistant. "
        "Given the raw data sections below, produce a structured morning "
        "briefing with the following sections: "
        "1) Key Highlights, 2) Pending Tasks, 3) Calendar, 4) Alerts. "
        "Omit any section that is marked as unavailable or empty. "
        "Be brief, actionable, and professional."
    )

    user_prompt = (
        f"Date: {now.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"{assembled}"
    )

    try:
        briefing = await _llm_complete(system_prompt, user_prompt, max_tokens=1500)
        return {
            "date": now.isoformat(),
            "briefing": briefing.strip(),
            "sections_available": [k for k, v in sections.items() if v != "(unavailable)" and v != "(memory provider not configured)"],
        }
    except Exception as exc:
        logger.error("digest_morning_briefing failed: %s", exc)
        return {"error": f"Briefing generation failed: {exc}"}


async def digest_summarize_thread(
    messages: str,
    focus: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Summarise a conversation thread and extract key points, decisions,
    and action items.

    *messages* is a JSON-encoded array of objects with keys:
        author, text, timestamp
    """
    if not _llm_provider:
        return {"error": "LLM provider is not configured"}

    try:
        parsed = json.loads(messages) if isinstance(messages, str) else messages
    except json.JSONDecodeError as exc:
        return {"error": f"Invalid messages JSON: {exc}"}

    if not isinstance(parsed, list) or not parsed:
        return {"error": "messages must be a non-empty JSON array"}

    # Format the thread for the LLM
    thread_lines: list[str] = []
    for msg in parsed:
        author = msg.get("author", "Unknown")
        text = msg.get("text", "")
        timestamp = msg.get("timestamp", "")
        ts_label = f" ({timestamp})" if timestamp else ""
        thread_lines.append(f"[{author}{ts_label}]: {text}")

    thread_text = "\n".join(thread_lines)

    focus_clause = ""
    if focus:
        focus_clause = (
            f" Pay special attention to discussion related to: {focus}."
        )

    system_prompt = (
        "You are a meeting-notes assistant. Given a conversation thread, "
        "produce a structured summary with exactly these sections:\n"
        "- **Key Points**: the most important topics discussed\n"
        "- **Decisions**: any decisions that were made\n"
        "- **Action Items**: concrete next steps with owners if identifiable\n"
        "Be concise and factual. Do not invent information that is not in "
        "the thread."
        f"{focus_clause}"
    )

    user_prompt = (
        f"Conversation thread ({len(parsed)} messages):\n\n"
        f"{thread_text}"
    )

    try:
        summary = await _llm_complete(system_prompt, user_prompt, max_tokens=1500)
        return {
            "message_count": len(parsed),
            "focus": focus or None,
            "summary": summary.strip(),
        }
    except Exception as exc:
        logger.error("digest_summarize_thread failed: %s", exc)
        return {"error": f"Thread summarisation failed: {exc}"}


async def digest_compare(
    data_a: str,
    data_b: str,
    context: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Compare two datasets or reports and surface differences, trends,
    and insights.

    *data_a* and *data_b* can be plain text or JSON strings.
    *context* describes what the data represents.
    """
    if not _llm_provider:
        return {"error": "LLM provider is not configured"}

    context_clause = ""
    if context:
        context_clause = f"Context: {context}\n\n"

    system_prompt = (
        "You are an analytical comparison assistant. Given two datasets "
        "or reports (Dataset A and Dataset B), produce a structured "
        "comparison with exactly these sections:\n"
        "- **Differences**: what changed between A and B\n"
        "- **Trends**: any patterns or directional changes\n"
        "- **Insights**: actionable observations or recommendations\n"
        "Be precise and data-driven. Reference specific values where possible."
    )

    user_prompt = (
        f"{context_clause}"
        f"--- Dataset A ---\n{data_a}\n\n"
        f"--- Dataset B ---\n{data_b}"
    )

    try:
        analysis = await _llm_complete(system_prompt, user_prompt, max_tokens=1500)
        return {
            "context": context or None,
            "data_a_length": len(data_a),
            "data_b_length": len(data_b),
            "analysis": analysis.strip(),
        }
    except Exception as exc:
        logger.error("digest_compare failed: %s", exc)
        return {"error": f"Comparison failed: {exc}"}


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def get_manifest() -> SkillManifest:
    return SkillManifest(
        name="digest",
        description="Summarise and digest information into structured briefings",
        capabilities=[Capability.MEMORY_READ],
        tools=[
            ToolDefinition(
                name="digest_create",
                description=(
                    "Create a digest or briefing from provided text content. "
                    "Supports bullet, paragraph, and executive summary formats."
                ),
                parameters=[
                    ToolParameter(
                        name="title",
                        type="string",
                        description="Title for the digest",
                    ),
                    ToolParameter(
                        name="content",
                        type="string",
                        description="Raw text content to summarise",
                    ),
                    ToolParameter(
                        name="format",
                        type="string",
                        description="Output format: bullet, paragraph, or executive",
                        required=False,
                        default="bullet",
                        enum=["bullet", "paragraph", "executive"],
                    ),
                    ToolParameter(
                        name="max_length",
                        type="integer",
                        description="Maximum length of the summary in characters (default 500)",
                        required=False,
                        default=500,
                    ),
                ],
                handler=digest_create,
            ),
            ToolDefinition(
                name="digest_morning_briefing",
                description=(
                    "Generate a morning briefing combining recent episodic "
                    "memory highlights, pending tasks, calendar events, and "
                    "KPI alerts into a structured overview."
                ),
                parameters=[],
                handler=digest_morning_briefing,
            ),
            ToolDefinition(
                name="digest_summarize_thread",
                description=(
                    "Summarise a conversation thread into key points, "
                    "decisions, and action items. Provide messages as a JSON "
                    "array of {author, text, timestamp} objects."
                ),
                parameters=[
                    ToolParameter(
                        name="messages",
                        type="string",
                        description=(
                            "JSON array of message objects, each with keys: "
                            "author (string), text (string), timestamp (string, optional)"
                        ),
                    ),
                    ToolParameter(
                        name="focus",
                        type="string",
                        description="Optional topic to focus the summary on",
                        required=False,
                        default="",
                    ),
                ],
                handler=digest_summarize_thread,
            ),
            ToolDefinition(
                name="digest_compare",
                description=(
                    "Compare two datasets or reports and surface differences, "
                    "trends, and actionable insights."
                ),
                parameters=[
                    ToolParameter(
                        name="data_a",
                        type="string",
                        description="First dataset or report (text or JSON)",
                    ),
                    ToolParameter(
                        name="data_b",
                        type="string",
                        description="Second dataset or report (text or JSON)",
                    ),
                    ToolParameter(
                        name="context",
                        type="string",
                        description="Description of what is being compared",
                        required=False,
                        default="",
                    ),
                ],
                handler=digest_compare,
            ),
        ],
    )
