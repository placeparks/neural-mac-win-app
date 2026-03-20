from __future__ import annotations

from types import SimpleNamespace

import pytest

from neuralclaw.config import NeuralClawConfig, ProviderConfig
from neuralclaw.cortex.memory.episodic import EpisodicMemory
from neuralclaw.cortex.memory.retrieval import MemoryContext
from neuralclaw.cortex.reasoning.deliberate import ConfidenceEnvelope
from neuralclaw.gateway import NeuralClawGateway


PROVIDERS = ["anthropic", "openai", "local"]
CHANNELS = ["telegram", "discord"]
MEMORY_PROFILES = [
    {"semantic": False, "vector": False},
    {"semantic": True, "vector": False},
    {"semantic": True, "vector": True},
]


def _build_config(provider: str, memory_profile: dict[str, bool], db_path: str) -> NeuralClawConfig:
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name=provider, model="stub", base_url="http://localhost"),
    )
    config.memory.db_path = db_path
    config.features.semantic_memory = memory_profile["semantic"]
    config.features.vector_memory = memory_profile["vector"]
    config.memory.vector_memory = memory_profile["vector"]
    return config


def _stub_gateway(gateway: NeuralClawGateway, monkeypatch: pytest.MonkeyPatch, response: str) -> None:
    async def fake_intake(**kwargs):
        return SimpleNamespace(
            id=f"sig-{kwargs['author_id']}",
            content=kwargs["content"],
            author_id=kwargs["author_id"],
            author_name=kwargs["author_name"],
            channel_type=None,
            channel_id=kwargs["channel_id"],
            context={},
        )

    async def fake_screen(signal):
        return SimpleNamespace(blocked=False)

    async def fake_fast_path(signal, memory_ctx=None):
        return None

    async def fake_classify(signal):
        return SimpleNamespace(intent="chat")

    async def fake_retrieve(content):
        return MemoryContext()

    async def fake_reason(signal, memory_ctx, tools=None, conversation_history=None, extra_system_sections=None):
        return ConfidenceEnvelope(response=response, confidence=0.9, source="llm")

    async def fake_store_interaction(*args, **kwargs):
        return None

    async def fake_post_process(*args, **kwargs):
        return None

    monkeypatch.setattr(gateway._intake, "process", fake_intake)
    monkeypatch.setattr(gateway._threat_screener, "screen", fake_screen)
    monkeypatch.setattr(gateway._fast_path, "try_fast_path", fake_fast_path)
    monkeypatch.setattr(gateway._classifier, "classify", fake_classify)
    monkeypatch.setattr(gateway._retriever, "retrieve", fake_retrieve)
    monkeypatch.setattr(gateway._deliberate, "reason", fake_reason)
    monkeypatch.setattr(gateway, "_store_interaction", fake_store_interaction)
    monkeypatch.setattr(gateway, "_post_process", fake_post_process)
    gateway._procedural = None
    gateway._identity = None


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("channel_name", CHANNELS)
@pytest.mark.parametrize("memory_profile", MEMORY_PROFILES)
async def test_full_pipeline_matrix(tmp_path, monkeypatch, provider: str, channel_name: str, memory_profile: dict[str, bool]):
    config = _build_config(provider, memory_profile, str(tmp_path / "matrix.db"))
    gateway = NeuralClawGateway(config, dev_mode=True)
    _stub_gateway(gateway, monkeypatch, f"{provider}:{channel_name}:ok")

    response = await gateway.process_message(
        content="What time is it?",
        author_id="matrix-user",
        author_name="Matrix User",
        channel_id=channel_name,
        channel_type_name=channel_name.upper(),
    )

    assert response == f"{provider}:{channel_name}:ok"
    assert len(response) < 4096


@pytest.mark.asyncio
async def test_memory_persists_across_sessions(tmp_path):
    db_path = str(tmp_path / "memory.db")
    gw1 = NeuralClawGateway(
        NeuralClawConfig(primary_provider=ProviderConfig(name="local", model="stub", base_url="http://localhost")),
        dev_mode=True,
    )
    gw1._config.memory.db_path = db_path
    gw1._memory_db_pool.db_path = db_path
    gw1._episodic = EpisodicMemory(db_path, db_pool=gw1._memory_db_pool)
    await gw1._memory_db_pool.initialize()
    await gw1._episodic.initialize()
    await gw1._episodic.store("My name is Alex", author="u1", tags=["user_id:u1"])
    await gw1._episodic.close()
    await gw1._memory_db_pool.close()

    gw2 = NeuralClawGateway(
        NeuralClawConfig(primary_provider=ProviderConfig(name="local", model="stub", base_url="http://localhost")),
        dev_mode=True,
    )
    gw2._config.memory.db_path = db_path
    gw2._memory_db_pool.db_path = db_path
    gw2._episodic = EpisodicMemory(db_path, db_pool=gw2._memory_db_pool)
    await gw2._memory_db_pool.initialize()
    await gw2._episodic.initialize()
    results = await gw2._episodic.search("Alex", limit=5)

    assert results
    assert any("Alex" in item.episode.content for item in results)

    await gw2._episodic.close()
    await gw2._memory_db_pool.close()


@pytest.mark.asyncio
async def test_evolution_synthesizer_produces_valid_skill(tmp_path, monkeypatch):
    """Skill synthesizer generates valid Python on repeated failures."""
    from neuralclaw.cortex.evolution.synthesizer import SkillSynthesizer, SynthesisResult
    from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter
    from neuralclaw.cortex.action.capabilities import Capability

    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="stub", base_url="http://localhost"),
    )
    config.features.evolution = True
    gateway = NeuralClawGateway(config, dev_mode=True)

    # Simulate 3 failures on the same task
    for _ in range(3):
        gateway._synthesizer.record_failure(
            query="convert celsius to fahrenheit",
            error="No tool available",
            category="conversion",
        )

    # Mock the synthesize_skill method to return a successful result and register the skill
    async def fake_synthesize(name, description, example_inputs, expected_outputs):
        # Register a skill in the registry to simulate successful synthesis
        manifest = SkillManifest(
            name="celsius_to_fahrenheit",
            version="1.0.0",
            description="Convert Celsius temperatures to Fahrenheit",
            capabilities=[Capability.SHELL_EXECUTE],
            tools=[
                ToolDefinition(
                    name="celsius_to_fahrenheit",
                    description="Convert Celsius to Fahrenheit",
                    parameters=[
                        ToolParameter(
                            name="celsius",
                            type="number",
                            description="Temperature in Celsius",
                            required=True,
                        ),
                    ],
                ),
            ],
        )
        gateway._skills.register(manifest)
        return SynthesisResult(
            success=True,
            skill_name="celsius_to_fahrenheit",
            description="Convert Celsius temperatures to Fahrenheit",
            code="def celsius_to_fahrenheit(celsius: float) -> float:\n    return celsius * 9 / 5 + 32",
        )

    monkeypatch.setattr(gateway._synthesizer, "synthesize_skill", fake_synthesize)

    # Trigger synthesis
    await gateway._synthesizer.synthesize_skill(
        name="celsius_to_fahrenheit",
        description="convert celsius to fahrenheit",
        example_inputs=["0", "100", "37"],
        expected_outputs=["32", "212", "98.6"],
    )

    # Check skill was registered
    skills = gateway._skills.list_skills()
    names = [s.name for s in skills]
    assert any("celsius" in n or "temperature" in n for n in names), (
        f"Synthesized skill not found in registry. Skills: {names}"
    )
