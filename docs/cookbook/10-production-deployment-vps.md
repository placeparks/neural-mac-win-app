# Tutorial 10 - Production Deployment on a VPS

## Goal
Deploy a managed NeuralClaw instance on a Linux VM.

## Install
```bash
python3.12 -m venv /opt/neuralclaw
source /opt/neuralclaw/bin/activate
pip install "neuralclaw[vector,google,microsoft]"
neuralclaw init
```

## Run
```bash
neuralclaw service install
neuralclaw service start
neuralclaw doctor
```

## Expected result
The service survives restarts and `curl http://localhost:8080/health` returns healthy.
