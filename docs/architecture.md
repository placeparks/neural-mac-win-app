# 🏗️ Architecture

NeuralClaw is built around a **five-cortex cognitive architecture** connected
by an asynchronous event bus. Every message flows through a biologically-inspired
pipeline: Perceive → Remember → Reason → Act → Evolve.

---

## The Five Cortices

```
                          ┌──────────────────────┐
                          │     Neural Bus       │
                          │  (async pub/sub)     │
                          └──────────┬───────────┘
                                     │
       ┌─────────────┬──────────────┼──────────────┬─────────────┐
       ▼             ▼              ▼              ▼             ▼
  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │PERCEPTION│  │  MEMORY  │  │REASONING │  │  ACTION  │  │EVOLUTION │
  │         │  │          │  │          │  │          │  │          │
  │ Intake  │  │ Episodic │  │Fast Path │  │ Sandbox  │  │Calibrator│
  │Classify │  │ Semantic │  │Deliberate│  │Capability│  │Distiller │
  │ Threat  │  │Procedural│  │Reflective│  │  Audit   │  │Synthesize│
  │ Screen  │  │Metabolism│  │          │  │          │  │          │
  └─────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘
```

### 1. Perception Cortex

Processes raw input before the LLM sees it.

| Module | File | Purpose |
|--------|------|---------|
| **Intake** | `cortex/perception/intake.py` | Normalize input into a `Signal` object |
| **Classifier** | `cortex/perception/classifier.py` | Zero-shot intent classification |
| **Threat Screener** | `cortex/perception/threat_screen.py` | Detect prompt injection, social engineering |

### 2. Memory Cortex

Three memory stores with a biological metabolism cycle.

| Module | File | Purpose |
|--------|------|---------|
| **Episodic** | `cortex/memory/episodic.py` | Conversation history (SQLite + FTS5) |
| **Semantic** | `cortex/memory/semantic.py` | Entity-relationship knowledge graph |
| **Procedural** | `cortex/memory/procedural.py` | Reusable workflows with trigger patterns |
| **Retrieval** | `cortex/memory/retrieval.py` | Unified search across all stores |
| **Metabolism** | `cortex/memory/metabolism.py` | Consolidation, strengthening, decay, pruning |

### 3. Reasoning Cortex

Multi-layer reasoning with automatic complexity routing.

| Module | File | Purpose |
|--------|------|---------|
| **Fast Path** | `cortex/reasoning/fast_path.py` | Pattern-matched instant responses |
| **Deliberative** | `cortex/reasoning/deliberate.py` | LLM-powered reasoning with context |
| **Reflective** | `cortex/reasoning/reflective.py` | Multi-step planning with self-critique |
| **Meta-Cognitive** | `cortex/reasoning/meta.py` | Performance analysis and capability gaps |

### 4. Action Cortex

Executes skills and enforces security boundaries.

| Module | File | Purpose |
|--------|------|---------|
| **Sandbox** | `cortex/action/sandbox.py` | Restricted subprocess for code execution |
| **Capabilities** | `cortex/action/capabilities.py` | Permission-based skill verification |
| **Audit** | `cortex/action/audit.py` | Full action logging for accountability |

### 5. Evolution Cortex

Self-improvement from every interaction.

| Module | File | Purpose |
|--------|------|---------|
| **Calibrator** | `cortex/evolution/calibrator.py` | Learn style preferences from corrections |
| **Distiller** | `cortex/evolution/distiller.py` | Extract episodic patterns → semantic facts |
| **Synthesizer** | `cortex/evolution/synthesizer.py` | Auto-generate skills from failure analysis |

---

## Neural Bus

The Neural Bus (`bus/neural_bus.py`) is the asynchronous backbone connecting
all cortices. It uses a pub/sub pattern with typed events:

```python
from neuralclaw.bus.neural_bus import NeuralBus, EventType

bus = NeuralBus()
await bus.start()

# Subscribe to events
bus.subscribe(EventType.SIGNAL_RECEIVED, my_handler)

# Publish events
await bus.publish(EventType.RESPONSE_READY, {"content": "Hello"}, source="gateway")
```

**Event Types:** `SIGNAL_RECEIVED`, `THREAT_DETECTED`, `MEMORY_STORED`,
`REASONING_STARTED`, `ACTION_COMPLETE`, `RESPONSE_READY`, `ERROR`, and more.

### Telemetry

`bus/telemetry.py` subscribes to all bus events and logs reasoning traces.
Enable/disable with `telemetry_stdout` in your config.

---

## Message Lifecycle

Every message flows through this pipeline in `gateway.py`:

```
1. PERCEPTION: Intake
   └── Normalize raw text → Signal object

2. PERCEPTION: Threat Screening
   └── Check for prompt injection / social engineering
   └── If blocked → return safety message

3. PERCEPTION: Intent Classification
   └── Classify intent (question, command, greeting, etc.)

4. MEMORY: Retrieve Context
   └── Search episodic + semantic memory for relevant context

5. REASONING: Fast Path
   └── Try pattern-matched instant response
   └── If matched → return immediately

6. REASONING: Procedural Memory Check
   └── Look for matching workflow templates

7. REASONING: Deliberative or Reflective
   └── Simple queries → Deliberative (single LLM call)
   └── Complex queries → Reflective (plan → execute → critique → revise)

8. POST-PROCESS
   └── Store in memory
   └── Tick metabolism + distiller
   └── Calibrate behavior preferences
   └── Meta-cognitive analysis
```

---

## Gateway

The `NeuralClawGateway` class (`gateway.py`) is the brain — it wires together
all cortices, providers, and channels. Key entry points:

```bash
neuralclaw chat       # Interactive terminal session
neuralclaw gateway    # Full multi-channel deployment
```

---

## Dashboard

The web dashboard provides live monitoring:

```bash
neuralclaw dashboard              # Default port 8080
neuralclaw dashboard --port 9090  # Custom port
```

**Features:**
- Live reasoning traces via WebSocket
- Memory statistics
- Swarm agent status
- Event bus telemetry
- Neural bus event log

The dashboard also starts automatically when you run `neuralclaw gateway`.
