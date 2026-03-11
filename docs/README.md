# NeuralClaw Documentation

Version: `0.7.7`

Core docs for the current repository state:

| Guide | Description |
|---|---|
| [getting-started.md](getting-started.md) | install, session setup, first chat |
| [configuration.md](configuration.md) | config layout, providers, trust modes |
| [channels.md](channels.md) | channel adapters and route trust model |
| [security.md](security.md) | threat screening, policy, sandbox, audit |
| [architecture.md](architecture.md) | gateway, cortices, bus, runtime structure |
| [reasoning.md](reasoning.md) | fast path, deliberative, reflective, meta |
| [memory.md](memory.md) | episodic, semantic, procedural, metabolism |
| [skills.md](skills.md) | built-in skills and marketplace model |
| [swarm.md](swarm.md) | delegation, consensus, mesh |
| [federation.md](federation.md) | federation protocol and peers |
| [api-reference.md](api-reference.md) | Python-facing API overview |
| [troubleshooting.md](troubleshooting.md) | install, session, channel, build issues |

Current highlights:

- direct browser-session providers: `chatgpt_app`, `claude_app`
- API-backed providers: `openai`, `anthropic`, `openrouter`, `proxy`, `local`
- channel trust modes: `open`, `pair`, `bound`
- CLI session commands: `setup`, `status`, `login`, `open`, `diagnose`, `auth`, `refresh`, `repair`
