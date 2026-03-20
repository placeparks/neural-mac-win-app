"""
SkillForge test suite.
Tests input detection, use-case interview, code generation, and channel parsing.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from neuralclaw.skills.forge import SkillForge, ForgeInputType
from neuralclaw.skills.forge_handlers import detect_forge_command, detect_clarification_reply


# -- Fixtures --

@pytest.fixture
def mock_forge():
    provider = MagicMock()
    sandbox = MagicMock()
    registry = MagicMock()
    forge = SkillForge(provider=provider, sandbox=sandbox, registry=registry)
    return forge


@pytest.fixture
def mock_registry():
    class _Reg:
        def __init__(self):
            self.last_registered = None
        def register(self, manifest):
            self.last_registered = manifest.name
        def hot_register(self, manifest):
            self.last_registered = manifest.name
    return _Reg()


# -- Input type detection --

@pytest.mark.parametrize("source,expected", [
    ("https://github.com/stripe/stripe-python", ForgeInputType.GITHUB),
    ("https://api.stripe.com/openapi.json",     ForgeInputType.OPENAPI),
    ("https://api.stripe.com/v1",               ForgeInputType.URL),
    ("https://mygraphql.com/graphql",           ForgeInputType.GRAPHQL),
    ("I want to send SMS reminders",            ForgeInputType.DESCRIPTION),
    ("async def my_func(x):\n    return x",     ForgeInputType.CODE),
])
def test_input_type_detection(source: str, expected: ForgeInputType, mock_forge):
    result = mock_forge._detect_input_type(source)
    assert result == expected, f"Expected {expected} for '{source[:50]}', got {result}"


# -- Channel command parsing --

@pytest.mark.parametrize("content,expected_source,expected_use_case", [
    ("!forge https://api.stripe.com --for charge patients", "https://api.stripe.com", "charge patients"),
    ("/forge twilio for: send reminders",                   "twilio",                  "send reminders"),
    ("forge I want to send SMS",                            "I want to send SMS",      ""),
    ("forge: check insurance",                              "check insurance",          ""),
    ("FORGE https://github.com/owner/repo",                 "https://github.com/owner/repo", ""),
])
def test_forge_command_detection(content: str, expected_source: str, expected_use_case: str):
    result = detect_forge_command(content)
    assert result is not None, f"Should detect forge command in: {content}"
    source, use_case = result
    assert expected_source.lower() in source.lower()
    if expected_use_case:
        assert expected_use_case.lower() in use_case.lower()


def test_forge_command_not_detected_for_normal_messages():
    assert detect_forge_command("Hello, how are you?") is None
    assert detect_forge_command("What's the weather?") is None
    assert detect_forge_command("!help") is None


def test_clarification_reply_detection():
    assert detect_clarification_reply("forge answer: charge patients") == "charge patients"
    assert detect_clarification_reply("answer: I want to query invoices") == "I want to query invoices"
    assert detect_clarification_reply("hello world") is None


# -- Slugify --

def test_slugify(mock_forge):
    assert mock_forge._slugify("Stripe API v2") == "stripe_api_v2"
    assert mock_forge._slugify("Hello World!") == "hello_world"
    assert mock_forge._slugify("") == "skill"


# -- Hot loader --

@pytest.mark.asyncio
async def test_hot_loader_picks_up_new_file(tmp_path, mock_registry):
    from neuralclaw.skills.hot_loader import SkillHotLoader
    import neuralclaw.skills.hot_loader as hl_mod

    # Temporarily override SKILLS_DIR
    original = hl_mod.SKILLS_DIR
    hl_mod.SKILLS_DIR = tmp_path

    loader = SkillHotLoader(registry=mock_registry)

    skill_code = '''
from typing import Any
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition

async def ping() -> dict[str, Any]:
    return {"pong": True}

def get_manifest():
    return SkillManifest(name="ping_skill", description="Ping", tools=[
        ToolDefinition(name="ping", description="Ping", handler=ping)
    ])
'''
    skill_file = tmp_path / "ping_skill.py"
    skill_file.write_text(skill_code)

    loaded = await loader._load_skill_file(skill_file)
    assert loaded
    assert mock_registry.last_registered == "ping_skill"

    # Restore
    hl_mod.SKILLS_DIR = original
