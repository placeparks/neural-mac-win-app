# Tutorial 02 - Discord Bot With Memory

## Goal
Run a Discord bot that keeps episodic and semantic memory on.

## Install
```bash
pip install "neuralclaw[vector]"
neuralclaw init
neuralclaw channels setup
```

## Config
```toml
[channels.discord]
enabled = true

[features]
semantic_memory = true
vector_memory = true
```

## Run
```bash
neuralclaw gateway
```

## Expected result
The bot replies in Discord and can recall prior discussion topics.
