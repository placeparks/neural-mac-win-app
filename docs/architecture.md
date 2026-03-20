# Architecture

NeuralClaw is built around a five-cortex architecture connected by the
`NeuralBus`. The current runtime includes the roadmap extensions for vector
memory, identity, structured output, browser/desktop action, observability,
and output filtering.

## Cortices

### Perception

- `intake.py`: normalize inbound content into `Signal`
- `classifier.py`: classify intent
- `threat_screen.py`: pre-LLM threat screening
- `vision.py`: multimodal media understanding
- `output_filter.py`: output-side Prompt Armor v2

### Memory

- `episodic.py`: SQLite + FTS5 event memory
- `semantic.py`: fact graph
- `procedural.py`: reusable workflow memory
- `vector.py`: embedding similarity store
- `identity.py`: persistent user model and alias linking
- `retrieval.py`: unified retrieval and merging
- `metabolism.py`: consolidation and pruning

### Reasoning

- `fast_path.py`: low-latency reflexive responses
- `deliberate.py`: tool-using standard reasoning
- `reflective.py`: decomposition, critique, revision
- `structured.py`: schema-enforced structured extraction/generation
- `meta.py`: performance analysis and capability gaps

### Action

- `policy.py`: runtime tool policy and budgets
- `capabilities.py`: capability verification
- `audit.py`: forensic action replay
- `browser.py`: Playwright browser cortex
- `desktop.py`: desktop automation
- `sandbox.py`: restricted execution environment

### Evolution and Observability

- `calibrator.py`: preference learning
- `distiller.py`: episode-to-fact distillation
- `synthesizer.py`: skill generation
- `traceline.py`: request-level observability and export

## Gateway Responsibilities

`gateway.py`:

- initializes feature-gated subsystems lazily
- loads built-in skills
- binds providers and channels
- injects memory, identity, and prompt-armor context into reasoning
- manages streaming, response filtering, audit, and post-processing
- starts federation, dashboard, and bridge loops when enabled

## Message Lifecycle

1. trust evaluation
2. intake normalization
3. threat screening
4. optional vision/media context generation
5. memory retrieval
6. fast-path attempt
7. procedural match check
8. deliberative or reflective reasoning
9. output filtering
10. delivery, storage, audit, and evolution ticks

## SkillScout (Discovery Layer)

SkillScout is the discovery layer that sits between user intent and SkillForge.
When a user describes a capability they need, SkillScout searches five
registries in parallel (PyPI, GitHub, npm, MCP Registry, Claw Club), ranks the
results using LLM scoring with heuristic fallback (stars, maintenance recency,
license, relevance), and pipes the best candidate to `SkillForge.steal()`
automatically.

Key implementation details:

- `skills/scout.py` sits in front of `skills/forge.py`. The flow is:
  `scout.py` -> `forge.py` -> `registry.py`.
- Scout commands (`/scout ...`, `!scout ...`, `scout:`, `scout`) are
  intercepted in `gateway._on_channel_message()` alongside forge commands.
- The `scout_skill` tool is exposed to the agent so it can self-discover
  capabilities mid-conversation without user intervention.
- Registry searches run concurrently via `asyncio.gather()` and results are
  merged into a single ranked candidate list before the top pick is forwarded
  to SkillForge.

## SkillForge (Action Cortex Extension)

SkillForge extends the Action cortex with dynamic skill creation. Rather than
requiring manual skill development, it lets users describe a capability in
natural language and generates a working skill on the fly.

Key implementation details:

- `skills/forge.py` sits alongside the existing `skills/registry.py`. It
  receives a natural-language description (or a URL / code snippet), synthesizes
  a skill manifest, validates it through `StaticAnalyzer`, tests it inside
  `Sandbox`, and registers the result with the `SkillRegistry`.
- SkillForge reuses the existing `Sandbox` for isolated test execution, the
  `StaticAnalyzer` for security checks, and the configured LLM provider for
  code generation.
- `SkillHotLoader` watches `~/.neuralclaw/skills/` via asyncio polling and
  automatically registers any new or updated skill files it detects.
- Forge commands (`/forge ...`) are intercepted early in
  `gateway._on_channel_message()` before normal message processing, so they
  bypass the standard perception-reasoning pipeline.

## Bus and Telemetry

The `NeuralBus` is the integration contract between modules. `Telemetry` and
`Traceline` subscribe to the event flow for stdout logging and persistent traces.
