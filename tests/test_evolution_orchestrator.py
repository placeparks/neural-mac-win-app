from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from neuralclaw.bus.neural_bus import Event, EventType, NeuralBus
from neuralclaw.cortex.evolution.orchestrator import EvolutionOrchestrator
from neuralclaw.cortex.reasoning.deliberate import ConfidenceEnvelope
from neuralclaw.skills.forge import ForgeInputType, ForgeResult
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition
from neuralclaw.skills.registry import SkillRegistry


def _write_skill(path: Path, skill_name: str, tool_name: str) -> None:
    path.write_text(
        (
            "from typing import Any\n"
            "from neuralclaw.skills.manifest import SkillManifest, ToolDefinition\n\n"
            f"async def {tool_name}(**_extra) -> dict[str, Any]:\n"
            "    return {\"ok\": True}\n\n"
            "def get_manifest() -> SkillManifest:\n"
            "    return SkillManifest(\n"
            f"        name=\"{skill_name}\",\n"
            f"        description=\"{skill_name} description\",\n"
            "        tools=[\n"
            f"            ToolDefinition(name=\"{tool_name}\", description=\"{tool_name}\", handler={tool_name})\n"
            "        ],\n"
            "    )\n"
        ),
        encoding="utf-8",
    )


class _ForgeStub:
    def __init__(self, file_path: Path, manifest: SkillManifest) -> None:
        self.file_path = file_path
        self.manifest = manifest
        self.calls: list[dict[str, object]] = []

    async def forge_from_description(self, source: str, **kwargs):
        self.calls.append({"source": source, **kwargs})
        return ForgeResult(
            success=True,
            skill_name=self.manifest.name,
            input_type=ForgeInputType.DESCRIPTION,
            manifest=self.manifest,
            file_path=str(self.file_path),
        )


@pytest.mark.asyncio
async def test_orchestrator_promotes_probation_skill_after_real_success(tmp_path):
    bus = NeuralBus()
    registry = SkillRegistry()
    policy = SimpleNamespace(allowed_tools=[])
    candidate_dir = tmp_path / "candidates"
    user_skills_dir = tmp_path / "skills"
    candidate_dir.mkdir()
    user_skills_dir.mkdir()

    skill_file = candidate_dir / "pdf_table_extractor.py"
    _write_skill(skill_file, "pdf_table_extractor", "extract_pdf_tables")
    manifest = SkillManifest(
        name="pdf_table_extractor",
        description="Extract tables from PDFs",
        tools=[ToolDefinition(name="extract_pdf_tables", description="Extract PDF tables")],
    )
    forge = _ForgeStub(skill_file, manifest)
    orchestrator = EvolutionOrchestrator(
        bus=bus,
        registry=registry,
        forge=forge,
        policy_config=policy,
        db_path=tmp_path / "evolution.db",
        candidate_dir=candidate_dir,
        user_skills_dir=user_skills_dir,
    )
    await orchestrator.initialize()

    envelope = ConfidenceEnvelope(
        response="I can't extract PDF tables yet.",
        confidence=0.32,
        source="llm",
        uncertainty_factors=["missing capability"],
    )
    for _ in range(orchestrator.FAILURE_THRESHOLD):
        await orchestrator.record_response("Extract tables from a PDF invoice", envelope)

    if orchestrator._tasks:
        await asyncio.gather(*list(orchestrator._tasks))

    initiatives = await orchestrator.list_initiatives()
    assert initiatives[0]["state"] == "probation"
    assert registry.get_skill("pdf_table_extractor") is not None
    assert "extract_pdf_tables" in policy.allowed_tools

    event = Event(
        type=EventType.ACTION_COMPLETE,
        data={"skill": "extract_pdf_tables", "success": True},
        source="test",
    )
    await orchestrator._handle_action_complete(event)
    await orchestrator._handle_action_complete(event)

    initiatives = await orchestrator.list_initiatives()
    assert initiatives[0]["state"] == "promoted"
    assert (user_skills_dir / "pdf_table_extractor.py").exists()

    await orchestrator.close()


@pytest.mark.asyncio
async def test_orchestrator_quarantines_probation_skill_after_repeated_failures(tmp_path):
    bus = NeuralBus()
    registry = SkillRegistry()
    policy = SimpleNamespace(allowed_tools=[])
    candidate_dir = tmp_path / "candidates"
    user_skills_dir = tmp_path / "skills"
    candidate_dir.mkdir()
    user_skills_dir.mkdir()

    skill_file = candidate_dir / "crm_lookup.py"
    _write_skill(skill_file, "crm_lookup", "lookup_customer_record")
    manifest = SkillManifest(
        name="crm_lookup",
        description="Lookup CRM records",
        tools=[ToolDefinition(name="lookup_customer_record", description="Lookup customer record")],
    )
    forge = _ForgeStub(skill_file, manifest)
    orchestrator = EvolutionOrchestrator(
        bus=bus,
        registry=registry,
        forge=forge,
        policy_config=policy,
        db_path=tmp_path / "evolution.db",
        candidate_dir=candidate_dir,
        user_skills_dir=user_skills_dir,
    )
    await orchestrator.initialize()

    envelope = ConfidenceEnvelope(
        response="I don't have a CRM integration yet.",
        confidence=0.28,
        source="llm",
        uncertainty_factors=["missing integration"],
    )
    for _ in range(orchestrator.FAILURE_THRESHOLD):
        await orchestrator.record_response("Look up a customer in the CRM", envelope)

    if orchestrator._tasks:
        await asyncio.gather(*list(orchestrator._tasks))

    fail_event = Event(
        type=EventType.ACTION_COMPLETE,
        data={"skill": "lookup_customer_record", "success": False, "error": "401 unauthorized"},
        source="test",
    )
    await orchestrator._handle_action_complete(fail_event)
    await orchestrator._handle_action_complete(fail_event)

    initiatives = await orchestrator.list_initiatives()
    assert initiatives[0]["state"] == "quarantined"
    assert registry.get_skill("crm_lookup") is None

    await orchestrator.close()
