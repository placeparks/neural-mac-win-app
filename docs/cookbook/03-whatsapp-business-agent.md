# Tutorial 03 - WhatsApp Business Agent

## Goal
Stand up a WhatsApp-connected assistant with conservative rate limits.

## Install
```bash
pip install neuralclaw
neuralclaw init
neuralclaw channels setup
```

## Config
```toml
[channels.whatsapp]
enabled = true

[policy]
channel_sends_per_second = 1.0
```

## Run
```bash
neuralclaw gateway
```

## Expected result
The WhatsApp adapter connects and sends paced replies without burst spam.
