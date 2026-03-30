# NeuralClaw Desktop — Architecture

## System Overview

NeuralClaw Desktop is a **thin client** that wraps the NeuralClaw Python agent framework. The Tauri shell provides native window management, system tray, and eventually sidecar lifecycle management. All intelligence lives in the Python backend.

```
┌─────────────────────────────────────────────────────────────┐
│                    NeuralClaw Desktop                       │
│                                                             │
│  ┌───────────────────────┐    ┌──────────────────────────┐  │
│  │     React Frontend    │    │     Tauri / Rust Shell    │  │
│  │                       │    │                          │  │
│  │  ┌─────────────────┐  │    │  ┌────────────────────┐  │  │
│  │  │   Zustand Stores │  │    │  │   IPC Commands     │  │  │
│  │  │  (app, chat, wiz)│  │    │  │  (→ Dashboard API) │  │  │
│  │  └────────┬────────┘  │    │  └────────────────────┘  │  │
│  │           │           │    │                          │  │
│  │  ┌────────▼────────┐  │    │  ┌────────────────────┐  │  │
│  │  │  lib/api.ts     │──┼────┼──│  sidecar.rs         │  │  │
│  │  │  (HTTP client)  │  │    │  │  (process manager)  │  │  │
│  │  └─────────────────┘  │    │  └────────────────────┘  │  │
│  │                       │    │                          │  │
│  │  ┌─────────────────┐  │    │  ┌────────────────────┐  │  │
│  │  │  lib/ws.ts      │  │    │  │  tray.rs            │  │  │
│  │  │  (WebSocket)    │  │    │  │  (system tray)      │  │  │
│  │  └─────────────────┘  │    │  └────────────────────┘  │  │
│  └───────────────────────┘    └──────────────────────────┘  │
│                                                             │
└────────────────────────────┬────────────────────────────────┘
                             │
                    Network (localhost)
                             │
              ┌──────────────▼──────────────┐
              │   NeuralClaw Python Gateway  │
              │                              │
              │  ┌────────────────────────┐  │
              │  │ Dashboard (:8080)      │  │
              │  │ REST: /health, /api/*  │  │
              │  │ WS: /ws/traces        │  │
              │  └────────────────────────┘  │
              │                              │
              │  ┌────────────────────────┐  │
              │  │ WebChat (:8099)        │  │
              │  │ WS: /ws/chat           │  │
              │  │ HTML: /chat            │  │
              │  └────────────────────────┘  │
              │                              │
              │  Five-Cortex Runtime:         │
              │  Perception → Memory →       │
              │  Reasoning → Action →        │
              │  Evolution                   │
              └──────────────────────────────┘
```

## Data Flow

### Chat Message Flow

```
User types message
       │
       ▼
  InputBar.tsx
       │
       ▼
  useChat.ts → wsManager.send({content: "hello"})
       │
       ▼ WebSocket
  WebChatAdapter (:8099/ws/chat)
       │
       ▼
  NeuralClaw Gateway Pipeline
  (Perception → Memory → Reasoning → Action)
       │
       ▼ WebSocket events
  response_delta  → appendStreamToken (live typing)
  response        → addMessage (one-shot reply)
  response_complete → addMessage (stream done)
       │
       ▼
  ChatView.tsx renders new message
```

### Health Check Flow

```
useHealth.ts (every 5 seconds)
       │
       ▼ HTTP GET
  Dashboard (:8080/health)
       │
       ▼ Response
  { status: "healthy", version: "1.5.5", uptime: "2h 15m" }
       │
       ▼
  appStore → connectionStatus = "connected"
```

### Dashboard Data Flow

```
DashboardPage.tsx (on mount)
       │
       ▼ HTTP GET (parallel)
  /api/stats     → provider, interactions, success_rate
  /api/bus       → recent event bus entries
  /api/agents    → swarm agent list
  /api/traces    → reasoning trace log
       │
       ▼
  Rendered in stats grid, traces list, event log
```

## State Management

Three Zustand stores manage all client-side state:

### appStore
```typescript
{
  setupComplete: boolean      // Has the wizard been completed?
  isLocked: boolean          // Is the biometric lock active?
  biometricEnabled: boolean  // Is biometric auth enabled?
  connectionStatus: string   // 'connected' | 'connecting' | 'disconnected'
  backendVersion: string     // e.g. "1.5.5"
  backendLatency: number     // ms
}
```

### chatStore
```typescript
{
  messages: ChatMessage[]       // Full conversation history
  isStreaming: boolean          // Is a response currently streaming?
  currentStreamContent: string  // Accumulated streaming tokens
  activeToolCalls: ToolCall[]   // In-progress tool invocations
}
```

### wizardStore
```typescript
{
  currentStep: number           // 1-7
  selectedProviders: string[]   // ['venice', 'openai', ...]
  apiKeys: Record<string, string>
  selectedModel: string
  enabledChannels: string[]
  enabledFeatures: string[]
  botName: string
}
```

## Security Model

### Current (Development)
- CSP is disabled (`"csp": null`) for dev flexibility
- API keys are stored in Zustand (browser memory only, not persisted)
- No authentication between desktop and backend

### Future (Production)
- API keys stored via `tauri-plugin-keychain` (OS keychain)
- Biometric unlock via platform APIs
- CSP enabled with strict whitelist
- Sidecar communication over localhost-only with shared secret

## Component Hierarchy

```
App
├── LockView (if biometric enabled + locked)
├── WizardShell (if setup not complete)
│   ├── Step1Welcome
│   ├── Step2Providers
│   ├── Step3ApiKey
│   ├── Step4ModelPick
│   ├── Step5Channels
│   ├── Step6Features
│   └── Step7Summary
└── AppLayout (main experience)
    ├── Sidebar
    └── Main Content
        ├── ChatPage → ChatView, InputBar, StatusBar
        ├── SettingsPage
        ├── MemoryPage
        ├── KnowledgePage
        ├── WorkflowPage
        ├── DashboardPage
        └── AboutPage
```

## Technology Choices

| Layer | Technology | Why |
|-------|-----------|-----|
| Shell | Tauri 2 | Native performance, small binary (~5MB), Rust safety |
| Frontend | React 19 | Component model, ecosystem, TypeScript support |
| State | Zustand | Minimal boilerplate, no Provider wrappers needed |
| Styling | Vanilla CSS | Full control, no build-time overhead, CSS variables |
| Build | Vite | Fast HMR, ESM-native, Tauri integration |
| Backend | Python | NeuralClaw's native language, rich AI/ML ecosystem |
| IPC | HTTP + WebSocket | Simple, debuggable, no custom protocol needed |
