# ThinkPad / Local Workstation Deployment

Full-featured deployment for development and daily use.

## Install

```bash
# Full stack — desktop + browser available on workstation
pip install "neuralclaw[all]"
python -m playwright install chromium
```

## Local Models (Optional)

```bash
# Ollama with larger models (16-32GB RAM)
ollama pull qwen3:8b
ollama pull nomic-embed-text
```

## Full Feature Config

Add to `~/.neuralclaw/config.toml`:

```toml
[features]
browser       = true
desktop       = true
vision        = true
vector_memory = true
```

## Development Mode

```bash
# Hot reload + verbose trace output + relaxed rate limits
neuralclaw gateway --dev
```

Dev mode features:
- **Config hot reload** — edit `config.toml` and changes apply without restart
- **Verbose traces** — every reasoning step printed to stdout
- **No rate limits** — faster testing iteration
- **Relaxed security** — `threat_threshold` raised so test inputs aren't blocked

## Production Mode

```bash
# Foreground terminal session
neuralclaw gateway

# Detached background process
neuralclaw daemon

# Auto-start on login (Windows, no admin)
neuralclaw startup install

# Managed service
neuralclaw service install
neuralclaw service start
```

## Verify

```bash
neuralclaw doctor
```
