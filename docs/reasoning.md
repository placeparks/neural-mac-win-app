# 🧩 Reasoning System

NeuralClaw uses a **four-layer reasoning architecture** that automatically
routes queries to the appropriate complexity level. Simple questions get
instant answers; complex ones trigger multi-step planning with self-critique.

---

## The Four Layers

```
Input
  │
  ▼
┌──────────────┐    Match?     ┌─────────────────┐
│  Fast Path   │───── Yes ────▶│ Instant Response │
│ (reflexive)  │               └─────────────────┘
└──────┬───────┘
       │ No
       ▼
┌──────────────┐    Complex?   ┌─────────────────┐
│ Deliberative │───── No ─────▶│ LLM Single-Call  │
│  (standard)  │               └─────────────────┘
└──────┬───────┘
       │ Yes
       ▼
┌──────────────┐               ┌─────────────────┐
│  Reflective  │──────────────▶│ Plan → Execute → │
│ (multi-step) │               │ Critique → Revise│
└──────┬───────┘               └─────────────────┘
       │
       ▼ (background)
┌──────────────┐
│Meta-Cognitive │
│  (analysis)  │
└──────────────┘
```

---

## Layer 1: Fast Path (Reflexive)

**File:** `cortex/reasoning/fast_path.py`

Pattern-matched instant responses that don't need an LLM call.
Handles greetings, goodbyes, help commands, version queries, etc.

```python
from neuralclaw.cortex.reasoning.fast_path import FastPathReasoner

fast = FastPathReasoner(bus, agent_name="NeuralClaw")
result = await fast.try_fast_path(signal, memory_context)

if result:
    # Matched! Return instantly without LLM call
    print(result.content)
```

**Examples that trigger fast path:**
- "Hello" → Greeting response
- "Thanks" → Acknowledgment
- "What can you do?" → Capability overview
- `/help` → Help text

---

## Layer 2: Deliberative (Standard)

**File:** `cortex/reasoning/deliberate.py`

Standard LLM reasoning with full context. Constructs a rich prompt with:
- The user's message
- Retrieved memory context (episodes + facts)
- Agent persona and calibration modifiers
- Conversation history (last 20 messages)
- Available tool definitions

```python
from neuralclaw.cortex.reasoning.deliberate import DeliberativeReasoner

deliberate = DeliberativeReasoner(bus, persona="You are NeuralClaw...")
deliberate.set_provider(provider_router)

envelope = await deliberate.reason(
    signal=signal,
    memory_ctx=memory_context,
    tools=skill_tools,
    conversation_history=history[-20:],
)

print(envelope.response)
print(envelope.confidence)
```

---

## Layer 3: Reflective (Multi-Step)

**File:** `cortex/reasoning/reflective.py`

For complex queries, NeuralClaw uses a reflective process:

```
1. DECOMPOSE    → Break the problem into sub-tasks
2. EXECUTE      → Run each sub-task through deliberative reasoning
3. SELF-CRITIQUE → Evaluate the quality of each result
4. REVISE       → Fix any issues found during critique
5. SYNTHESIZE   → Combine sub-results into a final answer
```

The reflective layer automatically activates when:
- The query contains multiple questions
- The topic requires multi-step reasoning
- The intent classification flags high complexity

```python
from neuralclaw.cortex.reasoning.reflective import ReflectiveReasoner

reflective = ReflectiveReasoner(bus, deliberate_reasoner)

# Check if reflection is needed
if reflective.should_reflect(signal, memory_ctx):
    envelope = await reflective.reflect(
        signal=signal,
        memory_ctx=memory_ctx,
        tools=tools,
        conversation_history=history,
    )
```

---

## Layer 4: Meta-Cognitive (Analysis)

**File:** `cortex/reasoning/meta.py`

Runs in the background after each interaction. Analyzes NeuralClaw's own
performance to detect:

- **Success rates** — How often is the agent helpful?
- **Capability gaps** — What topics does it struggle with?
- **Performance trends** — Is it getting better or worse?

```python
from neuralclaw.cortex.reasoning.meta import MetaCognitive

meta = MetaCognitive(bus=bus)

# Record an interaction
meta.record_interaction(
    category="conversation",
    success=True,
    confidence=0.85,
)

# Run analysis when enough data is collected
if meta.should_analyze:
    report = await meta.analyze()
    print(f"Success rate: {report.overall_success_rate:.0%}")
    print(f"Capability gaps: {report.capability_gaps}")
```

---

## How Routing Works

The gateway (`gateway.py`) handles routing automatically:

1. **Try fast path** → If matched, return instantly
2. **Check procedural memory** → Look for matching workflow templates
3. **Check complexity** → `reflective.should_reflect()` evaluates the signal
4. **Route accordingly:**
   - Simple → Deliberative (single LLM call)
   - Complex → Reflective (multi-step with self-critique)
5. **Post-process:**
   - Store in memory
   - Run metabolism/distiller
   - Update meta-cognitive stats

You don't need to configure any of this — it happens automatically.

---

## Persona Modifiers

The [Evolution Cortex](evolution.md) calibrator adjusts reasoning behavior
based on learned preferences:

- **Formality** — Casual vs. professional tone
- **Verbosity** — Concise vs. detailed responses
- **Emoji usage** — Based on user interaction patterns

These modifiers are injected into the deliberative/reflective prompt
automatically.
