"""
SkillForge Channel Handlers — Let users synthesize skills from any channel.

Trigger patterns (all platforms):
  Discord:   !forge <source> [--for <use_case>]
  Telegram:  /forge <source> [for: <use_case>]
  Slack:     @bot forge <source> [for: <use_case>]
  WhatsApp:  forge: <source>
  CLI:       neuralclaw forge <source> [--use-case <use_case>]

Multi-turn: if SkillForge needs clarification it asks questions
in the thread. User answers, forge continues.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from neuralclaw.skills.forge import SkillForge, ForgeSession


# -- Trigger patterns per platform --

FORGE_PATTERNS = [
    # Discord: !forge ... [--for ...]
    re.compile(r"^!forge\s+(.+?)(?:\s+--for\s+(.+))?$", re.I | re.DOTALL),
    # Telegram: /forge ... [for: ...]
    re.compile(r"^/forge\s+(.+?)(?:\s+for:\s*(.+))?$", re.I | re.DOTALL),
    # Slack: forge ... [for: ...]
    re.compile(r"^forge\s+(.+?)(?:\s+for:\s*(.+))?$", re.I | re.DOTALL),
    # WhatsApp: forge: ...
    re.compile(r"^forge:\s*(.+?)(?:\s+for:\s*(.+))?$", re.I | re.DOTALL),
    # Generic (CLI / web / any): forge <source>
    re.compile(r"^forge\s+(.+)", re.I | re.DOTALL),
]

# Status message answering a pending clarification
CLARIFICATION_PATTERN = re.compile(r"^(answer|reply|forge:?\s+answer)\s*:?\s*(.+)$", re.I | re.DOTALL)


def detect_forge_command(content: str) -> tuple[str, str] | None:
    """Returns (source, use_case) if content is a forge command, else None."""
    content = content.strip()
    for pattern in FORGE_PATTERNS:
        m = pattern.match(content)
        if m:
            source = m.group(1).strip()
            use_case = (m.group(2) or "").strip() if m.lastindex and m.lastindex >= 2 else ""
            return source, use_case
    return None


def detect_clarification_reply(content: str) -> str | None:
    """Returns the answer text if this is a reply to a forge clarification."""
    content = content.strip()
    m = CLARIFICATION_PATTERN.match(content)
    if m:
        return m.group(2).strip()
    return None


async def handle_forge_message(
    content: str,
    author_id: str,
    channel_id: str,
    platform: str,
    forge: "SkillForge",
    respond: Any,
) -> bool:
    """
    Check if a channel message is a forge command and handle it.
    Returns True if handled (caller should not process further).
    """
    # Check if this is a reply to a pending clarification
    session_key = f"{platform}:{channel_id}:{author_id}"
    pending_session = forge._sessions.get(session_key)

    if pending_session and pending_session.pending_clarifications:
        answer = detect_clarification_reply(content) or content.strip()
        if answer:
            return await _handle_clarification_reply(
                answer, pending_session, forge, respond, session_key
            )

    # Check for forge command
    parsed = detect_forge_command(content)
    if not parsed:
        return False

    source, use_case = parsed
    session_id = uuid.uuid4().hex[:8]
    session_key = f"{platform}:{channel_id}:{author_id}"

    await respond(
        f"\U0001f527 SkillForge started (`{session_id}`)\n"
        f"Analyzing: `{source[:80]}`"
        + (f"\nUse case: _{use_case}_" if use_case else "")
        + "\nThis takes 15-60 seconds..."
    )

    # Create session for multi-turn tracking
    session = _ForgeSessionImpl(
        session_id=session_id,
        user_id=author_id,
        channel_id=channel_id,
        platform=platform,
        source=source,
        use_case=use_case,
    )
    forge._sessions[session_key] = session

    result = await forge.steal(source, use_case=use_case, session=session)

    if result.clarifications_needed:
        session.pending_clarifications = result.clarifications_needed
        forge._sessions[session_key] = session

        questions = "\n".join(f"{i+1}. {q}" for i, q in enumerate(result.clarifications_needed))
        await respond(
            f"\U0001f914 I need a bit more info to generate the right tools:\n\n{questions}\n\n"
            f"Reply with your answers (or type `forge answer: <answer>` to reply)."
        )
        return True

    # Clean up session
    forge._sessions.pop(session_key, None)

    if result.success:
        tools_list = "\n".join(
            f"  \u2022 `{t.name}` \u2014 {t.description}"
            for t in (result.manifest.tools if result.manifest else [])
        )
        await respond(
            f"\u2705 **Skill `{result.skill_name}` forged successfully!**\n\n"
            f"**Tools generated ({result.tools_generated}):**\n{tools_list}\n\n"
            f"**Saved to:** `{result.file_path}`\n"
            f"**Active now** \u2014 use it in your next message.\n"
            f"\u23f1 {result.elapsed_seconds}s"
        )
    else:
        error_msg = result.error or "Unknown error"
        if result.static_analysis:
            blocked = [f['description'] for f in result.static_analysis if f.get('severity', 0) > 0.7]
            error_msg += f"\nSecurity flags: {', '.join(blocked)}"
        await respond(
            f"\u274c **SkillForge failed for `{source[:60]}`**\n\n"
            f"Error: {error_msg}\n\n"
            f"Try rephrasing your use case or providing more context."
        )

    return True


async def _handle_clarification_reply(
    answer: str,
    session: Any,
    forge: "SkillForge",
    respond: Any,
    session_key: str,
) -> bool:
    """Continue a forge session after the user answered clarification questions."""
    q = session.pending_clarifications[0] if session.pending_clarifications else "context"
    session.answers[q] = answer
    session.pending_clarifications = session.pending_clarifications[1:]

    if session.pending_clarifications:
        next_q = session.pending_clarifications[0]
        await respond(f"Got it. Next question:\n{next_q}")
        return True

    enriched_use_case = (
        session.use_case + "\n"
        + "\n".join(f"{k}: {v}" for k, v in session.answers.items())
    )
    await respond("Got it \u2014 generating your skill now...")

    result = await forge.steal(session.source, use_case=enriched_use_case, session=session)
    forge._sessions.pop(session_key, None)

    if result.success:
        tools_list = "\n".join(
            f"  \u2022 `{t.name}` \u2014 {t.description}"
            for t in (result.manifest.tools if result.manifest else [])
        )
        await respond(
            f"\u2705 **Skill `{result.skill_name}` forged!**\n\n"
            f"**Tools:** {result.tools_generated}\n{tools_list}\n"
            f"**Active now.**"
        )
    else:
        await respond(f"\u274c Forge failed: {result.error}")

    return True


class _ForgeSessionImpl:
    """Minimal ForgeSession implementation (avoids circular import)."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.pending_clarifications: list[str] = []
        self.answers: dict[str, str] = {}
