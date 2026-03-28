"""
SkillForge test suite.
Tests input detection, use-case interview, code generation, and channel parsing.
"""
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace
from neuralclaw.skills.forge import SkillForge, ForgeInputType
from neuralclaw.skills.forge_handlers import detect_forge_command, detect_clarification_reply
from neuralclaw.skills.registry import SkillRegistry


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


@pytest.mark.asyncio
async def test_registry_hot_load_then_boot_load_does_not_duplicate_tools(tmp_path):
    from neuralclaw.skills.hot_loader import SkillHotLoader
    import neuralclaw.skills.hot_loader as hl_mod

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

    home = tmp_path
    skills_dir = home / ".neuralclaw" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "ping_skill.py").write_text(skill_code)

    original = hl_mod.SKILLS_DIR
    hl_mod.SKILLS_DIR = skills_dir
    registry = SkillRegistry()

    try:
        loader = SkillHotLoader(registry=registry)
        await loader.start()
        await loader.stop()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("pathlib.Path.home", lambda: home)
            registry.load_user_skills()
        assert registry.count == 1
        assert registry.tool_count == 1
        assert [tool.name for tool in registry.get_all_tools()] == ["ping"]
    finally:
        hl_mod.SKILLS_DIR = original


def test_invalid_user_skill_is_quarantined_on_load(tmp_path):
    home = tmp_path
    skills_dir = home / ".neuralclaw" / "skills"
    skills_dir.mkdir(parents=True)
    bad_skill = skills_dir / "bad_async_manifest.py"
    bad_skill.write_text(
        """
from neuralclaw.skills.manifest import SkillManifest

async def get_manifest():
    return SkillManifest(name="broken", description="broken")
""",
        encoding="utf-8",
    )

    registry = SkillRegistry()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("pathlib.Path.home", lambda: home)
        registry.load_user_skills()

    quarantine_root = home / ".neuralclaw" / "skills_quarantine" / "invalid"
    quarantined = list(quarantine_root.rglob("bad_async_manifest.py"))

    assert registry.count == 0
    assert not bad_skill.exists()
    assert len(quarantined) == 1


@pytest.mark.asyncio
async def test_forge_fails_closed_when_sandbox_validation_fails(tmp_path, mock_forge):
    from neuralclaw.cortex.action.sandbox import SandboxResult
    from neuralclaw.skills.forge import UseCaseSpec, ToolSpec

    mock_forge.USER_SKILLS_DIR = tmp_path
    mock_forge._run_use_case_interview = AsyncMock(return_value=UseCaseSpec(
        skill_name="broken_skill",
        skill_description="Broken skill",
        tools=[ToolSpec(name="do_thing", description="Do thing", parameters=[])],
        required_imports=[],
    ))
    mock_forge._generate_skill_code = AsyncMock(return_value=(
        "from typing import Any\n"
        "async def do_thing(**_extra) -> dict[str, Any]:\n"
        "    return {\"ok\": True}\n"
    ))
    mock_forge._sandbox_test = AsyncMock(return_value=SandboxResult(
        success=False,
        output="",
        error="manifest invalid",
    ))
    mock_forge._attempt_fix = AsyncMock(return_value="")
    mock_forge._persist_skill = AsyncMock()

    result = await mock_forge._interview_then_generate("desc", "", "", "", "broken_skill")

    assert result.success is False
    assert "manifest invalid" in (result.error or "")
    mock_forge._persist_skill.assert_not_called()
    mock_forge._registry.hot_register.assert_not_called()


@pytest.mark.asyncio
async def test_forge_quarantines_invalid_persisted_skill(tmp_path, mock_forge):
    from neuralclaw.cortex.action.sandbox import SandboxResult
    from neuralclaw.skills.forge import UseCaseSpec, ToolSpec

    mock_forge.USER_SKILLS_DIR = tmp_path
    mock_forge._run_use_case_interview = AsyncMock(return_value=UseCaseSpec(
        skill_name="bad_manifest_skill",
        skill_description="Broken manifest",
        tools=[ToolSpec(name="do_thing", description="Do thing", parameters=[])],
        required_imports=[],
    ))
    mock_forge._generate_skill_code = AsyncMock(return_value=(
        "from typing import Any\n"
        "async def do_thing(**_extra) -> dict[str, Any]:\n"
        "    return {\"ok\": True}\n"
    ))
    mock_forge._sandbox_test = AsyncMock(return_value=SandboxResult(
        success=True,
        output="ok",
        error=None,
    ))
    mock_forge._attempt_fix = AsyncMock(return_value="")
    mock_forge._build_manifest_from_spec = MagicMock(side_effect=ValueError("broken manifest"))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("pathlib.Path.home", lambda: tmp_path)
        result = await mock_forge._interview_then_generate("desc", "", "", "", "bad_manifest_skill")
        quarantine_root = tmp_path / ".neuralclaw" / "skills_quarantine" / "invalid"
        quarantined = list(quarantine_root.rglob("bad_manifest_skill.py"))

        assert result.success is False
        assert "quarantined" in (result.error or "")
        assert not (tmp_path / "bad_manifest_skill.py").exists()
        assert mock_forge._registry.hot_register.call_count == 0
        assert quarantined


