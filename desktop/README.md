# NeuralClaw Desktop

> Native desktop client for **NeuralClaw** — the self-evolving AI agent framework.  
> Built with **Tauri 2**, **React 19**, and **TypeScript**.

![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-blue)
![Tauri](https://img.shields.io/badge/Tauri-2.x-24C8D8)
![React](https://img.shields.io/badge/React-19-61DAFB)
![TypeScript](https://img.shields.io/badge/TypeScript-5.x-3178C6)

---

## What Is This?

NeuralClaw Desktop is a native application that wraps the NeuralClaw Python agent framework in a polished desktop experience. It connects to the NeuralClaw backend via HTTP and WebSocket, giving you:

- **Chat interface** with real-time streaming via WebSocket
- **7-step setup wizard** for first-time configuration
- **Dashboard** with live stats, traces, event bus, and agent activity
- **Memory browser** for viewing episodic, semantic, and procedural memory
- **Settings panel** for provider, channels, and feature configuration
- **System tray** integration with quick-access menu
- **Cross-platform** builds (Windows `.msi`, macOS `.dmg`, Linux `.AppImage`)

## Architecture

```
┌─────────────────────────────────┐
│       NeuralClaw Desktop        │
│  ┌───────────┐  ┌────────────┐  │
│  │  React 19 │  │  Tauri 2   │  │
│  │  Frontend  │  │  (Rust)    │  │
│  └─────┬─────┘  └─────┬──────┘  │
│        │               │        │
│        │  IPC Commands  │        │
└────────┼───────────────┼────────┘
         │               │
    ┌────▼────┐     ┌────▼─────┐
    │ :8099   │     │  :8080   │
    │ WebChat │     │Dashboard │
    │  (WS)   │     │ (REST)   │
    └────┬────┘     └────┬─────┘
         │               │
    ┌────▼────────────────▼─────┐
    │   NeuralClaw Python       │
    │   Gateway (backend)       │
    └───────────────────────────┘
```

| Port  | Server    | Protocol  | Purpose |
|-------|-----------|-----------|---------|
| 8080  | Dashboard | HTTP/REST | Health checks, stats, memory, agents, traces, events |
| 8099  | WebChat   | WebSocket | Real-time chat messaging (`/ws/chat`) |

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| **Node.js** | ≥ 20 | [nodejs.org](https://nodejs.org) |
| **Rust** | ≥ 1.75 | `winget install Rustlang.Rustup` or [rustup.rs](https://rustup.rs) |
| **Python** | ≥ 3.11 | For running the NeuralClaw backend |

**Windows additional**: Visual Studio Build Tools with C++ workload (installed with Rust).

## Quick Start

### 1. Install dependencies

```bash
cd desktop
npm install
```

### 2. Start the NeuralClaw backend

In a separate terminal:

```bash
# From the project root
python -m neuralclaw gateway --web-port 8099
```

This starts:
- Dashboard on `http://localhost:8080`
- WebChat on `http://localhost:8099`

### 3. Launch the desktop app

```bash
npm run tauri dev
```

The app opens with hot-reload enabled. Changes to React code refresh instantly; Rust changes trigger a recompile.

## Project Structure

```
desktop/
├── index.html                          # HTML entry (Inter + JetBrains Mono fonts)
├── package.json                        # neuralclaw-desktop v1.0.0
├── vite.config.ts                      # Vite build config
├── tsconfig.json                       # TypeScript config
│
├── src/                                # React frontend
│   ├── main.tsx                        # Entry point
│   ├── App.tsx                         # Root component (lock → wizard → app)
│   ├── index.css                       # Design system (900+ lines)
│   │
│   ├── lib/                            # Core libraries
│   │   ├── constants.ts                # Ports, URLs, app metadata
│   │   ├── theme.ts                    # Provider colors, model definitions
│   │   ├── api.ts                      # Typed HTTP client (Dashboard API)
│   │   └── ws.ts                       # WebSocket manager (WebChat)
│   │
│   ├── store/                          # Zustand state management
│   │   ├── appStore.ts                 # Global app state
│   │   ├── chatStore.ts                # Messages + streaming state
│   │   └── wizardStore.ts              # Wizard step data
│   │
│   ├── hooks/                          # React hooks
│   │   ├── useBackend.ts               # WebSocket connection lifecycle
│   │   ├── useChat.ts                  # Send/receive messages
│   │   ├── useConfig.ts                # Load backend config
│   │   └── useHealth.ts                # Health polling (5s interval)
│   │
│   ├── wizard/                         # First-run setup wizard
│   │   ├── WizardShell.tsx             # Progress bar + step container
│   │   ├── Step1Welcome.tsx            # Feature overview
│   │   ├── Step2Providers.tsx          # Select AI providers
│   │   ├── Step3ApiKey.tsx             # Enter API keys
│   │   ├── Step4ModelPick.tsx          # Choose models
│   │   ├── Step5Channels.tsx           # Configure messaging channels
│   │   ├── Step6Features.tsx           # Toggle features
│   │   └── Step7Summary.tsx            # Review + launch
│   │
│   ├── components/
│   │   ├── chat/                       # Chat UI components
│   │   │   ├── ChatView.tsx            # Message list + auto-scroll
│   │   │   ├── MessageBubble.tsx       # Markdown rendering
│   │   │   ├── InputBar.tsx            # Auto-resize textarea
│   │   │   ├── StatusBar.tsx           # Version + connection status
│   │   │   └── ToolCallCard.tsx        # Collapsible tool invocations
│   │   └── layout/
│   │       ├── Sidebar.tsx             # Navigation + status
│   │       └── Header.tsx              # Page title bar
│   │
│   └── views/                          # Full page views
│       ├── LockView.tsx                # Biometric lock screen
│       ├── ChatPage.tsx                # Chat interface
│       ├── SettingsPage.tsx            # Settings (General, Provider, Channels)
│       ├── MemoryPage.tsx              # Memory stats + clear
│       ├── KnowledgePage.tsx           # Knowledge base instructions
│       ├── WorkflowPage.tsx            # Workflow manager
│       ├── DashboardPage.tsx           # Stats, traces, events, agents
│       └── AboutPage.tsx               # Version info + credits
│
├── src-tauri/                          # Rust / Tauri backend
│   ├── Cargo.toml                      # Dependencies
│   ├── tauri.conf.json                 # App config + window settings
│   ├── capabilities/default.json       # Security permissions
│   ├── icons/                          # App icons (all sizes)
│   └── src/
│       ├── main.rs                     # Entry point
│       ├── lib.rs                      # Plugin setup + tray + sidecar init
│       ├── sidecar.rs                  # Python sidecar lifecycle management
│       ├── commands.rs                 # IPC command handlers (→ Dashboard API)
│       └── tray.rs                     # System tray (Open, Settings, Quit)
│
└── scripts/                            # Build helpers
    ├── build-sidecar.sh                # PyInstaller build (macOS/Linux)
    └── build-sidecar-win.ps1           # PyInstaller build (Windows)
```

## Backend API Reference

The desktop app connects to two backend servers. Here are the endpoints it uses:

### Dashboard Server (`:8080`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check (status, version, uptime) |
| GET | `/ready` | Readiness probe |
| GET | `/api/stats` | System stats (provider, interactions, success rate) |
| GET | `/api/memory` | Memory counts (episodic, semantic, procedural) |
| GET | `/api/agents` | Active swarm agents |
| GET | `/api/traces` | Recent reasoning traces |
| GET | `/api/bus` | Event bus log |
| GET | `/api/features` | Feature toggle states |
| GET | `/config` | Full configuration dump |
| POST | `/api/message` | Send a test message |
| POST | `/api/memory/clear` | Clear all memory |
| POST | `/api/features` | Toggle a feature |

### WebChat Server (`:8099`)

| Protocol | Endpoint | Description |
|----------|----------|-------------|
| WS | `/ws/chat` | Real-time chat (send: `{content}`, receive: `response_delta`, `response`, `response_complete`) |
| GET | `/chat` | Embedded HTML chat UI (built into backend) |

## Design System

The app uses a custom dark theme with CSS variables. Key tokens:

- **Background**: `#0d1117` (GitHub-dark inspired)
- **Surface**: `#161b22` with `#21262d` elevation
- **Accent**: `#58a6ff` (blue), `#3fb950` (green), `#f0883e` (orange)
- **Typography**: Inter (UI) + JetBrains Mono (code)
- **Animations**: fadeIn, slideIn, scaleIn, glow, pulse

## Building for Production

### 1. Build the Python sidecar

The sidecar is a PyInstaller-packaged version of the NeuralClaw gateway that gets bundled with the app.

```bash
# Windows
pwsh scripts/build-sidecar-win.ps1

# macOS/Linux
./scripts/build-sidecar.sh
```

### 2. Add sidecar to Tauri config

Add back the `externalBin` to `src-tauri/tauri.conf.json` under `bundle`:

```json
"externalBin": [
  "sidecar/neuralclaw-sidecar"
]
```

### 3. Build the installer

```bash
npm run tauri build
```

Output:
- **Windows**: `src-tauri/target/release/bundle/msi/NeuralClaw_1.0.0_x64_en-US.msi`
- **macOS**: `src-tauri/target/release/bundle/dmg/NeuralClaw_1.0.0_aarch64.dmg`
- **Linux**: `src-tauri/target/release/bundle/appimage/NeuralClaw_1.0.0_amd64.AppImage`

## CI/CD

The `.github/workflows/desktop-release.yml` workflow builds the app for all platforms when a tag matching `desktop-v*` is pushed:

```bash
git tag desktop-v1.0.0
git push origin desktop-v1.0.0
```

## Development Notes

### Hot Reload
- React changes: instant (Vite HMR)
- Rust changes: auto-recompile (~15s)
- CSS changes: instant

### Without the Backend
The app works without the backend running — it shows "Disconnected" status and the chat will display an offline message. Dashboard/Memory pages will show empty states.

### Port Configuration
If you need different ports, update:
1. `src/lib/constants.ts` — `DASHBOARD_PORT` and `WEBCHAT_PORT`
2. Backend launch command: `--web-port` and `--dashboard-port` flags

## License

Same as the parent NeuralClaw project.
