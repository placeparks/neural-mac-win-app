# Tutorial 04 - Personal AI on Pi 5

## Goal
Run NeuralClaw on a Raspberry Pi 5 with a local model.

## Install
```bash
python3.12 -m venv ~/neuralclaw-env
source ~/neuralclaw-env/bin/activate
pip install "neuralclaw[vector]"
neuralclaw init
```

## Config
```toml
[providers]
primary = "local"

[providers.local]
model = "qwen3.5:2b"
base_url = "http://localhost:11434/v1"

[policy]
max_concurrent_requests = 3
```

## Run
```bash
neuralclaw service install
neuralclaw service start
```

## Expected result
`/health` returns healthy and the Pi stays within a small memory budget.
