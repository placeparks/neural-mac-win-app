# 🧬 Evolution Cortex

The Evolution Cortex enables NeuralClaw to **self-improve** with every
interaction. It consists of three modules that learn your preferences,
extract patterns from experience, and auto-generate new skills.

---

## Overview

| Module | Purpose | Trigger |
|--------|---------|---------|
| **Calibrator** | Learn communication style preferences | Every interaction |
| **Distiller** | Extract patterns from episodes → semantic facts | Periodic (automatic) |
| **Synthesizer** | Auto-generate skills from failure analysis | On repeated failures |

---

## Behavioral Calibrator

**File:** `cortex/evolution/calibrator.py`

Learns your communication preferences from corrections and interaction patterns.

### What It Tracks

| Preference | How It's Learned |
|------------|-----------------|
| **Formality** | Analyzes your message style (casual vs. professional) |
| **Verbosity** | Tracks if you prefer short or detailed responses |
| **Emoji usage** | Observes your emoji patterns |
| **Tone** | Learns from explicit corrections ("be more casual") |

### How It Works

1. After each interaction, the calibrator records an **implicit signal**
   (message length ratio, timestamp, etc.)
2. If you correct the agent ("be shorter", "more formal"), it records an
   **explicit correction**
3. Over time, it builds a preference profile
4. These preferences are injected as **persona modifiers** into the
   reasoning prompt

### Python API

```python
from neuralclaw.cortex.evolution.calibrator import BehavioralCalibrator

calibrator = BehavioralCalibrator(bus=bus)
await calibrator.initialize()

# Process implicit signals (automatic in gateway)
await calibrator.process_implicit_signal(
    user_msg_length=50,
    agent_msg_length=200,
)

# Process explicit corrections
await calibrator.process_correction(
    user_feedback="Be more concise next time",
    original_response="...",
)

# Get current preferences
prefs = calibrator.preferences
print(f"Formality: {prefs.formality}")
print(f"Verbosity: {prefs.verbosity}")

# Get persona modifiers (injected into prompts)
modifiers = prefs.to_persona_modifiers()
```

---

## Experience Distiller

**File:** `cortex/evolution/distiller.py`

Extracts recurring patterns from episodic memory and converts them into
semantic knowledge.

### How It Works

```
Episodic Memory (raw conversations)
        │
        ▼ Pattern Detection
Semantic Memory (facts & relationships)
        │
        ▼ Workflow Extraction
Procedural Memory (reusable workflows)
```

1. **Scans** episodic memory for repeated topics or entities
2. **Extracts** facts → stores in semantic memory
3. **Identifies** recurring task patterns → stores as procedural workflows

### Python API

```python
from neuralclaw.cortex.evolution.distiller import ExperienceDistiller

distiller = ExperienceDistiller(
    episodic, semantic, procedural, bus
)

# Check if distillation is due
if distiller.should_distill:
    await distiller.distill()
```

Distillation runs automatically in the gateway's post-processing step.

---

## Skill Synthesizer

**File:** `cortex/evolution/synthesizer.py`

When NeuralClaw repeatedly fails at a task, the synthesizer can
**auto-generate a new skill** via LLM code generation and sandbox testing.

### How It Works

1. Detects repeated failures on similar tasks
2. Analyzes the failure pattern
3. Uses the LLM to generate skill code
4. Tests the skill in the sandbox
5. If it passes, registers it in the skill registry

### Python API

```python
from neuralclaw.cortex.evolution.synthesizer import SkillSynthesizer

synth = SkillSynthesizer(bus=bus)
synth.set_provider(provider_router)

# Trigger synthesis for a failed task
await synth.synthesize_skill(
    task_description="Convert temperatures between Celsius and Fahrenheit",
    failure_context="No built-in skill for temperature conversion",
)
```

---

## How Evolution Fits In

All three modules run automatically in the gateway's post-processing
pipeline (after every response):

```python
# gateway.py _post_process()

# 1. Tick metabolism + distiller clocks
self._metabolism.tick()
self._distiller.tick()

# 2. Record implicit calibration signal
await self._calibrator.process_implicit_signal(...)

# 3. Run metabolism if due
if self._metabolism.should_run:
    await self._metabolism.run_cycle()

# 4. Run distillation if due
if self._distiller.should_distill:
    await self._distiller.distill()
```

You don't need to configure anything — evolution happens automatically.
