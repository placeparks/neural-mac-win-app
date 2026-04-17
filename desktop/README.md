# NeuralClaw Desktop

Native desktop client for NeuralClaw, built with Tauri 2, React 19, and TypeScript.

## What The Desktop App Does

The desktop app is the primary product surface for NeuralClaw. It is not just a chat shell.

Current product responsibilities:

- first-run setup wizard
- provider and model-role configuration
- persistent local chat sessions
- agent definition and delegation workflows
- task inbox and orchestration tracking
- integrations and channels control plane
- knowledge-base ingestion and memory maintenance
- floating avatar / assistant window
- local computer + voice assistant controls

## Current Desktop Surfaces

- `Chat`
  - persistent sessions
  - attachments
  - selected model metadata
  - requested/effective model tracking
- `Connections`
  - connect/test/disconnect supported integrations
  - surface operational readiness
- `Tasks`
  - manual, auto-route, consensus, and pipeline task tracking
  - orchestration metadata and task detail
  - approval-gated execution and review actions
- `Agents`
  - persistent definitions
  - runtime state
  - direct talk
  - delegation
- `Memory`
  - counts
  - retention
  - export/import
- `Knowledge`
  - upload
  - ingest
  - search
  - delete
- `Database`
  - DB/BI workflows
  - connection visibility
- `Workspace`
  - projects and agent workspace visibility
- `Settings`
  - provider config
  - model roles
  - embedding model
  - channels
  - search providers
  - feature flags
  - autonomy and self-configuration permissions
  - backend runtime
  - `Computer + Voice Assistant`

## Avatar / Assistant

The avatar is now part of the real product experience rather than a cosmetic extra.

Current assistant behaviors:

- floating avatar window
- agent deck for delegation
- live activity pulse
- inline mic input from the avatar overlay
- optional auto-speak replies
- live desktop screen preview
- assistant-centric settings in the `Computer + Voice Assistant` tab

Windows-specific intent:

- avoid stale speaking/emotion state
- avoid duplicate spoken replies
- keep mic, bubble, and response state coordinated
- make the avatar feel like an assistant presence, not a novelty widget

## Operator View

The desktop dashboard is now an operator surface, not only a health screen.

Current operator pieces:

- provider and backend health
- operator brief
- recommended actions
- traces and event bus
- recent audited actions

This matters because the product should show what the agent actually did, not only what it said.

## Architecture

```text
+---------------------- NeuralClaw Desktop -----------------------+
| React frontend | Zustand stores | Tauri shell | Avatar window   |
+---------------------------+-------------------------------------+
                            |
                            v
+-------------------------- Local sidecar ------------------------+
| Dashboard API :8080 | web chat/traces | tasks | integrations    |
+---------------------------+-------------------------------------+
                            |
                            v
+------------------------ NeuralClaw core ------------------------+
| gateway | swarm | memory | channels | local routing | skills    |
+----------------------------------------------------------------+
```

## Model Routing

The desktop app treats the configured local endpoint as the live source of truth.

- available Ollama models are discovered from the configured endpoint
- model roles are configured from the UI
- chat-capable and embedding-only model usage is separated
- requested and effective models are tracked independently
- fallback behavior is surfaced to users

Important rule:

- embedding-only models belong in the embedding path only
- they are blocked from chat and delegation roles

## Integrations and Channels

Desktop is the user-facing control plane for both.

Current integrations surfaced from the app:

- GitHub
- Google Workspace
- Slack
- Jira
- Notion
- Supabase
- database connections

Current channel management surfaced from the app:

- Telegram
- Discord
- Slack
- WhatsApp
- Signal

Important Slack note:

- workspace connect is not the same as full Socket Mode readiness
- deeper inbound Slack behavior still requires the app token path

## Feature and Autonomy Controls

Settings now needs to be treated as a real control layer.

Current intent:

- expose meaningful backend feature toggles
- group them clearly instead of showing a flat dump
- make self-configuration and skill-forging capability an explicit user permission
- avoid hidden runtime powers that are not obvious from the UI

## Local Assistant Controls

The `Computer + Voice Assistant` tab currently manages:

- avatar visibility and VRM model
- assistant voice presence
- auto-speak replies
- desktop control enablement
- browser automation enablement
- screen peek test flow
- action delay and related runtime controls

This tab is the current home for local assistant configuration and should stay the canonical assistant control surface.

## Development

### Prerequisites

- Node.js 20+
- Rust stable toolchain
- Python 3.11+

### Run in development

```bash
cd desktop
npm install
npm run tauri dev
```

### Build for production

```bash
cd desktop
npm run tauri build
```

The Tauri release build packages the Python sidecar automatically.

## Validation

Useful checks:

```bash
cd desktop
npm run build
```

From repo root:

```bash
python -m py_compile neuralclaw/dashboard.py neuralclaw/gateway.py
```

## Known Notes

- the avatar vendor bundle remains large; packaging succeeds, but chunk optimization is still open
- packaged logging has occasionally been inconsistent even when the backend is healthy
- sidecar/process ownership handling has been improved significantly, but installer validation is still important after runtime changes
- backend STT and stronger voice-entry reliability are still future work for a more premium assistant experience
