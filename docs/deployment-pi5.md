# Raspberry Pi 5 Deployment

**Target:** Pi 5 (8GB), Raspberry Pi OS Lite (64-bit), Tailscale mesh.

## System Prerequisites

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.12 python3.12-venv python3-pip git curl sqlite3

# Increase SQLite WAL performance on SD card
echo "vm.dirty_writeback_centisecs = 1500" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

## Install NeuralClaw

```bash
# Lite profile for Pi — no browser, no desktop
python3.12 -m venv ~/neuralclaw-env
source ~/neuralclaw-env/bin/activate
pip install "neuralclaw[vector,voice]"  # voice optional, needs ffmpeg
```

## Local Inference with Ollama

```bash
# Pi 5 handles 2B-7B models well
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull qwen3.5:2b        # ~1.5GB, fits Pi 5 RAM headroom
# Optional: ollama pull nomic-embed-text  # for local vector embeddings
```

## First-Time Config

```bash
neuralclaw init
```

## Pi-Specific Config Optimizations

Add to `~/.neuralclaw/config.toml`:

```toml
[features]
browser              = false   # No Chromium on Pi
desktop              = false
reflective_reasoning = false   # Saves RAM

[memory]
max_episodic_results = 5       # Keep retrieval fast on SD card

[providers.local]
model    = "qwen3.5:2b"
base_url = "http://localhost:11434/v1"

[policy]
max_tool_calls_per_request = 5
max_request_wall_seconds   = 60   # Local inference is slower
max_concurrent_requests    = 3

[traceline]
max_preview_chars = 200            # Smaller previews → smaller DB
retention_days    = 14             # Shorter retention on Pi storage

[general]
log_level = "WARNING"              # Reduce I/O on SD
```

## Service Install

```bash
neuralclaw service install
systemctl --user enable --now neuralclaw
```

## Verify

```bash
neuralclaw doctor
curl http://localhost:8080/health
curl http://localhost:8080/ready
```

## Tips

- **Move DB to USB SSD** for longevity: set `db_path = "/mnt/usb/neuralclaw/memory.db"`
- **Daily backup** via crontab:
  ```
  0 3 * * * sqlite3 ~/.neuralclaw/data/memory.db ".backup /backup/memory_$(date +\%Y\%m\%d).db"
  ```
- **Monitor memory** with `curl http://localhost:8080/metrics | grep rss`
