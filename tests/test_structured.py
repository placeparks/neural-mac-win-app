"""Tests for structured output enforcement."""

import pytest
from pydantic import BaseModel

from neuralclaw.bus.neural_bus import NeuralBus
from neuralclaw.cortex.action.sandbox import SandboxResult
from neuralclaw.cortex.evolution.distiller import ExperienceDistiller
from neuralclaw.cortex.evolution.synthesizer import SkillSynthesizer
from neuralclaw.cortex.memory.episodic import EpisodicMemory
from neuralclaw.cortex.memory.procedural import ProceduralMemory
from neuralclaw.cortex.memory.retrieval import MemoryContext
from neuralclaw.cortex.memory.semantic import SemanticMemory
from neuralclaw.cortex.perception.intake import Signal
from neuralclaw.cortex.reasoning.deliberate import ConfidenceEnvelope
from neuralclaw.cortex.reasoning.reflective import ReflectiveReasoner
from neuralclaw.cortex.reasoning.structured import (
    ExtractedFact,
    GeneratedSkill,
    StructuredOutputError,
    StructuredReasoner,
    TaskDecomposition,
)


class DemoSchema(BaseModel):
    name: str
    score: int


class StubDeliberate:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def reason(
        self,
        signal,
        memory_ctx,
        tools=None,
        conversation_history=None,
        extra_system_sections=None,
    ):
        self.calls += 1
        response = self._responses.pop(0)
        return ConfidenceEnvelope(response=response, confidence=0.8, source="llm")


class StubStructured:
    async def extract(self, text, schema, instructions="", max_retries=3, extra_system_sections=None):
        return TaskDecomposition(
            sub_tasks=["collect requirements", "produce answer"],
            estimated_complexity="moderate",
            requires_tools=[],
        )


class FakeStructuredSynthesizer:
    async def reason_structured(
        self,
        signal,
        schema,
        memory_ctx=None,
        max_retries=3,
        use_json_mode=True,
        conversation_history=None,
        extra_system_sections=None,
    ):
        return GeneratedSkill(
            name="demo_skill",
            description="Demo generated skill",
            code='async def demo_skill(value):\n    return {"value": value}',
            test_cases=["demo"],
            required_imports=[],
            estimated_risk=0.1,
        )


class FakeStructuredDistiller:
    async def extract(self, text, schema, instructions="", max_retries=3, extra_system_sections=None):
        return ExtractedFact(
            subject="alice",
            predicate="uses",
            obj="python",
            confidence=0.82,
            source_quote="Alice uses Python",
        )


@pytest.mark.asyncio
async def test_reason_structured_valid_schema_passes():
    deliberate = StubDeliberate(['{"name":"alice","score":7}'])
    reasoner = StructuredReasoner(deliberate, NeuralBus())

    result = await reasoner.reason_structured(
        Signal(content="return structured data"),
        DemoSchema,
        MemoryContext(),
    )

    assert result.name == "alice"
    assert result.score == 7
    assert deliberate.calls == 1


@pytest.mark.asyncio
async def test_reason_structured_retries_on_validation_failure():
    deliberate = StubDeliberate([
        '{"name":"alice"}',
        '{"name":"alice","score":7}',
    ])
    reasoner = StructuredReasoner(deliberate, NeuralBus())

    result = await reasoner.reason_structured(
        Signal(content="return structured data"),
        DemoSchema,
        MemoryContext(),
        max_retries=2,
    )

    assert result.score == 7
    assert deliberate.calls == 2


@pytest.mark.asyncio
async def test_reason_structured_fails_after_max_retries():
    deliberate = StubDeliberate([
        '{"name":"alice"}',
        '{"name":"bob"}',
        '{"name":"charlie"}',
    ])
    reasoner = StructuredReasoner(deliberate, NeuralBus())

    with pytest.raises(StructuredOutputError) as exc_info:
        await reasoner.reason_structured(
            Signal(content="return structured data"),
            DemoSchema,
            MemoryContext(),
            max_retries=3,
        )

    assert "failed after 3 attempts" in str(exc_info.value)
    assert deliberate.calls == 3


@pytest.mark.asyncio
async def test_extract_uses_schema_validation():
    deliberate = StubDeliberate([
        '{"subject":"alice","predicate":"likes","obj":"python","confidence":0.8,"source_quote":"alice likes python"}',
    ])
    reasoner = StructuredReasoner(deliberate, NeuralBus())

    result = await reasoner.extract(
        text="Alice likes python.",
        schema=ExtractedFact,
        instructions="Extract one fact.",
    )

    assert result.subject == "alice"
    assert result.obj == "python"


@pytest.mark.asyncio
async def test_reflective_decompose_uses_structured_reasoner():
    deliberate = StubDeliberate([])
    reflective = ReflectiveReasoner(NeuralBus(), deliberate, structured=StubStructured())

    plan = await reflective._decompose(
        Signal(content="Research the market and summarize key trends."),
        MemoryContext(),
    )

    assert [task.description for task in plan.sub_tasks] == [
        "collect requirements",
        "produce answer",
    ]


@pytest.mark.asyncio
async def test_skill_synthesizer_uses_structured_generated_skill():
    class FakeSandbox:
        async def execute_python(self, code):
            assert "async def demo_skill" in code
            return SandboxResult(success=True, output="TEST_RESULT: ok")

    synthesizer = SkillSynthesizer(
        bus=NeuralBus(),
        sandbox=FakeSandbox(),
        structured=FakeStructuredSynthesizer(),
    )

    result = await synthesizer.synthesize_skill(
        name="demo_skill",
        description="Return a wrapped value",
        example_inputs=["hello"],
        expected_outputs=["{'value': 'hello'}"],
    )

    assert result.success is True
    assert "async def demo_skill" in result.code


@pytest.mark.asyncio
async def test_experience_distiller_uses_structured_fact_extraction(db_path):
    episodic = EpisodicMemory(db_path)
    semantic = SemanticMemory(db_path)
    procedural = ProceduralMemory(db_path)
    await episodic.initialize()
    await semantic.initialize()
    await procedural.initialize()

    try:
        await episodic.store("Alice uses Python for backend work.", source="test")
        distiller = ExperienceDistiller(
            episodic,
            semantic,
            procedural,
            distill_interval=1,
            structured=FakeStructuredDistiller(),
        )
        distiller.tick()

        report = await distiller.distill()
        triples = await semantic.get_relationships("alice")

        assert report.facts_extracted >= 1
        assert any(t.predicate == "uses" and t.obj == "python" for t in triples)
    finally:
        await episodic.close()
        await semantic.close()
        await procedural.close()
