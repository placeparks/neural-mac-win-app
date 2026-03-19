# Tutorial 01 - Your First Telegram Bot in 10 Minutes

## What you'll build
A Telegram bot with persistent memory and the default provider stack.

## Install
```bash
pip install "neuralclaw[vector]"
neuralclaw init
neuralclaw channels setup
```

## Config
```toml
[channels.telegram]
enabled = true
```

## Run
```bash
neuralclaw gateway
```

## Expected result
Your Telegram bot replies and remembers follow-up preferences.
