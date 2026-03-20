"""Tests for SkillScout — discovery layer for SkillForge."""

from __future__ import annotations

import asyncio
import pytest

from neuralclaw.skills.scout import (
    SkillScout,
    ScoutCandidate,
    ScoutResult,
    SourceRegistry,
    _quote,
)
from neuralclaw.skills.scout_handlers import (
    detect_scout_command,
    SCOUT_PATTERNS,
)


# ---------------------------------------------------------------------------
# detect_scout_command
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("/scout verify insurance eligibility", "verify insurance eligibility"),
    ("scout dns lookup library", "dns lookup library"),
    ("scout: image resizing tool", "image resizing tool"),
    ("!scout best csv parser", "best csv parser"),
    ("hello world", None),
    ("forge something", None),
    ("", None),
])
def test_detect_scout_command(text: str, expected: str | None):
    result = detect_scout_command(text)
    assert result == expected


# ---------------------------------------------------------------------------
# Heuristic ranking
# ---------------------------------------------------------------------------

def test_heuristic_rank_prefers_stars_and_license():
    scout = SkillScout(forge=None, provider=None)
    candidates = [
        ScoutCandidate(
            name="low-star",
            source="https://github.com/a/low",
            registry=SourceRegistry.GITHUB,
            stars=10,
            license="GPL-3.0",
        ),
        ScoutCandidate(
            name="high-star-mit",
            source="https://github.com/b/high",
            registry=SourceRegistry.GITHUB,
            stars=5000,
            license="MIT",
        ),
        ScoutCandidate(
            name="npm-pkg",
            source="npm:something",
            registry=SourceRegistry.NPM,
            stars=0,
        ),
    ]
    best = scout._heuristic_rank(candidates)
    assert best.name == "high-star-mit"
    assert "Heuristic" in best.relevance_note


def test_heuristic_rank_prefers_claw_club():
    scout = SkillScout(forge=None, provider=None)
    candidates = [
        ScoutCandidate(
            name="github-thing",
            source="https://github.com/a/b",
            registry=SourceRegistry.GITHUB,
            stars=100,
        ),
        ScoutCandidate(
            name="claw-club-thing",
            source="https://claw.club/skill/x",
            registry=SourceRegistry.CLAW_CLUB,
            stars=10,
        ),
    ]
    best = scout._heuristic_rank(candidates)
    assert best.name == "claw-club-thing"


# ---------------------------------------------------------------------------
# _quote
# ---------------------------------------------------------------------------

def test_quote_encodes_spaces():
    assert _quote("hello world") == "hello+world"
    assert _quote("a&b=c") == "a%26b%3Dc"


# ---------------------------------------------------------------------------
# ScoutResult defaults
# ---------------------------------------------------------------------------

def test_scout_result_defaults():
    r = ScoutResult()
    assert r.success is False
    assert r.candidates == []
    assert r.tools == []
    assert r.elapsed_seconds == 0.0


# ---------------------------------------------------------------------------
# Single candidate skips LLM ranking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rank_single_candidate_returns_it():
    scout = SkillScout(forge=None, provider=None)
    c = ScoutCandidate(
        name="only-one", source="pkg", registry=SourceRegistry.PYPI,
    )
    result = await scout._rank_candidates([c], "anything")
    assert result is c


# ---------------------------------------------------------------------------
# SCOUT_PATTERNS count
# ---------------------------------------------------------------------------

def test_scout_patterns_count():
    assert len(SCOUT_PATTERNS) == 5


# ---------------------------------------------------------------------------
# End-to-end scout with mock forge
# ---------------------------------------------------------------------------

class _MockForge:
    """Minimal mock for SkillForge."""
    def __init__(self):
        self.steal_called_with = None

    async def steal(self, source: str, use_case: str = "", session=None):
        self.steal_called_with = (source, use_case)
        from dataclasses import dataclass, field
        @dataclass
        class FakeManifest:
            tools: list = field(default_factory=list)
        @dataclass
        class FakeResult:
            success: bool = True
            skill_name: str = "test_skill"
            tools_generated: int = 1
            manifest: FakeManifest = field(default_factory=FakeManifest)
            error: str = ""
            clarifications_needed: list = field(default_factory=list)
            elapsed_seconds: float = 0.0
        return FakeResult()


@pytest.mark.asyncio
async def test_scout_e2e_with_mock():
    """Scout with injected HTTP that returns one GitHub result."""
    mock_forge = _MockForge()

    async def mock_http_get(url, timeout=15, headers=None, raw=False):
        if "api.github.com" in url:
            return {
                "items": [{
                    "full_name": "test/repo",
                    "html_url": "https://github.com/test/repo",
                    "description": "A test repo",
                    "stargazers_count": 500,
                    "updated_at": "2026-01-01",
                    "license": {"spdx_id": "MIT"},
                }]
            }
        return None

    scout = SkillScout(
        forge=mock_forge,
        provider=None,
        http_get=mock_http_get,
    )
    result = await scout.scout("test library")
    assert result.success
    assert result.skill_name == "test_skill"
    assert mock_forge.steal_called_with is not None
    assert "github.com/test/repo" in mock_forge.steal_called_with[0]
