"""Channel command handlers for SkillScout.

Detects scout commands across platforms and routes them to the
SkillScout engine.  Mirrors forge_handlers.py patterns.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Awaitable

logger = logging.getLogger("neuralclaw.scout")


# ---------------------------------------------------------------------------
# Patterns — one per platform convention
# ---------------------------------------------------------------------------

SCOUT_PATTERNS = [
    # Discord: !scout ...
    re.compile(r"^!scout\s+(.+)$", re.I | re.DOTALL),
    # Telegram: /scout ...
    re.compile(r"^/scout\s+(.+)$", re.I | re.DOTALL),
    # Slack: scout ...
    re.compile(r"^scout\s+(.+)$", re.I | re.DOTALL),
    # WhatsApp: scout: ...
    re.compile(r"^scout:\s*(.+)$", re.I | re.DOTALL),
    # Generic (CLI / web): scout: ... or scout ...
    re.compile(r"^scout\s+(.+)", re.I | re.DOTALL),
]


def detect_scout_command(content: str) -> str | None:
    """Return the search query if *content* matches a scout pattern, else None."""
    text = content.strip()
    for pat in SCOUT_PATTERNS:
        m = pat.match(text)
        if m:
            return m.group(1).strip()
    return None


async def handle_scout_message(
    content: str,
    author_id: str,
    channel_id: str,
    platform: str,
    scout: Any,  # SkillScout
    respond: Callable[[str], Awaitable[None]],
) -> bool:
    """Try to handle *content* as a scout command.

    Returns True if the message was consumed, False otherwise.
    """
    query = detect_scout_command(content)
    if query is None:
        return False

    logger.info(
        "SCOUT_COMMAND: query=%r, author=%s, channel=%s, platform=%s",
        query, author_id, channel_id, platform,
    )

    await respond(f"Scouting for: *{query}*\nSearching PyPI, GitHub, npm, MCP registries...")

    result = await scout.scout(query)

    if not result.success:
        # Show what we found even if forge failed
        if result.candidates:
            candidate_list = "\n".join(
                f"  {i+1}. [{c.registry.value}] **{c.name}** — {c.description[:80]}"
                for i, c in enumerate(result.candidates[:5])
            )
            msg = (
                f"Found {len(result.candidates)} candidates:\n{candidate_list}\n\n"
            )
            if result.chosen:
                msg += f"Tried to forge **{result.chosen.name}** but it failed: {result.error}\n"
                msg += "You can try forging a different candidate manually with `forge <source>`."
            await respond(msg)
        else:
            await respond(f"No results found for: {query}\nTry a more specific description.")
        return True

    # Success — show the full flow
    candidate_list = "\n".join(
        f"  {i+1}. [{c.registry.value}] **{c.name}**"
        + (f" ({c.stars} ⭐)" if c.stars else "")
        + f" — {c.description[:60]}"
        for i, c in enumerate(result.candidates[:5])
    )
    chosen_note = ""
    if result.chosen:
        chosen_note = (
            f"\nChose **{result.chosen.name}** ({result.chosen.registry.value})"
        )
        if result.chosen.relevance_note:
            chosen_note += f" — {result.chosen.relevance_note}"

    tools_list = "\n".join(f"  • {t}" for t in result.tools)
    msg = (
        f"Scouted {len(result.candidates)} candidates:\n{candidate_list}"
        f"{chosen_note}\n\n"
        f"✅ Skill **{result.skill_name}** forged — {len(result.tools)} tools:\n"
        f"{tools_list}\n\n"
        f"Active now. ({result.elapsed_seconds}s)"
    )
    await respond(msg)
    return True
