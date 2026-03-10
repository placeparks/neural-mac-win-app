# ⚙️ Configuration

NeuralClaw uses a TOML config file for settings and the OS keychain for
secrets. This guide covers every configuration option.

---

## File Locations

| Path | Purpose |
|------|---------|
| `~/.neuralclaw/config.toml` | Main configuration file |
| `~/.neuralclaw/data/memory.db` | SQLite memory database |
| `~/.neuralclaw/logs/` | Log files |

The `~` represents your home directory:
- **Linux/macOS:** `/home/username/`
- **Windows:** `C:\Users\Username\`

---

## Generating the Config

```bash
neuralclaw init
```

This creates `~/.neuralclaw/config.toml` with default values if it
doesn't exist.

---

## Full Config Reference

```toml
[general]
name = "NeuralClaw"
persona = "You are NeuralClaw, a helpful and intelligent AI assistant."
log_level = "INFO"                    # DEBUG, INFO, WARNING, ERROR
telemetry_stdout = true               # Print reasoning traces to terminal

[providers]
primary = "openai"                    # Primary LLM provider
fallback = ["openrouter", "local"]    # Fallback order

[providers.openai]
model = "gpt-4o"
base_url = "https://api.openai.com/v1"

[providers.anthropic]
model = "claude-sonnet-4-20250514"
base_url = "https://api.anthropic.com"

[providers.openrouter]
model = "anthropic/claude-sonnet-4-20250514"
base_url = "https://openrouter.ai/api/v1"

[providers.local]
model = "llama3"
base_url = "http://localhost:11434/v1"  # Ollama

[memory]
db_path = "~/.neuralclaw/data/memory.db"
max_episodic_results = 10             # Max episodes per search
max_semantic_results = 5              # Max facts per search
importance_threshold = 0.3            # Minimum importance to keep

[security]
threat_threshold = 0.7                # Score to flag a message
block_threshold = 0.9                 # Score to block a message
max_skill_timeout_seconds = 30        # Skill execution timeout
allow_shell_execution = false         # Allow shell commands (DANGER)

[channels.telegram]
enabled = false

[channels.discord]
enabled = false

[features]
# Feature flags — set to false to run in lite mode (lower RAM, faster cold start).
# Lite mode disables: swarm, dashboard, evolution cortex, reflective reasoning,
# procedural memory, and semantic memory. Core reasoning, security, episodic
# memory, fast-path, and all channel adapters remain fully active.
swarm = true                  # Agent mesh, delegation, consensus
dashboard = true              # Web dashboard on port 7474
evolution = true              # Behavioral calibrator, distiller, synthesizer
reflective_reasoning = true   # Multi-step planning (uses extra LLM calls)
procedural_memory = true      # Trigger-pattern procedure matching
semantic_memory = true        # Knowledge graph

[federation]
enabled = true                    # Start federation server with gateway
port = 8100                       # Federation HTTP port
bind_host = "127.0.0.1"          # Bind address
seed_nodes = []                   # Peers to auto-join on startup, e.g. ["http://peer:8100"]
heartbeat_interval = 60           # Seconds between heartbeats
node_name = ""                    # Override node name (defaults to general.name)

[policy]
# Tool allowlist — only tools in this list are permitted at runtime.
# If the list is empty, all tools are allowed (legacy behaviour).
# Recommended: keep this explicit for production deployments.
allowed_tools = [
    "web_search",
    "fetch_url",
    "read_file",
    "write_file",
    "list_directory",
    "execute_python",
    "create_event",
    "list_events",
    "delete_event",
]

# Tools that cause side effects and are protected by idempotency.
# Retried calls with the same arguments will be de-duplicated automatically.
mutating_tools = [
    "write_file",
    "create_event",
    "delete_event",
]

# Filesystem roots the agent may read/write (absolute paths).
# Paths outside these roots are denied by the policy engine.
allowed_roots = ["~/.neuralclaw/workspace"]

# Block SSRF: deny requests to private IPs, loopback, and cloud metadata.
deny_private_networks = true

# Maximum tool calls per single reasoning turn (0 = unlimited).
max_tool_calls_per_turn = 20
```

---

## API Keys

API keys are stored in the **OS keychain**, not in the config file.

### Set via CLI

```bash
neuralclaw init  # Interactive setup
```

### Set via Python

```python
from neuralclaw.config import set_api_key, get_api_key

set_api_key("openai", "sk-...")
set_api_key("anthropic", "sk-ant-...")
set_api_key("telegram", "123456:ABC-DEF...")
```

### Set via Environment Variables

Environment variables take priority over the keychain:

```bash
# LLM providers
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export OPENROUTER_API_KEY=sk-or-...

# Channel tokens
export NEURALCLAW_TELEGRAM_TOKEN=123456:ABC-DEF...
export NEURALCLAW_DISCORD_TOKEN=MTIz...
```

### Key Lookup Order

1. Environment variable (e.g., `OPENAI_API_KEY`)
2. OS keychain (stored via `neuralclaw init` or `set_api_key()`)

---

## Provider Configuration

### Switching Primary Provider

Edit `~/.neuralclaw/config.toml`:

```toml
[providers]
primary = "anthropic"  # Changed from "openai"
```

### Using Local Models (Ollama)

1. Install Ollama: [ollama.ai](https://ollama.ai)
2. Pull a model: `ollama pull llama3`
3. Set primary to local:

```toml
[providers]
primary = "local"

[providers.local]
model = "llama3"
base_url = "http://localhost:11434/v1"
```

### Custom Base URLs

For self-hosted or proxy endpoints:

```toml
[providers.openai]
model = "gpt-4o"
base_url = "https://my-proxy.example.com/v1"
```

---

## Channel Auto-Enable

Channels are **automatically enabled** when a token is configured
(either via keychain or environment variable). You can explicitly
disable a channel:

```toml
[channels.telegram]
enabled = false  # Won't start even if token exists
```

---

## Persona Customization

Customize how NeuralClaw responds:

```toml
[general]
name = "Jarvis"
persona = "You are Jarvis, a witty and helpful AI butler with a dry sense of humor."
```

---

## Security Tuning

### Strict Mode (high security)

```toml
[security]
threat_threshold = 0.5    # Lower = more sensitive
block_threshold = 0.7     # Lower = blocks more
allow_shell_execution = false
max_skill_timeout_seconds = 10
```

### Permissive Mode (testing)

```toml
[security]
threat_threshold = 0.9
block_threshold = 0.95
allow_shell_execution = true
max_skill_timeout_seconds = 60
```

---

## Data Classes

The config is loaded into typed dataclasses:

| Class | Fields |
|-------|--------|
| `NeuralClawConfig` | name, persona, log_level, telemetry_stdout, primary_provider, fallback_providers, memory, security, federation, channels |
| `ProviderConfig` | name, model, base_url, api_key |
| `MemoryConfig` | db_path, max_episodic_results, max_semantic_results, importance_threshold |
| `SecurityConfig` | threat_threshold, block_threshold, max_skill_timeout_seconds, allow_shell_execution |
| `FederationConfig` | enabled, port, bind_host, seed_nodes, heartbeat_interval, node_name |
| `ChannelConfig` | name, enabled, token, extra |
