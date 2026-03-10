<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+"/>
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="MIT License"/>
  <img src="https://img.shields.io/badge/phase-4%20Domination-blueviolet?style=flat-square" alt="Phase 4"/>
  <img src="https://img.shields.io/badge/architecture-cognitive%20cortices-blueviolet?style=flat-square" alt="Architecture"/>
</p>

<h1 align="center">🧠 NeuralClaw</h1>

<p align="center">
  <strong>The Self-Evolving Cognitive Agent Framework</strong><br/>
  <em>Perceive · Remember · Reason · Evolve · Act</em>
</p>

<p align="center">
  A next-generation autonomous agent that introduces cognitive memory architecture,<br/>
  self-evolving intelligence, and security-first design.
</p>

---

## 📖 Documentation

Comprehensive guides are available in the [`docs/`](docs/README.md) directory:

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/getting-started.md) | Install, configure, first chat |
| [Architecture](docs/architecture.md) | Five Cortices, Neural Bus, pipeline |
| [Channels](docs/channels.md) | Telegram, Discord, Slack, WhatsApp, Signal |
| [Memory](docs/memory.md) | Episodic, Semantic, Procedural + Metabolism |
| [Reasoning](docs/reasoning.md) | Fast-path → Deliberative → Reflective → Meta |
| [Swarm & Multi-Agent](docs/swarm.md) | Delegation, Consensus, Agent Mesh |
| [Federation](docs/federation.md) | Cross-network agents, trust scoring |
| [Skills](docs/skills.md) | Builtins, Marketplace, Economy |
| [Security](docs/security.md) | Threat screening, sandbox, audit |
| [Configuration](docs/configuration.md) | TOML config, env vars, keychain |
| [API Reference](docs/api-reference.md) | Python API quick reference |
| [Troubleshooting](docs/troubleshooting.md) | Common issues, debugging |

---

## ✨ What Makes NeuralClaw Different

| Problem in existing agents | NeuralClaw's answer |
|---|---|
| Flat markdown memory | **Cognitive Tri-Store** — Episodic + Semantic + Procedural memory with metabolism (consolidation, decay, strengthening) |
| Dumb reactive loops | **4-Layer Reasoning** — Reflexive fast-path → Deliberative → Reflective self-critique → Meta-cognitive evolution |
| No self-improvement | **Evolution Cortex** — Behavioral calibration, experience distillation, automatic skill synthesis |
| Skill supply-chain attacks | **Cryptographic Marketplace** — Ed25519 signing, static analysis, risk scoring |
| Single-channel bots | **5 Channel Adapters** — Telegram, Discord, Slack, WhatsApp, Signal |
| No security model | **Zero-Trust by Default** — Pre-LLM threat screening, capability-based permissions, sandboxed execution |

---

## 🏗️ Architecture: The Five Cortices

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

Every cortex communicates through the **Neural Bus** — an asynchronous event-driven backbone with full reasoning trace telemetry.

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.12+**
- At least one LLM provider (OpenAI, Anthropic, OpenRouter, or local Ollama)

### Installation

```bash
# Install from PyPI
pip install neuralclaw

# Or install with all channel adapters
pip install neuralclaw[all-channels]

# Or install from source for development
git clone https://github.com/placeparks/neuralclaw.git
cd neuralclaw
pip install -e ".[dev]"
```

### Setup

```bash
# Run the interactive setup wizard — configures LLM providers & stores keys securely
neuralclaw init

# Configure messaging channels (Telegram, Discord, Slack, WhatsApp, Signal)
neuralclaw channels setup
```

### Usage

```bash
# Interactive terminal chat
neuralclaw chat

# Start the full gateway with all configured channels
neuralclaw gateway

# Check configuration and status
neuralclaw status

# View configured channels
neuralclaw channels list
```

---

## 🔑 LLM Provider Setup

NeuralClaw supports **multiple LLM providers** with automatic fallback routing:

