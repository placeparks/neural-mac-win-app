# Getting Started

## Prerequisites

- Python `3.12+`
- one provider path:
  - API key for OpenAI / Anthropic / OpenRouter
  - a direct ChatGPT or Claude browser session
  - a proxy relay
  - or a local OpenAI-compatible model server

## Install

```bash
# PyPI install with all built-in Python dependencies
pip install neuralclaw

# Source checkout
pip install -e .

# Development extras
pip install -e ".[dev]"

# Compatibility aliases for older setup flows
pip install -e ".[all-channels]"
pip install -e ".[sessions]"

# Everything
pip install -e ".[all,dev]"
```

Base installation already includes the Python dependencies for:

- API providers
- browser-session providers
- Telegram, Discord, and Slack adapters
- QR rendering and other built-in CLI features

External prerequisites still apply where required:

- `python -m playwright install chromium` for `chatgpt_app` and `claude_app`
- Node.js for the WhatsApp bridge
- `signal-cli` for Signal

```bash
python -m playwright install chromium
```

## First Setup

```bash
neuralclaw init
neuralclaw --help
```

Use `init` for API-backed providers.

For direct browser-session providers:

```bash
neuralclaw session setup chatgpt
neuralclaw session setup claude
neuralclaw session status
```

For proxy-backed access:

```bash
neuralclaw proxy setup
neuralclaw proxy status
```

## First Chat

```bash
neuralclaw chat
neuralclaw chat -p openai
neuralclaw chat -p proxy
neuralclaw chat -p chatgpt_app
neuralclaw chat -p claude_app
```

## Channels

```bash
neuralclaw channels setup
neuralclaw channels list
neuralclaw channels test
neuralclaw gateway
```

Private routes typically behave like `pair`; shared routes typically behave like `bound`.
If prompted, send:

```text
/pair
```

to trust the current route.

## Validate Your Setup

```bash
neuralclaw status
neuralclaw session status
neuralclaw doctor
pytest -q
python -m build --sdist --wheel
```
