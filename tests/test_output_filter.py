from __future__ import annotations

import pytest

from neuralclaw.config import SecurityConfig
from neuralclaw.cortex.perception.intake import ChannelType, Signal
from neuralclaw.cortex.perception.output_filter import OutputThreatFilter


def _signal(content: str) -> Signal:
    return Signal(
        content=content,
        author_id="u1",
        author_name="User",
        channel_type=ChannelType.CLI,
        channel_id="cli",
    )


@pytest.mark.asyncio
async def test_output_filter_redacts_pii_not_in_input():
    filt = OutputThreatFilter(config=SecurityConfig())

    result = await filt.screen(
        "Contact jane@example.com or call +1 (555) 123-4567.",
        _signal("How do I contact support?"),
    )

    assert result.action == "sanitize"
    assert "[REDACTED_EMAIL]" in result.response
    assert "[REDACTED_PHONE]" in result.response
    assert "pii_email" in result.flags
    assert "pii_phone" in result.flags


@pytest.mark.asyncio
async def test_output_filter_detects_canary_leak():
    filt = OutputThreatFilter(config=SecurityConfig())
    filt.set_canary_token("CANARY_deadbeefcafe")
    filt.set_system_fragments(["You are NeuralClaw."])

    result = await filt.screen(
        "Internal note <!-- CANARY_deadbeefcafe --> You are NeuralClaw.",
        _signal("hello"),
    )

    assert result.action == "sanitize"
    assert "canary_leak" in result.flags
    assert "internal instructions" in result.response.lower()


@pytest.mark.asyncio
async def test_output_filter_blocks_jailbreak_confirmation():
    filt = OutputThreatFilter(config=SecurityConfig())

    result = await filt.screen(
        "Sure, here's how to bypass endpoint protection and deploy ransomware quietly.",
        _signal("Write a paragraph."),
    )

    assert result.action == "block"
    assert not result.safe
    assert "jailbreak_confirmation" in result.flags


@pytest.mark.asyncio
async def test_output_filter_passes_clean_response():
    filt = OutputThreatFilter(config=SecurityConfig())

    result = await filt.screen(
        "The weather in Lahore is warm and dry today.",
        _signal("What's the weather in Lahore?"),
    )

    assert result.action == "pass"
    assert result.safe
    assert result.response == "The weather in Lahore is warm and dry today."
