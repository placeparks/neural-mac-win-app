# NeuralClaw Desktop — Development Guide

## Environment Setup

### Windows

```powershell
# 1. Install Rust
winget install Rustlang.Rustup

# 2. Install Node.js 22+
winget install OpenJS.NodeJS.LTS

# 3. Install dependencies
cd desktop
npm install

# 4. Verify
rustc --version    # ≥ 1.75
node --version     # ≥ 20
npx tsc --noEmit   # should pass clean
```

### macOS

```bash
# 1. Install Xcode CLI tools
xcode-select --install

# 2. Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# 3. Install Node.js
brew install node

# 4. Install dependencies
cd desktop && npm install
```

### Linux (Ubuntu/Debian)

```bash
# 1. System deps for Tauri
sudo apt install -y \
  libwebkit2gtk-4.1-dev \
  libappindicator3-dev \
  librsvg2-dev \
  patchelf

# 2. Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# 3. Install Node.js
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs

# 4. Install dependencies
cd desktop && npm install
```

## Running in Development

You need two terminals:

```bash
# Terminal 1 — NeuralClaw backend
python -m neuralclaw gateway --web-port 8099

# Terminal 2 — Desktop app (hot-reload)
cd desktop
npm run tauri dev
```

### What each port does

| Port | Service | Used By |
|------|---------|---------|
| 1420 | Vite dev server | Tauri webview (dev only) |
| 8080 | Dashboard (REST) | Health, stats, memory, agents, traces |
| 8099 | WebChat (WS) | Real-time chat via `/ws/chat` |

## Code Conventions

### TypeScript

- **Stores**: Zustand with interface-first approach (`appStore.ts`, `chatStore.ts`, `wizardStore.ts`)
- **Hooks**: One hook per concern (`useChat`, `useHealth`, `useBackend`, `useConfig`)
- **API**: All backend calls go through `lib/api.ts` — never call `fetch` directly in components
- **WebSocket**: All WS logic lives in `lib/ws.ts` — components subscribe via `useBackend`
- **Constants**: All ports, URLs, and app metadata in `lib/constants.ts`

### Rust

- **Commands**: Each IPC handler in `commands.rs` proxies to the Dashboard REST API
- **Sidecar**: `sidecar.rs` manages the Python backend lifecycle
- **Tray**: `tray.rs` handles system tray icon and menu
- **No business logic in Rust** — the Rust layer is purely a shell

### CSS

- Design system lives entirely in `src/index.css`
- Use CSS variables (e.g., `var(--bg-primary)`, `var(--accent-blue)`)
- Component classes follow BEM-like naming (`.chat-view`, `.wizard-card`, `.stat-card`)
- No CSS-in-JS or Tailwind

## Type Checking

```bash
# Check TypeScript
npx tsc --noEmit

# Build frontend only
npx vite build

# Build Rust only
cd src-tauri && cargo build

# Full Tauri build (frontend + Rust)
npm run tauri build
```

## Adding a New View

1. Create `src/views/MyPage.tsx`
2. Add to `App.tsx` switch statement
3. Add nav item in `components/layout/Sidebar.tsx` (`NAV_ITEMS` array)
4. If it needs backend data, add API functions in `lib/api.ts`

## Adding a New IPC Command

1. Add the Rust handler in `src-tauri/src/commands.rs`
2. Register it in `src-tauri/src/lib.rs` → `tauri::generate_handler![]`
3. Call from React via `@tauri-apps/api/core` → `invoke('command_name', { args })`

## Building the Sidecar

The sidecar is a PyInstaller-packaged NeuralClaw gateway binary that ships with production builds.

```bash
# Windows
pwsh scripts/build-sidecar-win.ps1

# macOS/Linux
chmod +x scripts/build-sidecar.sh
./scripts/build-sidecar.sh
```

The sidecar binary must be placed in `src-tauri/sidecar/` and the `externalBin` config must be added back to `tauri.conf.json` before building for production.

## Production Build

```bash
# Ensure sidecar is built first, then:
npm run tauri build
```

Installers are output to `src-tauri/target/release/bundle/`.

## CI/CD

Push a tag to trigger the GitHub Actions build:

```bash
git tag desktop-v1.0.0
git push origin desktop-v1.0.0
```

The workflow builds for Windows, macOS (x86 + ARM), and Linux in parallel.
