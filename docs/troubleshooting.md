# 🔍 Troubleshooting

Common issues and solutions when running NeuralClaw.

---

## Installation Issues

### `neuralclaw` command not found

**Cause:** Python Scripts directory not in PATH.

**Fix:**

```bash
# Option 1: Use python -m
python -m neuralclaw.cli chat

# Option 2: Add to PATH (Linux/macOS)
export PATH="$HOME/.local/bin:$PATH"

# Option 3: Use pipx (auto-adds to PATH)
pipx install neuralclaw
```

### `ModuleNotFoundError: No module named 'telegram'`

**Cause:** Channel dependencies not installed.

**Fix:**

```bash
pip install "neuralclaw[telegram]"
# Or install all channels
pip install "neuralclaw[all-channels]"
```

### pipx reinstall with extras fails

**Cause:** `pipx reinstall` doesn't support `--pip-args` for extras.

**Fix:**

```bash
pipx uninstall neuralclaw
pipx install "neuralclaw[all-channels]"
```

---

## Configuration Issues

### No LLM provider configured

**Symptoms:** `Provider: NONE` in status output.

**Fix:**

```bash
# Option 1: Run setup wizard
neuralclaw init

# Option 2: Set env var
export OPENAI_API_KEY=sk-...

# Option 3: Use local Ollama (no key needed)
# Edit ~/.neuralclaw/config.toml:
# [providers]
# primary = "local"
```

### Keychain errors on Linux

**Cause:** No Secret Service backend available.

**Fix:**

```bash
# Install gnome-keyring
sudo apt install gnome-keyring

# Or use environment variables instead
export OPENAI_API_KEY=sk-...
```

### Config file not found

**Fix:**

```bash
neuralclaw init  # Creates ~/.neuralclaw/config.toml
```

---

## Channel Issues

### Discord bot not responding to messages

**Cause:** Message Content Intent not enabled.

**Fix:**
1. Go to [discord.com/developers](https://discord.com/developers/applications)
2. Select your app → **Bot** → enable **Message Content Intent**
3. Restart gateway

### Slack not connecting

**Cause:** Socket Mode not enabled or tokens incorrect.

**Fix:**
1. Verify Socket Mode is enabled in app settings
2. Check both tokens:
   - Bot Token: starts with `xoxb-`
   - App Token: starts with `xapp-`
3. Ensure both are stored: `neuralclaw channels list`

### WhatsApp QR code not showing

**Cause:** Node.js not installed or wrong version.

**Fix:**

```bash
node --version  # Need 18+
# If not installed:
sudo apt install nodejs npm
```

---

## Runtime Issues

### Gateway crashes on startup

**Debug:**

```bash
# Check if gateway initializes correctly
python -c "
import asyncio
from neuralclaw.gateway import NeuralClawGateway
async def t():
    gw = NeuralClawGateway()
    await gw.initialize()
    print(f'Provider: {gw._provider.name if gw._provider else \"NONE\"}')
    print(f'Skills: {gw._skills.count}')
    await gw.stop()
asyncio.run(t())
"
```

### Import errors

**Smoke test:**

```bash
python -c "from neuralclaw.gateway import NeuralClawGateway; print('OK')"
```

### Memory database locked

**Cause:** Multiple NeuralClaw instances accessing the same database.

**Fix:** Stop other instances before starting a new one.

---

## Performance Issues

### Slow responses on Raspberry Pi

**Tips:**
1. Use a lighter model: `providers.local.model = "llama3:8b"`
2. Reduce memory search: `memory.max_episodic_results = 5`
3. Lower skill timeout: `security.max_skill_timeout_seconds = 15`

### High memory usage

**Tips:**
1. The SQLite memory database grows over time
2. Metabolism automatically prunes low-importance memories
3. You can lower the importance threshold:

```toml
[memory]
importance_threshold = 0.5  # Higher = more aggressive pruning
```

---

## Debugging Commands

```bash
# Check all stored API keys
python -c "
from neuralclaw.config import get_api_key
for k in ['openai','anthropic','openrouter','telegram','discord','slack_bot','slack_app']:
    v = get_api_key(k)
    status = f'set ({v[:8]}...)' if v else 'not set'
    print(f'  {k:15s} {status}')
"

# Check config
neuralclaw status

# Check channels
neuralclaw channels list

# Run benchmarks to test performance
neuralclaw benchmark

# Check version
neuralclaw --version
```

---

## Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Full test suite (86 tests)
python -m pytest tests/ -v

# Specific modules
python -m pytest tests/test_perception.py -v
python -m pytest tests/test_memory.py -v
python -m pytest tests/test_evolution_security_swarm.py -v

# With coverage
python -m pytest tests/ --cov=neuralclaw --cov-report=term-missing
```

---

## Getting Help

- **GitHub Issues:** [github.com/placeparks/neuralclaw/issues](https://github.com/placeparks/neuralclaw/issues)
- **Commands Reference:** [COMMANDS.md](../COMMANDS.md)
- **All CLI commands:** `neuralclaw --help`
