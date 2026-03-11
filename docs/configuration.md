# Configuration

NeuralClaw stores config in `~/.neuralclaw/config.toml` and secrets in the OS keychain.

## Key Paths

| Path | Purpose |
|---|---|
| `~/.neuralclaw/config.toml` | main config |
| `~/.neuralclaw/data/memory.db` | memory database |
| `~/.neuralclaw/data/channel_bindings.json` | trusted channel routes |
| `~/.neuralclaw/sessions/` | managed ChatGPT / Claude browser profiles |

## Example Config

```toml
[general]
name = "NeuralClaw"
persona = "You are NeuralClaw, a helpful and intelligent AI assistant."
log_level = "INFO"
telemetry_stdout = true

[providers]
primary = "chatgpt_app"
fallback = ["proxy", "openrouter", "local"]

[providers.openai]
model = "gpt-4o"
base_url = "https://api.openai.com/v1"

[providers.anthropic]
model = "claude-sonnet-4-20250514"
base_url = "https://api.anthropic.com"

[providers.openrouter]
model = "anthropic/claude-sonnet-4-20250514"
base_url = "https://openrouter.ai/api/v1"

[providers.proxy]
model = "gpt-4"
base_url = "http://localhost:3040/v1"

[providers.chatgpt_app]
model = "auto"
profile_dir = "~/.neuralclaw/sessions/chatgpt"
headless = false
browser_channel = ""
site_url = "https://chatgpt.com/"

[providers.claude_app]
model = "auto"
profile_dir = "~/.neuralclaw/sessions/claude"
headless = false
browser_channel = ""
site_url = "https://claude.ai/chats"

[providers.local]
model = "qwen3.5:2b"
base_url = "http://localhost:11434/v1"

[channels.telegram]
enabled = false
trust_mode = "pair"

[channels.discord]
enabled = false
trust_mode = "bound"

[channels.slack]
enabled = false
trust_mode = "bound"

[channels.whatsapp]
enabled = false
trust_mode = "pair"

[channels.signal]
enabled = false
trust_mode = "pair"
```

## Provider Notes

### API-backed providers

Configure with:

```bash
neuralclaw init
neuralclaw proxy setup
neuralclaw local setup
```

### Browser-session providers

Configure with:

```bash
neuralclaw session setup chatgpt
neuralclaw session setup claude
neuralclaw session status
```

Requirements:

- `pip install -e ".[sessions]"`
- `python -m playwright install chromium`

NeuralClaw stores only the local profile directory and session metadata, not raw cookies in config.

### Local provider

If Ollama is running on the default port, configure it with:

```bash
neuralclaw local setup
neuralclaw local status
```

NeuralClaw queries `http://localhost:11434/api/tags` and saves the selected
model into `[providers.local]`.

## Channel Trust

`trust_mode` can be:

- `open`
- `pair`
- `bound`

If omitted, the runtime chooses a sensible default from the route type.

## Environment Variables

```bash
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
export OPENROUTER_API_KEY=...

export NEURALCLAW_TELEGRAM_TOKEN=...
export NEURALCLAW_DISCORD_TOKEN=...
export NEURALCLAW_SLACK_BOT_TOKEN=...
export NEURALCLAW_SLACK_APP_TOKEN=...
```

## Validation

```bash
neuralclaw status
neuralclaw session status
neuralclaw doctor
```