| Provider | Model | Setup |
|----------|-------|-------|
| **OpenAI** | GPT-4o, GPT-4o-mini | API key from [platform.openai.com](https://platform.openai.com) |
| **Anthropic** | Claude 3.5 Sonnet | API key from [console.anthropic.com](https://console.anthropic.com) |
| **OpenRouter** | Multi-model access | API key from [openrouter.ai](https://openrouter.ai) |
| **Local (Ollama)** | Llama 3, Mistral, etc. | No key needed — runs on `localhost:11434` |

All API keys are stored in your **OS keychain** (Windows Credential Store / macOS Keychain / Linux Secret Service) — never in plaintext config files.

---

## 📡 Channel Adapters

| Channel | Method | Dependencies |
|---------|--------|-------------|
| **Telegram** | Bot API via `python-telegram-bot` | Token from @BotFather |
| **Discord** | Bot via `discord.py` | Token from Developer Portal |
| **Slack** | Socket Mode via `slack-bolt` | Bot + App tokens |
| **WhatsApp** | `whatsapp-web.js` Node.js bridge | Node.js 18+ required |
| **Signal** | `signal-cli` JSON-RPC bridge | signal-cli installed |

```bash
# Interactive guided setup for all channels
neuralclaw channels setup
```

---

## 🧬 Intelligence Layer (Phase 2)

### Memory Metabolism

Memories have a biological lifecycle — they aren't just appended:

```
Formation → Consolidation → Strengthening/Decay → Retrieval → Reconsolidation
```

- **Consolidation** — Repeated episodic events merge into semantic knowledge
- **Strengthening** — Frequently accessed memories gain importance
- **Decay** — Stale, unused memories gradually lose relevance
- **Pruning** — Very low-importance memories are archived

### Reflective Reasoning

Complex queries trigger multi-step planning with self-critique:

```
Decompose → Execute sub-tasks → Self-critique → Revise plan → Synthesize answer
```

### Evolution Cortex

| Module | Function |
|--------|----------|
| **Calibrator** | Learns your style preferences (formality, verbosity, emoji) from corrections and interaction patterns |
| **Distiller** | Extracts recurring patterns from episodes → semantic facts + procedural workflows |
| **Synthesizer** | Auto-generates new skills from repeated task failures via LLM code generation + sandbox testing |

### Skill Marketplace

```python
from neuralclaw.skills.marketplace import SkillMarketplace

mp = SkillMarketplace()
pkg, findings = mp.publish("my_skill", "1.0", "author", "desc", code, private_key)
# Static analysis scans for: shell exec, network exfil, path traversal, obfuscation
# Risk score: 0.0 (safe) → 1.0 (dangerous)
```

---

## 📁 Project Structure

```
neuralclaw/
├── bus/                    # Neural Bus (async event backbone)
│   ├── neural_bus.py       #   Event types, pub/sub, correlation
│   └── telemetry.py        #   Reasoning trace logging
├── channels/               # Channel Adapters
│   ├── protocol.py         #   Adapter interface
│   ├── telegram.py         #   Telegram bot
│   ├── discord_adapter.py  #   Discord bot
│   ├── slack.py            #   Slack (Socket Mode)
│   ├── whatsapp.py         #   WhatsApp (web.js bridge)
│   └── signal_adapter.py   #   Signal (signal-cli bridge)
├── cortex/                 # Cognitive Cortices
│   ├── perception/         #   Intake, classifier, threat screen
│   ├── memory/             #   Episodic, semantic, procedural, metabolism
│   ├── reasoning/          #   Fast-path, deliberative, reflective
│   ├── action/             #   Sandbox, capabilities, policy, network, audit
│   └── evolution/          #   Calibrator, distiller, synthesizer
├── providers/              # LLM Provider Abstraction
│   ├── router.py           #   Multi-provider routing + fallback
│   ├── openai.py           #   OpenAI connector
│   ├── anthropic.py        #   Anthropic connector
│   ├── openrouter.py       #   OpenRouter connector
│   └── local.py            #   Ollama / local models
├── skills/                 # Skill Framework
│   ├── registry.py         #   Discovery and loading
│   ├── manifest.py         #   Skill declarations
│   ├── marketplace.py      #   Signed distribution + static analysis
│   └── builtins/           #   Web search, file ops, code exec, calendar
├── cli.py                  # Rich-powered CLI
├── config.py               # TOML config + OS keychain secrets
└── gateway.py              # Orchestration engine (the brain)
```

---

## 🛡️ Security Model

NeuralClaw follows a **zero-trust, security-first** design:

- **Pre-LLM Threat Screening** — Prompt injection and social engineering detection happens *before* the LLM sees the message
- **Capability-Based Permissions** — Skills declare required capabilities; the verifier enforces them
- **Sandboxed Execution** — Code execution runs in a restricted subprocess with resource limits
- **Cryptographic Skill Verification** — Marketplace skills are HMAC-signed and statically analyzed
- **OS Keychain Integration** — API keys stored in Windows Credential Store / macOS Keychain, never in files
- **Audit Logging** — Every action is logged with full trace for accountability

---

## 🐝 Swarm Intelligence (Phase 3)

### Delegation Chains
Agents can delegate sub-tasks to specialists with full context preservation and provenance tracking:

```python
from neuralclaw.swarm.delegation import DelegationChain, DelegationContext

chain = DelegationChain()
ctx = DelegationContext(task_description="Research competitor pricing", max_steps=10)
delegation_id = await chain.create("researcher", ctx)
# ... sub-agent works ...
await chain.complete(delegation_id, result="Found 3 competitors", confidence=0.85)
```

### Consensus Protocol
Multiple agents can vote on high-stakes decisions:

```python
from neuralclaw.swarm.consensus import ConsensusProtocol, ConsensusMode

consensus = ConsensusProtocol(chain)
# Supports: MAJORITY, UNANIMOUS, WEIGHTED, QUORUM
```

### Agent Mesh
A2A-compatible agent discovery and communication:

```bash
neuralclaw swarm status    # View registered agents
neuralclaw swarm agents    # List capabilities
```

### Web Dashboard

Live monitoring dashboard with reasoning traces, memory stats, and swarm visualization:

```bash
neuralclaw dashboard       # Open at http://localhost:8099
```

---

## 🌐 Federation (Phase 4)

Agents can discover and communicate across network boundaries:

```python
from neuralclaw.swarm.federation import FederationProtocol

fed = FederationProtocol(node_name="my-agent", port=8100)
await fed.start()                                 # Start federation server
await fed.join_federation("http://peer:8100")      # Connect to another agent
await fed.send_message(node_id, "Analyze this")    # Send cross-network task
```

### Marketplace Economy

Credit-based economy with usage tracking, ratings, and leaderboards:

```python
from neuralclaw.skills.economy import SkillEconomy

econ = SkillEconomy()
econ.register_author("mirac", "Mirac")
econ.register_skill("web_search", "mirac")
econ.record_usage("web_search", user_id="u1", success=True)
econ.rate_skill("web_search", rater_id="u1", score=4.5, review="Great!")
print(econ.get_trending())
```

### Benchmarks

```bash
# Run the full benchmark suite
neuralclaw benchmark

# Run a specific category
neuralclaw benchmark --category security

# Export results to JSON
neuralclaw benchmark --export
```

---

## 🧪 Testing

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run full test suite
pytest tests/ -v

# Run Phase 2 functional tests
python test_phase2.py

# Run specific test modules
pytest tests/test_perception.py -v      # Perception + threat screening
pytest tests/test_memory.py -v          # Memory cortex
pytest tests/test_evolution_security_swarm.py -v  # Evolution, security, swarm
pytest tests/test_ssrf.py -v            # SSRF, URL validation, DNS rebinding
pytest tests/test_sandbox_policy.py -v  # Sandbox path validation, tool budgets
```

---

## 🗺️ Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| **Phase 1** | Foundation — Cortices, Bus, CLI, Providers, Skills | ✅ Complete |
| **Phase 2** | Intelligence — Memory metabolism, reflective reasoning, evolution cortex, marketplace | ✅ Complete |
| **Phase 3** | Swarm — Multi-agent delegation, consensus protocols, agent mesh, web dashboard | ✅ Complete |
| **Phase 4** | Domination — Federation, marketplace economy, benchmarks, PyPI publishing | ✅ Complete |

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<p align="center">
  Built with 🧠 by <strong>Mirac</strong> — <a href="https://cardify.dev">Cardify</a> / Claw Club
</p>
