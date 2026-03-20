# Channel Adapters

NeuralClaw supports Telegram, Discord, Slack, WhatsApp, Signal, and built-in
web chat.

## Install

```bash
pip install -e ".[all-channels]"
pip install -e ".[voice]"   # optional Discord voice playback
```

## Trust Model

Every inbound route is evaluated before perception, memory, or reasoning.

| Mode | Meaning |
|---|---|
| `open` | always trust inbound messages |
| `pair` | require `/pair` once for that route |
| `bound` | only trusted routes may talk |

Bindings are stored in `~/.neuralclaw/data/channel_bindings.json`.

Typical defaults:

- web / local routes: `open`
- private chats and DMs: `pair`
- shared servers and channels: `bound`

## Streaming

Streaming response support is additive:

- Discord edits a placeholder message
- Telegram edits a placeholder message
- Web pushes incremental deltas
- other adapters fall back to buffered `send()`

If output filtering is enabled, the gateway deliberately falls back to buffered
delivery so Prompt Armor can screen the final text before it is sent.

## Discord

Discord supports:

- DMs and mention replies
- streamed text editing
- optional voice-channel playback of responses

```toml
[channels.discord]
enabled = true
trust_mode = "bound"
voice_responses = false
auto_disconnect_empty_vc = true
voice_channel_id = ""
```

Voice playback requires:

- `features.voice = true`
- `[tts].enabled = true`
- either `channels.discord.voice_responses = true` or `[tts].auto_speak = true`

## Telegram

- token via `@BotFather`
- route identity is chat-based
- supports streaming edit updates

## Slack

- requires bot token and app token
- uses Socket Mode
- preserves `thread_ts` so replies stay inside the originating thread

## WhatsApp

- uses the Baileys bridge
- pair with `neuralclaw channels connect whatsapp`

## Signal

- uses `signal-cli`

## Forge Command Triggers

SkillForge commands are intercepted by each channel adapter **before** normal message processing, so they never reach the LLM router. Each platform uses its own trigger pattern:

| Platform | Pattern |
|---|---|
| Discord | `!forge <source> [--for <use_case>]` |
| Telegram | `/forge <source> [for: <use_case>]` |
| Slack | `forge <source> [for: <use_case>]` |
| WhatsApp | `forge: <source>` |

## Web Chat

- always added by the gateway
- intended for local/dev use
