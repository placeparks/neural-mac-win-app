# NeuralClaw Commands

Version target: `1.1.0`

## Install

```bash
# Default install with all Python-side features
pip install neuralclaw

# Local editable install
pip install -e .

# Development extras
pip install -e ".[dev]"

# Compatibility aliases
pip install -e ".[all-channels]"
pip install -e ".[sessions]"
pip install -e ".[all,dev]"
python -m playwright install chromium
```

Notes:

- `pip install neuralclaw` includes the Python dependencies for built-in providers and channels.
- WhatsApp still needs Node.js for the bridge.
- Signal still needs `signal-cli` installed separately.

## Core

```bash
neuralclaw init
neuralclaw chat
neuralclaw --help
neuralclaw chat --help
neuralclaw chat -p openai
neuralclaw chat -p anthropic
neuralclaw chat -p openrouter
neuralclaw chat -p proxy
neuralclaw chat -p chatgpt_app
neuralclaw chat -p claude_app
neuralclaw chat -p local
neuralclaw gateway
neuralclaw local --help
neuralclaw local setup
neuralclaw local status
neuralclaw status
neuralclaw doctor
neuralclaw repair
neuralclaw --version
```

## Session Providers

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
- `pair`: send `/pair` once
- `bound`: only trusted routes may talk; `/pair` creates the binding

## Gateway Options

```bash
neuralclaw gateway --name Agent-2
neuralclaw gateway --federation-port 8101
neuralclaw gateway --dashboard-port 8081
neuralclaw gateway --web-port 8082
neuralclaw gateway --seed http://localhost:8100
```

## Swarm / Federation / Benchmark

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

Subcommands:

| Subcommand | Purpose |
|---|---|
| `forge create <source>` | Generate a new skill from a URL, API spec, library name, repo, MCP server, or description. Use `--use-case` to tailor the output. |
| `forge list` | List all forged skills in `~/.neuralclaw/skills/` |
| `forge show <name>` | Display the manifest and source of a forged skill |
| `forge remove <name>` | Delete a forged skill from disk |

## Release Validation

```bash
pytest -q
python -m compileall neuralclaw
python -m build --sdist --wheel
```
