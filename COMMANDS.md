# NeuralClaw Commands

Version target: `current source tree`

This file covers the primary Python-side commands that are still relevant alongside the desktop app.

## Install

```bash
pip install neuralclaw
pip install -e .
pip install -e ".[dev]"
pip install -e ".[all,dev]"
python -m playwright install chromium
```

Notes:

- WhatsApp still needs Node.js for the bridge
- Signal still needs `signal-cli`
- Browser automation still needs Playwright browser install

## Core Runtime

```bash
neuralclaw init
neuralclaw chat
neuralclaw gateway
neuralclaw daemon
neuralclaw status
neuralclaw doctor
neuralclaw repair
neuralclaw --help
neuralclaw --version
```

## Local Model Setup

```bash
neuralclaw local --help
neuralclaw local setup
neuralclaw local status
```

## Sessions

```bash
neuralclaw session --help
neuralclaw session setup chatgpt
neuralclaw session setup claude
neuralclaw session status
neuralclaw session diagnose chatgpt
neuralclaw session diagnose claude
neuralclaw session open chatgpt
neuralclaw session open claude
neuralclaw session login chatgpt
neuralclaw session login claude
neuralclaw session repair chatgpt
neuralclaw session repair claude
neuralclaw session auth google
neuralclaw session auth microsoft
```

## Proxy

```bash
neuralclaw proxy --help
neuralclaw proxy setup
neuralclaw proxy status
```

## Channels

```bash
neuralclaw channels --help
neuralclaw channels setup
neuralclaw channels list
neuralclaw channels test
neuralclaw channels test telegram
neuralclaw channels add telegram
neuralclaw channels remove telegram
neuralclaw channels connect whatsapp
```

Trust behavior:

- `open`: route is accepted immediately
- `pair`: requires pairing/binding first
- `bound`: only trusted bindings may talk

## Gateway Options

```bash
neuralclaw gateway --name Agent-2
neuralclaw gateway --federation-port 8101
neuralclaw gateway --dashboard-port 8081
neuralclaw gateway --web-port 8082
neuralclaw gateway --seed http://localhost:8100
```

## Swarm and Federation

```bash
neuralclaw swarm status
neuralclaw swarm spawn researcher -c "search,analysis"
neuralclaw federation
neuralclaw benchmark
neuralclaw benchmark --category security
neuralclaw benchmark --export
```

## SkillForge

```bash
neuralclaw forge --help
neuralclaw forge create "https://api.stripe.com" --use-case "charge chiro patients"
neuralclaw forge create "twilio" --use-case "send appointment reminders"
neuralclaw forge create "I want to look up drug interactions"
neuralclaw forge list
neuralclaw forge show <skill-name>
neuralclaw forge remove <skill-name>
```

Important runtime note:

- forge/scout capability may exist in the backend, but agent self-modification should still be treated as a user-permitted autonomy capability in the product UX

## SkillScout

```bash
neuralclaw scout --help
neuralclaw scout find "verify patient insurance eligibility"
neuralclaw scout search "send SMS reminders"
```

## Desktop Workflow

These are not Python CLI commands, but they are the primary app workflow now.

```bash
cd desktop
npm install
npm run tauri dev
```

Production build:

```bash
cd desktop
npm run tauri build
```

## Validation

```bash
pytest -q
python -m compileall neuralclaw
python -m py_compile neuralclaw/dashboard.py neuralclaw/gateway.py
cd desktop && npm run build
```

## Product Guidance

- Use the desktop app for connections, model roles, channels, tasks, and assistant controls
- Use the desktop app to review approval-gated work and recent audited actions
- Use the CLI for local runtime setup, debugging, services, and direct Python-side workflows
