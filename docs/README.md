# NeuralClaw Documentation

Version: `1.0.0`

This doc set reflects the current repo state after the full `AGENT.md`
roadmap implementation.

## Recommended Reading Order

| Guide | Description |
|---|---|
| [getting-started.md](getting-started.md) | install, bootstrap, first-run flow |
| [configuration.md](configuration.md) | config sections, feature flags, auth, extras |
| [architecture.md](architecture.md) | gateway, cortices, bus, runtime wiring |
| [memory.md](memory.md) | episodic, semantic, procedural, vector, identity |
| [reasoning.md](reasoning.md) | fast-path, deliberative, reflective, structured |
| [skills.md](skills.md) | built-ins, manifests, capability model |
| [channels.md](channels.md) | adapters, trust, streaming, Discord voice |
| [security.md](security.md) | threat screening, output filtering, audit, policy |
| [swarm.md](swarm.md) | delegation, consensus, mesh |
| [federation.md](federation.md) | native federation and A2A endpoints |
| [api-reference.md](api-reference.md) | Python-facing API overview |
| [troubleshooting.md](troubleshooting.md) | install, auth, provider, and channel issues |

## Current Highlights

- **computer use**: screenshot → vision analysis → click/type/hotkey with
  remote control via Telegram (images sent as photos)
- **dynamic self-awareness**: capability-driven system prompt, tool awareness
  injection, anti-refusal directives
- **GPT-5 / Claude 4.6 support**: updated provider defaults and API compat
- vector memory, persistent user identity, and smart importance scoring
- vision perception and browser multi-step planning
- streaming responses and structured output enforcement
- Google Workspace and Microsoft 365 builtin skills
- traceline observability, Prompt Armor v2, and audit replay
- A2A-compatible federation agent cards and task APIs

## Repo-local Handoff

Implementation state and verification history are tracked in:

- [agent-implementation-notes.md](agent-implementation-notes.md)
