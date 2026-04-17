# Contributing to NeuralClaw

Thanks for contributing to NeuralClaw.

The current repository is a mixed Python + Tauri desktop product. Contributions should treat the Python gateway, desktop UI, and assistant experience as one connected system.

## Development Setup

```bash
git clone https://github.com/placeparks/neuralclaw.git
cd neuralclaw
pip install -e ".[dev]"
cd desktop
npm install
```

## Core Development Loops

### Python

```bash
pytest -q
python -m compileall neuralclaw
python -m py_compile neuralclaw/dashboard.py neuralclaw/gateway.py
```

### Desktop

```bash
cd desktop
npm run build
```

For local desktop iteration:

```bash
cd desktop
npm run tauri dev
```

## What Needs Extra Care

### Desktop Runtime Changes

Changes to any of these areas should be validated end-to-end:

- sidecar lifecycle
- installer/runtime process ownership
- desktop settings persistence
- avatar/assistant state flow
- model routing in installed builds

Do not assume a clean `npm run build` means the installed runtime behaves correctly.

### Integrations

If you change integrations:

- update the desktop `Connections` UX if the user-facing behavior changes
- keep connect/test/disconnect behavior aligned between backend and UI
- document any extra provider requirements clearly
- be precise about what is actually operational versus merely configured

### Agentic Runtime

If you change agent orchestration or autonomy:

- keep task lifecycle, approvals, and desktop task visibility aligned
- do not add hidden self-modification powers without an explicit user-facing permission
- preserve the distinction between chat-capable models and embedding-only models
- make sure the operator dashboard still explains what the system actually did

### Observability

If you change tool use, integration actions, or runtime control paths:

- wire the behavior into audit visibility when appropriate
- keep recent-action surfaces readable from the dashboard
- do not rely only on logs that may be inconsistent in packaged runs
- prefer product-visible traces for user trust

### Avatar / Assistant

The avatar should not feel like a toy.

When changing avatar or assistant behavior:

- avoid duplicated state ownership
- avoid stale timers overriding newer states
- avoid speech overlap
- avoid hidden capability toggles spread across unrelated tabs
- prioritize stable Windows behavior over flashy but brittle interactions

## Code Style

### Python

- use type hints on public functions
- keep public behavior explicit and testable
- prefer small, named helpers over long inline logic

### Desktop / TypeScript

- treat the UI as a product surface, not only a control panel
- keep state transitions coherent
- avoid stacking multiple disconnected sources of truth for the same behavior
- when adding user-facing flows, wire verification actions into the UI whenever possible

## Architecture Guidance

NeuralClaw currently spans:

- gateway/runtime
- skills and providers
- channels and integrations
- desktop app
- avatar/assistant UX

Make changes with these boundaries in mind:

1. Backend capability
2. Dashboard/API surface
3. Desktop UX/control surface
4. Runtime verification
5. Documentation
6. Observability / audit visibility

If one layer changes and the others are left behind, the product feels broken even if the code compiles.

## Pull Request Expectations

Before opening a PR:

1. run Python validation for touched backend paths
2. run desktop build if anything under `desktop/` changed
3. update docs for user-facing changes
4. update `agent.md` when the project state or priorities materially changed
5. call out remaining operational caveats honestly

## Security

If you discover a security vulnerability, report it privately rather than opening a public issue.

## License

By contributing, you agree that your contributions are licensed under the MIT License.