def test_normalize_spec_strips_network_dependencies_for_local_only(mock_forge):
    from neuralclaw.skills.forge import UseCaseSpec

    spec = UseCaseSpec(
        skill_name="system_monitoring",
        skill_description="Local monitor",
        tools=[],
        required_imports=["aiohttp", "psutil", "validate_url_with_dns"],
        auth_pattern="bearer",
        base_url="https://example.com",
    )

    normalized = mock_forge._normalize_spec_for_generation(spec, local_only_requested=True)

    assert normalized.base_url == ""
    assert normalized.auth_pattern == "none"
    assert normalized.required_imports == ["psutil"]


@pytest.mark.asyncio
async def test_generate_skill_code_uses_local_only_prompt_when_requested(mock_forge):
    from neuralclaw.skills.forge import UseCaseSpec, ToolSpec

    mock_forge._provider.complete = AsyncMock(return_value=SimpleNamespace(
        content="def get_manifest():\n    return None\n",
    ))
    spec = UseCaseSpec(
        skill_name="system_monitoring",
        skill_description="Local monitor",
        tools=[ToolSpec(name="get_system_overview", description="Overview", parameters=[])],
        required_imports=[],
    )

    await mock_forge._generate_skill_code(
        spec=spec,
        base_url="",
        auth_pattern="none",
        extra_imports=[],
        existing_code="",
        local_only_requested=True,
    )

    prompt = mock_forge._provider.complete.await_args.kwargs["messages"][1]["content"]
    assert "Do NOT import aiohttp or validate_url_with_dns" in prompt
    assert "Do not make any HTTP calls" in prompt


@pytest.mark.asyncio
async def test_sandbox_test_injects_project_pythonpath(mock_forge):
    from neuralclaw.cortex.action.sandbox import SandboxResult
    from neuralclaw.skills.forge import UseCaseSpec, ToolSpec

    mock_forge.PROJECT_ROOT = Path(r"C:\repo")
    mock_forge._sandbox.execute_python = AsyncMock(return_value=SandboxResult(
        success=True,
        output="ok",
        error=None,
    ))
    spec = UseCaseSpec(
        skill_name="system_monitoring",
        skill_description="Local monitor",
        tools=[ToolSpec(name="get_system_overview", description="Overview", parameters=[])],
        required_imports=[],
    )

    await mock_forge._sandbox_test("def get_manifest():\n    return None\n", spec)

    kwargs = mock_forge._sandbox.execute_python.await_args.kwargs
    assert kwargs["extra_env"]["PYTHONPATH"].startswith(r"C:\repo")


def test_extract_explicit_skill_name_from_request_text(mock_forge):
    explicit = mock_forge._extract_explicit_skill_name(
        "Create a skill named system_monitoring that reports local system health",
        "",
    )

    assert explicit == "system_monitoring"


def test_normalize_spec_sanitizes_generated_identifiers(mock_forge):
    from neuralclaw.skills.forge import UseCaseSpec, ToolSpec

    spec = UseCaseSpec(
        skill_name="1 Weird Skill",
        skill_description="",
        tools=[
            ToolSpec(
                name="List Processes By RAM",
                description="",
                parameters=[
                    {"name": "Sort By", "type": "nonsense", "description": "", "required": True},
                    {"name": "Sort By", "type": "integer", "description": "", "required": False},
                ],
            )
        ],
        required_imports=[],
    )

    normalized = mock_forge._normalize_spec_for_generation(spec, local_only_requested=False)

    assert normalized.skill_name == "skill_1_weird_skill"
    assert normalized.tools[0].name == "list_processes_by_ram"
    assert normalized.tools[0].parameters[0]["name"] == "sort_by"
    assert normalized.tools[0].parameters[0]["type"] == "string"
    assert normalized.tools[0].parameters[1]["name"] == "sort_by_2"


