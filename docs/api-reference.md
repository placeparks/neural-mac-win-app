# 📘 API Reference

Quick reference for the most important NeuralClaw classes and methods.
For full details, see the individual module guides.

---

## Gateway

```python
from neuralclaw.gateway import NeuralClawGateway

gw = NeuralClawGateway(config=None)   # Uses default config if None
await gw.initialize()                  # Initialize all subsystems
await gw.start()                       # Start gateway + channels
await gw.stop()                        # Graceful shutdown
await gw.run_forever()                 # Run until interrupted

# Process a single message through the full pipeline
response = await gw.process_message(
    content="Hello",
    author_id="user",
    author_name="User",
    channel_id="cli",
    channel_type_name="CLI",
)
```

---

## Configuration

```python
from neuralclaw.config import (
    load_config,           # Load from ~/.neuralclaw/config.toml
    save_default_config,   # Write default config if missing
    ensure_dirs,           # Create config/data/log dirs
    get_api_key,           # Get key from env var or keychain
    set_api_key,           # Store key in OS keychain
)

config = load_config()
config.name                    # "NeuralClaw"
config.persona                 # Agent persona string
config.primary_provider        # ProviderConfig
config.fallback_providers      # list[ProviderConfig]
config.memory                  # MemoryConfig
config.security                # SecurityConfig
config.channels                # list[ChannelConfig]
```

---

## Memory

```python
from neuralclaw.cortex.memory.episodic import EpisodicMemory
from neuralclaw.cortex.memory.semantic import SemanticMemory
from neuralclaw.cortex.memory.procedural import ProceduralMemory
from neuralclaw.cortex.memory.retrieval import MemoryRetriever
from neuralclaw.cortex.memory.metabolism import MemoryMetabolism

# Episodic
episodic = EpisodicMemory(db_path)
await episodic.initialize()
await episodic.store(content, source, author, importance)
results = await episodic.search(query, limit=10)
await episodic.close()

# Semantic
semantic = SemanticMemory(db_path)
await semantic.initialize()
await semantic.store(entity, relation, value, confidence)
facts = await semantic.query(entity)
await semantic.close()

# Procedural
procedural = ProceduralMemory(db_path, bus)
await procedural.initialize()
await procedural.store(name, trigger_patterns, steps, source)
matches = await procedural.find_matching(query)
await procedural.close()

# Retrieval (unified search)
retriever = MemoryRetriever(episodic, semantic, bus, max_episodes=10, max_facts=5)
context = await retriever.retrieve(query)
```

---

## Perception

```python
from neuralclaw.cortex.perception.intake import PerceptionIntake, ChannelType
from neuralclaw.cortex.perception.classifier import IntentClassifier
from neuralclaw.cortex.perception.threat_screen import ThreatScreener

# Intake
intake = PerceptionIntake(bus)
signal = await intake.process(content, author_id, author_name, channel_type, channel_id)

# Classifier
classifier = IntentClassifier(bus)
intent = await classifier.classify(signal)

# Threat Screening
screener = ThreatScreener(bus, threat_threshold=0.7, block_threshold=0.9)
result = await screener.screen(signal)
result.score       # 0.0 - 1.0
result.blocked     # bool
result.reasons     # list[str]
```

---

## Reasoning

```python
from neuralclaw.cortex.reasoning.fast_path import FastPathReasoner
from neuralclaw.cortex.reasoning.deliberate import DeliberativeReasoner
from neuralclaw.cortex.reasoning.reflective import ReflectiveReasoner
from neuralclaw.cortex.reasoning.meta import MetaCognitive

# Fast Path
fast = FastPathReasoner(bus, agent_name="NeuralClaw")
result = await fast.try_fast_path(signal, memory_ctx)

# Deliberative
deliberate = DeliberativeReasoner(bus, persona)
deliberate.set_provider(provider_router)
envelope = await deliberate.reason(signal, memory_ctx, tools, conversation_history)

# Reflective
reflective = ReflectiveReasoner(bus, deliberate_reasoner)
if reflective.should_reflect(signal, memory_ctx):
    envelope = await reflective.reflect(signal, memory_ctx, tools, conversation_history)

# Meta-Cognitive
meta = MetaCognitive(bus=bus)
meta.record_interaction(category, success, confidence)
report = await meta.analyze()
```

---

## Evolution

```python
from neuralclaw.cortex.evolution.calibrator import BehavioralCalibrator
from neuralclaw.cortex.evolution.distiller import ExperienceDistiller
from neuralclaw.cortex.evolution.synthesizer import SkillSynthesizer

# Calibrator
calibrator = BehavioralCalibrator(bus=bus)
await calibrator.initialize()
await calibrator.process_implicit_signal(user_msg_length, agent_msg_length)
modifiers = calibrator.preferences.to_persona_modifiers()

# Distiller
distiller = ExperienceDistiller(episodic, semantic, procedural, bus)
if distiller.should_distill:
    await distiller.distill()

# Synthesizer
synth = SkillSynthesizer(bus=bus)
synth.set_provider(provider_router)
await synth.synthesize_skill(task_description, failure_context)
```

