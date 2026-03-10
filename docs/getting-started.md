# 🚀 Getting Started

This guide walks you through installing NeuralClaw, configuring your first
LLM provider, and running your first conversation.

---

## Prerequisites

- **Python 3.12+** — [python.org/downloads](https://www.python.org/downloads/)
- At least one LLM provider (or Ollama for fully local operation)

---

## Installation

### From PyPI (recommended)

```bash
# Core install
pip install neuralclaw

# With all messaging channel adapters
pip install "neuralclaw[all-channels]"

# Or install a specific channel only
pip install "neuralclaw[telegram]"
pip install "neuralclaw[discord]"
pip install "neuralclaw[slack]"
```

### Using pipx (isolated environment)

```bash
pipx install "neuralclaw[all-channels]"
```

### From Source (development)

```bash
git clone https://github.com/placeparks/neuralclaw.git
cd neuralclaw
pip install -e ".[dev]"
```

---

## Upgrading

To upgrade an existing installation to the latest version (e.g., from 0.4.0 to 0.4.1):

```bash
# Upgrade from PyPI
pip install --upgrade neuralclaw

# Or if you used pipx
pipx upgrade neuralclaw
```

> **Note on 0.4.1 Configs:** Version 0.4.1 introduces new safety configurations. Your existing `config.toml` will continue to work perfectly via default values. To manually tune the new `[policy]` and `[security]` bounds, refer to the [Security Guide](security.md).

---

## First-Time Setup

Run the interactive wizard:

```bash
neuralclaw init
```

This will:
1. Create the config directory at `~/.neuralclaw/`
2. Write a default `config.toml`
3. Prompt you to enter API keys for your LLM providers
4. Store keys securely in your OS keychain (never in plaintext)

### LLM Providers

| Provider | Key Source | Model |
|----------|-----------|-------|
| **OpenAI** | [platform.openai.com](https://platform.openai.com) | GPT-4o |
| **Anthropic** | [console.anthropic.com](https://console.anthropic.com) | Claude 3.5 Sonnet |
| **OpenRouter** | [openrouter.ai](https://openrouter.ai) | Multi-model access |
| **Local (Ollama)** | No key needed | Llama 3, Mistral, etc. |

You only need **one** provider. NeuralClaw supports automatic fallback if your
primary provider fails.

---

## Your First Chat

```bash
neuralclaw chat
```

This starts an interactive terminal session. NeuralClaw will:
- Process your message through the full cognitive pipeline
- Use threat screening (pre-LLM security)
- Store the conversation in episodic memory
- Route to fast-path or deliberative reasoning as needed

### Chat with a Specific Provider

```bash
neuralclaw chat --provider openai
neuralclaw chat --provider anthropic
neuralclaw chat --provider local       # Ollama
```

Type `exit` or `quit` to end the session.

---

## Check Your Status

```bash
neuralclaw status
```

Shows your full configuration: providers, channels, security settings.

---

## What's Next?

- **[Set up messaging channels](channels.md)** — Connect Telegram, Discord, or Slack
- **[Start the gateway](channels.md#starting-the-gateway)** — Run all channels simultaneously
- **[Launch the dashboard](architecture.md#dashboard)** — Live monitoring
- **[Explore the architecture](architecture.md)** — Understand the cognitive pipeline
