# NeuralClaw

Version target: `1.5.7`

NeuralClaw is a desktop-first agent platform built around a Python cognitive gateway and a native Tauri desktop client. It combines local and hosted model routing, durable task delegation, integrations, channels, web research, knowledge retrieval, and a floating assistant/avatar experience.

## What NeuralClaw Is Now

NeuralClaw is no longer only a Python agent framework. In the current repository state it is a product stack made of:

- a Python gateway and skill runtime
- a desktop control plane
- an adaptive context engine (proactive suggestions, routines, style learning)
- persistent agent/task orchestration
- integrations and channels
- local computer-use and browser-use capabilities
- a premium assistant/avatar layer for Windows desktop use

## Core Capabilities

### Agent Runtime

- Multi-provider model execution:
  - `openai`
  - `anthropic`
  - `openrouter`
  - `proxy`
  - `local`
  - session-based providers such as `chatgpt_app` and `claude_app`
- Role-based local routing for:
  - `primary`
  - `fast`
  - `micro`
  - `embed`
- Durable delegation modes:
  - manual
  - auto-route
  - consensus
  - pipeline
- Approval-gated execution for delegation workflows
- Operator brief and recent-action audit visibility in the dashboard
- Self-config tooling so the agent can inspect and update parts of its runtime config

### Memory and Knowledge

- Episodic, semantic, procedural, vector, and identity memory
- Dedicated embedding model support
- Knowledge-base upload and ingestion
- Startup KB auto-indexing from configured project paths

### Web and Computer Use

- Improved web search pipeline for recommendation-style queries such as “best phones of 2026”
- Browser automation tools
- Desktop control tools:
  - screenshot
  - click
  - type
  - hotkeys
  - clipboard read/write
  - app launch

### Integrations and Channels

- Connections surface for:
  - GitHub
  - Google Workspace
  - Slack
  - Jira
  - Notion
  - Supabase
  - database connections
- Channels surface for:
  - Telegram
  - Discord
  - Slack
  - WhatsApp
  - Signal

### Desktop Assistant

- Floating avatar assistant window
- Mic input in the avatar overlay
- Optional auto-speak replies
- Live desktop screen preview
- Agent deck for delegation and activity
- Dedicated `Computer + Voice Assistant` settings tab

## Desktop App

The desktop app is the primary user-facing control surface.

Main areas:

- `Chat`
- `Connections`
- `Tasks`
- `Agents`
- `Memory`
- `Knowledge`
- `Database`
- `Workspace`
- `Settings`

Key desktop behaviors:

- setup wizard persists real runtime config
- local chat sessions are persistent
- requested/effective model behavior is tracked
- delegation state survives restart
- approval-gated work can be reviewed from the task inbox
- connections and channels are configured from UI
- model roles are configured from UI
- search providers are configured from UI
- feature and autonomy toggles are surfaced from UI

See [desktop/README.md](C:/Users/Lenovo/Downloads/clawnick-main%20(2)/clawnick-main/desktop/README.md) for desktop-specific details.

## Integrations

Current connection platform direction:

- connect from the UI instead of only pasting secrets into files
- test connections from the UI
- track integration readiness and status
- expose agent-facing capabilities instead of raw token storage

Current status:

- GitHub OAuth flow exists
- Slack workspace connect flow exists
- Google Workspace connect/test flow exists
- Supabase save/test flow exists
- Slack UI distinguishes workspace connection from full Socket Mode readiness
- channel configuration now surfaces channel-specific fields instead of one generic token path

Important Slack note:

- deep inbound Slack behavior still requires an `xapp-...` app token for Socket Mode

## Search and Research Quality

NeuralClaw’s web research path has been improved for recommendation and comparison queries.

What changed:

- stronger DuckDuckGo fallback
- result ranking and dedupe
- editorial-review domain preference
- better extraction from article/main content
- desktop settings for provider keys:
  - Tavily
  - Brave
  - Serper
  - Google Custom Search
  - SearXNG

Best quality still depends on the user providing at least one premium search provider key.

## Operator Control and Observability

NeuralClaw is being moved toward a visible, trustworthy agent operating surface.

Current control/inspection pieces:

- task inbox with approval states
- operator brief in the dashboard
- recommended actions generated from recent runtime context
- proactive background routines driven by the `RoutineScheduler`
- passive format and tone learning mapped to the `StyleAdapter`
- actionable intent prediction during standard operations
- transactional compensating rollbacks for supported integrations
- grouped feature toggles and autonomy controls in settings

Important rule:

- agent self-configuration and forge-style capability changes should only be available when explicitly permitted by the user

## Install

```bash
pip install neuralclaw
```

Local editable install:

```bash
pip install -e .
```

Development:

```bash
pip install -e ".[dev]"
python -m playwright install chromium
```

Optional extras:

```bash
pip install -e ".[voice]"
pip install -e ".[browser]"
pip install -e ".[desktop]"
pip install -e ".[google]"
pip install -e ".[microsoft]"
pip install -e ".[vector]"
pip install -e ".[all,dev]"
```

External runtimes still needed for some flows:

- Playwright browser binaries
- Node.js for WhatsApp bridge flows
- `signal-cli` for Signal
- FFmpeg for Discord voice playback

## Quick Start

```bash
neuralclaw init
neuralclaw local setup
neuralclaw channels setup
neuralclaw status
neuralclaw doctor
neuralclaw chat
neuralclaw gateway
```

Desktop development:

```bash
cd desktop
npm install
npm run tauri dev
```

Desktop production build:

```bash
cd desktop
npm run tauri build
```

## Project Layout

```text
neuralclaw/
  bus/         event bus and telemetry
  channels/    adapters and trust layer
  cortex/      perception, memory, reasoning, action, evolution
  providers/   model providers and router
  session/     session-backed providers
  skills/      built-ins, manifests, registry
  swarm/       delegation, consensus, federation
  gateway.py   gateway orchestration entrypoint
  config.py    runtime config and validation
desktop/
  src/         React views, hooks, stores, avatar UI
  src-tauri/   Rust shell, sidecar, tray, IPC
  scripts/     sidecar build scripts
```

## Product Notes

- Embedding-only models are intentionally reserved for memory/RAG and blocked from chat/delegation roles
- Installed-app behavior has been validated repeatedly against sidecar lifecycle issues
- The avatar path is functional and significantly improved, but bundle/chunk optimization is still open
- Packaged Windows runs now preserve actionable audit/error detail for denied or crashed tool calls instead of blank failure fields
- Packaged Windows sandbox execution now prefers real Python installs and skips `WindowsApps` alias stubs that can break `forge_skill` and `execute_python`
- Some packaged logging runs have been inconsistent, so runtime health is still sometimes verified through live API/process checks in addition to logs
- Approval metadata and richer planner-style orchestration still need deeper polish beyond the current delegation modes

## Documentation

- [desktop/README.md](C:/Users/Lenovo/Downloads/clawnick-main%20(2)/clawnick-main/desktop/README.md)
- [COMMANDS.md](C:/Users/Lenovo/Downloads/clawnick-main%20(2)/clawnick-main/COMMANDS.md)
- [CHANGELOG.md](C:/Users/Lenovo/Downloads/clawnick-main%20(2)/clawnick-main/CHANGELOG.md)
- [CONTRIBUTING.md](C:/Users/Lenovo/Downloads/clawnick-main%20(2)/clawnick-main/CONTRIBUTING.md)
- [agent.md](C:/Users/Lenovo/Downloads/clawnick-main%20(2)/clawnick-main/agent.md)