---

## Swarm

```python
from neuralclaw.swarm.delegation import DelegationChain, DelegationContext, DelegationPolicy
from neuralclaw.swarm.consensus import ConsensusProtocol, ConsensusStrategy
from neuralclaw.swarm.mesh import AgentMesh

# Delegation
chain = DelegationChain(bus=bus, policy=DelegationPolicy())
chain.register_executor(agent_name, async_handler)
result = await chain.delegate(agent_name, DelegationContext(task_description="..."))
results = await chain.delegate_parallel([(name, ctx), ...])

# Consensus
consensus = ConsensusProtocol(chain, bus=bus)
result = await consensus.seek_consensus(task, strategy, agent_names, min_agents, timeout)

# Mesh
mesh = AgentMesh(bus=bus)
mesh.register(name, description, capabilities, handler, endpoint, max_concurrent)
agents = mesh.discover(capability=None, available_only=True)
response = await mesh.send(from_agent, to_agent, content, message_type, payload, timeout)
responses = await mesh.broadcast(from_agent, content, capability_filter)
status = mesh.get_mesh_status()
```

---

## Federation

```python
from neuralclaw.swarm.federation import FederationProtocol

fed = FederationProtocol(node_name, bus=None, port=8100)
await fed.start()                                    # Start HTTP server
await fed.stop()                                     # Stop server
success = await fed.join_federation(seed_endpoint)   # Connect to peer
response = await fed.send_message(node_id, content, message_type, payload, timeout)
responses = await fed.broadcast(content, capability_filter, payload)
await fed.send_heartbeats()                          # Ping all peers

# Registry
fed.registry.register(name, endpoint, capabilities, version, region, trust_score)
fed.registry.find_by_capability(capability)
fed.registry.find_by_region(region)
fed.registry.get_status()
fed.registry.blacklist(node_id)
```

---

## Neural Bus

```python
from neuralclaw.bus.neural_bus import NeuralBus, EventType

bus = NeuralBus()
await bus.start()
await bus.stop()

bus.subscribe(event_type, async_handler)
bus.subscribe_all(async_handler)
await bus.publish(event_type, data, source)
```

---

## Skills

```python
from neuralclaw.skills.registry import SkillRegistry
from neuralclaw.skills.marketplace import SkillMarketplace
from neuralclaw.skills.economy import SkillEconomy

# Registry
registry = SkillRegistry()
registry.load_builtins()
registry.count           # Number of skills
registry.tool_count      # Number of tools
tools = registry.get_all_tools()

# Marketplace
mp = SkillMarketplace()
package, findings = mp.publish(name, version, author, description, code, private_key)
mp.install(skill_name)

# Economy
econ = SkillEconomy()
econ.register_author(author_id, display_name)
econ.register_skill(skill_name, author_id)
econ.record_usage(skill_name, user_id, success)
econ.rate_skill(skill_name, rater_id, score, review)
econ.get_trending()
econ.get_author_leaderboard()
```

---

## SkillForge

```python
from neuralclaw.skills.forge import (
    SkillForge,
    ForgeInputType,
    ForgeResult,
    SkillHotLoader,
    detect_forge_command,
)

# Constructor
forge = SkillForge(provider, sandbox, registry, bus, model="claude-sonnet-4-20250514")

# Main entry point — accepts a natural-language description, URL, or code snippet.
# use_case is an optional string that constrains the generated skill's scope.
result: ForgeResult = await forge.steal(source="send SMS reminders via Twilio", use_case="appointment reminders")

# ForgeInputType enum — classifies the source argument
ForgeInputType.DESCRIPTION      # plain-language request
ForgeInputType.URL              # URL to inspect and wrap
ForgeInputType.CODE_SNIPPET     # raw code to package as a skill

# ForgeResult dataclass
result.success          # bool
result.skill_name       # str
result.manifest         # dict — full skill manifest
result.tools_created    # int
result.warnings         # list[str]
result.error            # str | None

# Hot loader — watches ~/.neuralclaw/skills/ for new/updated files
loader = SkillHotLoader(registry, bus)
await loader.start()    # Begin asyncio polling loop
await loader.stop()     # Stop watching

# Channel command parser — detects /forge commands in message content
parsed = detect_forge_command(content)
# Returns None if no forge command found, otherwise a dict with
# {"source": str, "use_case": str | None}

# Registry method — register a skill manifest at runtime without restart
registry.hot_register(manifest)
```
