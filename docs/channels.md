# Channel Adapters

NeuralClaw supports Telegram, Discord, Slack, WhatsApp, Signal, and built-in web chat.

## Install

```bash
pip install -e ".[all-channels]"
```

## Trust Model

Every channel route is evaluated before perception, memory, or reasoning.

Supported trust modes:

| Mode | Meaning |
|---|---|
| `open` | Always trust inbound messages |
| `pair` | Require `/pair` once for that route |
| `bound` | Only trusted routes may talk; `/pair` can create the first binding |

Typical defaults:

- web / local interactive routes: `open`
- private chats and DMs: `pair`
- shared channels, groups, and servers: `bound`

Bindings are stored in `~/.neuralclaw/data/channel_bindings.json`.

## Setup

```bash
neuralclaw channels setup
neuralclaw channels list
neuralclaw channels test
```

## Telegram

- token via `@BotFather`
- inbound trust route is chat-based
- private chats pair easily
- group chats are better with `bound`

Example:

```toml
[channels.telegram]
enabled = true
trust_mode = "pair"
```

## Discord

- requires `discord.py`
- responds in DMs or mentions
- route identity includes guild/channel context when present

Example:

```toml
[channels.discord]
enabled = true
trust_mode = "bound"
```

## Slack

- requires bot token and app token
- Socket Mode based
- route identity includes workspace + channel and preserves thread context

Example:

```toml
[channels.slack]
enabled = true
trust_mode = "bound"
```

## WhatsApp

- uses the Baileys bridge
- pair with:

```bash
neuralclaw channels connect whatsapp
```

- route identity is WhatsApp chat-based

## Signal

- uses `signal-cli`
- route identity is sender/chat-based

## Web Chat

- always added by the gateway
- intended for local/dev use
- behaves like a private route

## Pairing Flow

In `pair` or `bound` mode:

1. send `/pair`
2. NeuralClaw stores a trusted binding for that route
3. future messages on that route are trusted automatically

## Troubleshooting

| Issue | Fix |
|---|---|
| Telegram bot does not answer | verify token and trust mode |
| Discord mention ignored | confirm bot mention or DM and trust binding |
| Slack replies outside thread | ensure thread-capable route is used |
| WhatsApp not connected | run `neuralclaw channels connect whatsapp` again |
| Route keeps asking to pair | delete stale binding file and pair again |
