# NeuralClaw Desktop

Native desktop client for NeuralClaw, built with Tauri 2, React 19, and TypeScript.

## Desktop v1.4.0

This release turns the desktop app into a local control room for NeuralClaw:

- Persistent chat sessions with model-aware metadata
- Dedicated `Tasks` inbox for delegated and background work
- Agent creation, editing, direct talk, delegation, and runtime telemetry
- Local Ollama model discovery, health badges, and automatic failover
- Memory controls for episodic, semantic, and procedural memory
- Knowledge-base document and image upload flows
- Channel configuration for Telegram, Discord, Slack, WhatsApp, and Signal
- Avatar window with agent desk, minimize/hide support, and desktop companion mode

## Architecture

```text
+----------------------- NeuralClaw Desktop ------------------------+
| React frontend | Zustand stores | Tauri shell | Avatar window     |
+---------------------------+--------------------------------------+
                            |
                            v
+--------------------------- Local sidecar ------------------------+
| Dashboard API (:8080) | Web chat / traces | task + agent APIs    |
+---------------------------+-------------------------------------+
                            |
                            v
+------------------------- NeuralClaw core ------------------------+
| Gateway | Swarm agents | Memory | Channels | Local model routing |
+-----------------------------------------------------------------+
```

## Main Surfaces

- `Chat`: persistent sessions, attachments, per-chat model selection, requested/effective model display
- `Tasks`: queued/running/completed/failed delegated work with detail view and follow-up routing
- `Agents`: definitions, live runtime state, logs, latency/token metrics, direct talk/delegate flows
- `Memory`: live counts, refresh, and clear controls
- `Knowledge Base`: upload and manage documents/images for retrieval
- `Settings`: provider, channels, models, memory, avatar, features, and advanced computer-use controls

## Local Model Routing

NeuralClaw Desktop treats the configured Ollama endpoint as the single source of truth.

- The app fetches exact live model tags from the configured local host
- New chats and agents use the real discovered model names
- Requested and effective model names are tracked separately
- If `qwen3.5:35b` is unavailable, execution can fall back to `qwen3.5:9b`, then `qwen3.5:4b`
- Health state and fallback behavior are visible in the desktop UI

## Delegation and Tasks

Delegated work is persisted as task records and survives app restart.

- Single-agent delegation produces a tracked task with result or error state
- Multi-agent delegation creates parent and child task records
- Completion, failure, and model downgrade events surface as toasts
- Task detail includes target agent(s), result preview, runtime data, and chat follow-up actions

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

The Tauri release build packages the Python sidecar automatically.

## Production Build

```bash
cd desktop
npm run tauri build
```

Windows outputs:

- `src-tauri/target/release/bundle/nsis/NeuralClaw_1.4.0_x64-setup.exe`
- `src-tauri/target/release/bundle/msi/NeuralClaw_1.4.0_x64_en-US.msi`

The GitHub workflow at `.github/workflows/desktop-release.yml` builds tagged desktop releases for:

- Windows (`x86_64-pc-windows-msvc`)
- macOS Apple Silicon (`aarch64-apple-darwin`)
- Linux (`x86_64-unknown-linux-gnu`)

Release trigger:

```bash
git tag desktop-v1.4.0
git push origin desktop-v1.4.0
```

## Notes

- Desktop app versioning is independent from the Python package version at the repo root
- Local chat and task data persists across reinstalls unless explicitly cleared
- The Tauri bundle still carries a large lazy avatar vendor chunk; packaging succeeds, but that remains the main optimization item