def test_finalize_generated_code_rewrites_manifest_from_spec(mock_forge):
    from neuralclaw.skills.forge import UseCaseSpec, ToolSpec

    spec = UseCaseSpec(
        skill_name="system_monitoring",
        skill_description="System monitoring",
        tools=[ToolSpec(name="get_system_overview", description="Overview", parameters=[])],
        required_imports=[],
    )
    code = """
from typing import Any
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition

async def wrong_handler(**_extra) -> dict[str, Any]:
    return {"ok": True}

def get_manifest():
    return SkillManifest(
        name="system_overview",
        description="Wrong manifest",
        tools=[
            ToolDefinition(name="wrong_handler", description="Wrong", handler=wrong_handler)
        ],
    )
"""

    finalized = mock_forge._finalize_generated_code(code, spec, local_only_requested=True)

    assert 'name="system_monitoring"' in finalized
    assert 'name="system_overview"' not in finalized
    assert 'name="get_system_overview"' in finalized
    assert "handler=wrong_handler" in finalized


@pytest.mark.asyncio
async def test_forge_attempts_fix_on_syntax_error_before_sandbox(tmp_path, mock_forge):
    from neuralclaw.cortex.action.sandbox import SandboxResult
    from neuralclaw.skills.forge import UseCaseSpec, ToolSpec

    mock_forge.USER_SKILLS_DIR = tmp_path
    mock_forge._run_use_case_interview = AsyncMock(return_value=UseCaseSpec(
        skill_name="syntax_skill",
        skill_description="Syntax skill",
        tools=[ToolSpec(name="ping", description="Ping", parameters=[])],
        required_imports=[],
    ))
    mock_forge._generate_skill_code = AsyncMock(return_value="async def ping(:\n    return {}\n")
    mock_forge._attempt_fix = AsyncMock(return_value=(
        "from typing import Any\n"
        "async def ping(**_extra) -> dict[str, Any]:\n"
        "    return {\"ok\": True}\n"
    ))
    mock_forge._sandbox_test = AsyncMock(return_value=SandboxResult(
        success=True,
        output="ok",
        error=None,
    ))

    result = await mock_forge._interview_then_generate(
        "Create a skill named syntax_skill that returns a ping response",
        "",
        "",
        "",
        "syntax_skill",
    )

    assert result.success is True
    assert mock_forge._attempt_fix.await_count == 1
    assert mock_forge._sandbox_test.await_count == 1


@pytest.mark.asyncio
async def test_forge_candidate_mode_persists_without_activation(tmp_path, mock_forge):
    from neuralclaw.cortex.action.sandbox import SandboxResult
    from neuralclaw.skills.forge import ToolSpec, UseCaseSpec
    from neuralclaw.skills.manifest import SkillManifest, ToolDefinition

    candidate_dir = tmp_path / "candidates"
    candidate_dir.mkdir()
    mock_forge.USER_SKILLS_DIR = tmp_path / "live"
    mock_forge._run_use_case_interview = AsyncMock(return_value=UseCaseSpec(
        skill_name="candidate_skill",
        skill_description="Candidate skill",
        tools=[ToolSpec(name="candidate_tool", description="Candidate tool", parameters=[])],
        required_imports=[],
    ))
    mock_forge._generate_skill_code = AsyncMock(return_value=(
        "from typing import Any\n"
        "from neuralclaw.skills.manifest import SkillManifest, ToolDefinition\n"
        "async def candidate_tool(**_extra) -> dict[str, Any]:\n"
        "    return {\"ok\": True}\n"
    ))
    mock_forge._sandbox_test = AsyncMock(return_value=SandboxResult(
        success=True,
        output="ok",
        error=None,
    ))
    mock_forge._build_manifest_from_spec = MagicMock(return_value=SkillManifest(
        name="candidate_skill",
        description="Candidate skill",
        tools=[ToolDefinition(name="candidate_tool", description="Candidate tool")],
    ))

    result = await mock_forge._interview_then_generate(
        "Create a skill named candidate_skill",
        activate=False,
        skills_dir=candidate_dir,
        registry_source="candidate",
    )

    assert result.success is True
    assert Path(result.file_path).parent == candidate_dir
    assert mock_forge._registry.hot_register.call_count == 0
