# NeuralClaw

NeuralClaw is a Python agent framework with:

- multi-provider LLM routing
- direct ChatGPT and Claude browser-session support
- multi-channel messaging adapters
- memory, reasoning, policy, and tool execution layers
- simple channel trust modes: `open`, `pair`, `bound`

## Install

```bash
# PyPI install with all built-in Python dependencies
pip install neuralclaw

# Local checkout
pip install .

# Development
pip install -e ".[dev]"

# Compatibility aliases for older setup flows
pip install -e ".[sessions]"
pip install -e ".[all-channels]"
pip install -e ".[all,dev]"
```

`pip install neuralclaw` now installs the Python packages needed for all built-in
providers and channel adapters. Some integrations still need external runtimes:

- Playwright browser binaries for `chatgpt_app` and `claude_app`
- Node.js for the WhatsApp bridge
- `signal-cli` for Signal

Install Playwright browsers with:

```bash
python -m playwright install chromium
```

## Quick Start

```bash
# Create config and set API-backed providers
neuralclaw init

# Configure a direct ChatGPT browser session
neuralclaw session setup chatgpt

# Or configure a direct Claude browser session
neuralclaw session setup claude

# Configure channel credentials
neuralclaw channels setup

# Check status
neuralclaw status
neuralclaw session status

# Interactive chat
neuralclaw chat

# Force a specific provider
neuralclaw chat -p proxy
neuralclaw chat -p chatgpt_app
neuralclaw chat -p claude_app

# Start gateway with channels + web chat
neuralclaw gateway
```

## Providers

NeuralClaw supports these provider types:

| Provider | Purpose | Setup |
|---|---|---|
| `openai` | Official OpenAI API | `neuralclaw init` |
| `anthropic` | Official Anthropic API | `neuralclaw init` |
| `openrouter` | OpenRouter API | `neuralclaw init` |
| `proxy` | OpenAI-compatible relay | `neuralclaw proxy setup` |
| `chatgpt_app` | Direct ChatGPT browser session | `neuralclaw session setup chatgpt` |
| `claude_app` | Direct Claude browser session | `neuralclaw session setup claude` |
| `local` | Ollama or other local OpenAI-compatible endpoint | `neuralclaw local setup` |

Notes:

- `chatgpt_app` and `claude_app` use managed persistent browser profiles.
- `chatgpt_app` is experimental because upstream auth may reject browser-controlled login.
- Use `neuralclaw session diagnose chatgpt` if ChatGPT lands on `/api/auth/error` or a verification loop.
- Use `neuralclaw session auth chatgpt` to capture a managed-profile ChatGPT session cookie.
- If ChatGPT shows Cloudflare, complete the challenge in the opened browser and leave the terminal running until NeuralClaw captures the cookie.
- App-session providers are text-first and may fall back to tool-capable providers when tool calls are required.
- `proxy` remains useful for self-hosted relays or API-normalized session bridges.
- `local` works with Ollama and defaults to `qwen3.5:2b` unless you choose another local model.
- WhatsApp uses a Baileys bridge and may still hit upstream `405` failures on fresh sessions.

## Local Models

If you have Ollama running locally, use:

```bash
neuralclaw local setup
neuralclaw local status
neuralclaw chat -p local
```

The setup flow queries `http://localhost:11434/api/tags` and lets you select a
detected model such as `qwen3.5:0.8b`, `qwen3.5:2b`, `qwen3.5:4b`, or `qwen3.5:9b`.

## Channel Trust

Each channel can run in one of three trust modes:

| Mode | Behavior |
|---|---|
| `open` | Always accept inbound messages |
| `pair` | Require one-time `/pair` in that route before trusting it |
| `bound` | Only trusted bindings can talk; `/pair` creates the initial binding |

Default behavior:

- local web / CLI routes behave like `open`
- private messaging routes behave like `pair`
- shared routes behave like `bound`

Trusted bindings are stored locally in `~/.neuralclaw/data/channel_bindings.json`.

## Session Commands

```bash
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
```

## Project Layout

```text
neuralclaw/
  bus/         event bus and telemetry
  channels/    Telegram, Discord, Slack, Signal, WhatsApp, Web, trust layer
  cortex/      perception, memory, reasoning, action, evolution
  providers/   API providers, proxy provider, app-session providers, router
  session/     managed browser session runtime
  skills/      tool registry and built-ins
  gateway.py   orchestration entrypoint
  cli.py       command-line interface
  config.py    config, secrets, provider/channel setup
```

## Test

```bash
pytest -q
python -m compileall neuralclaw
python -m build
```

## Docs

See:

- [docs/channels.md](docs/channels.md)
- [docs/configuration.md](docs/configuration.md)
- [docs/security.md](docs/security.md)
