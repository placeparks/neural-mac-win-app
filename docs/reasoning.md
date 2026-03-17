# Reasoning System

NeuralClaw uses layered reasoning with optional structure enforcement and
parallel tool execution.

## Layers

### Fast Path

Low-latency pattern-based responses for greetings, acknowledgments, and similar
simple interactions.

### Deliberative

Standard tool-using LLM reasoning. It now supports:

- conversation history
- identity prompt sections
- visual context
- parallel execution of sibling tool calls
- request-scoped audit metadata
- streaming generation paths

### Reflective

Multi-step decomposition, critique, and revision for complex tasks.

### Structured Output

`structured.py` wraps the underlying reasoner with Pydantic-enforced schemas.
Built-in schemas cover:

- generated skills
- extracted facts
- task decomposition

Structured output is used by reflective decomposition and the evolution paths.

## Parallel Tool Execution

When `policy.parallel_tool_execution = true`, multiple tool calls emitted in the
same model turn execute concurrently with stable ordering preserved when results
are fed back into the conversation.

## Streaming

When `features.streaming_responses = true`, simple deliberative paths can stream
tokens to adapters that support `send_stream()`. Output filtering forces
buffered delivery to preserve screening guarantees.

## Meta-Cognitive Analysis

`meta.py` tracks performance patterns over time and surfaces capability gaps and
success-rate trends.
