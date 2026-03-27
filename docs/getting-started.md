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
neuralclaw gateway     # foreground
neuralclaw daemon      # background
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
python -m twine check dist/*
```

## Keep It Running

Use one of these depending on how persistent you want the gateway to be:

```bash
neuralclaw gateway          # foreground terminal session
neuralclaw daemon           # detached background process
neuralclaw startup install  # auto-start on login (Windows, no admin)
neuralclaw service install  # install managed service
neuralclaw service start    # start managed service
neuralclaw alive            # check if background gateway is running
neuralclaw logs             # inspect gateway logs
```

## Prepare a PyPI Release

```bash
pip install -e ".[dev]"
pytest -q
python -m compileall neuralclaw
python -m build --sdist --wheel
python -m twine check dist/*
```

Publish from GitHub Actions by pushing a version tag such as `v1.2.9`, or run
the manual publish workflow after validating the generated artifacts.

## Forge Your First Skill

SkillForge lets you create new skills from a plain-language description.

```bash
# From CLI
neuralclaw forge create "I want to send SMS reminders" --use-case "appointment reminders for my clinic"

# Or from Telegram
/forge twilio for: send appointment reminders
```

## Scout Your First Skill

SkillScout searches public registries for existing skill candidates and can forge them automatically:

```bash
neuralclaw scout find "check password strength"
```

Scout finds the best matching candidate, passes it to SkillForge, and registers the resulting skill with the gateway -- all in one command.
