# 📡 Channel Adapters

NeuralClaw supports **6 messaging channels**, turning your agent into
a multi-platform AI assistant. All channels connect through the same
cognitive pipeline — one brain, many interfaces.

---

## Supported Channels

| Channel | Protocol | Dependency | Install Extra |
|---------|----------|------------|---------------|
| **Telegram** | Bot API | `python-telegram-bot` | `neuralclaw[telegram]` |
| **Discord** | Bot (Gateway) | `discord.py` | `neuralclaw[discord]` |
| **Slack** | Socket Mode | `slack-bolt` | `neuralclaw[slack]` |
| **WhatsApp** | `whatsapp-web.js` bridge | Node.js 18+ | — |
| **Signal** | `signal-cli` JSON-RPC | signal-cli installed | — |
| **Web Chat** | Built-in HTTP | None (bundled) | — |

Install all at once:

```bash
pip install "neuralclaw[all-channels]"
```

---

## Quick Setup

```bash
neuralclaw channels setup
```

This interactive wizard guides you through configuring each channel.
Tokens are stored securely in your OS keychain.

---

## Telegram

### Setup

1. Open Telegram and message **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the bot token (looks like `123456:ABC-DEF...`)
4. Run:

```bash
neuralclaw channels setup
# Paste your token when prompted for Telegram
```

### Start

```bash
neuralclaw gateway
```

Message your bot on Telegram — NeuralClaw will respond with full
cognitive processing.

---

## Discord

### Setup

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application** → give it a name
3. Go to **Bot** tab → click **Reset Token** → copy the token
4. **Important:** Enable **Message Content Intent** in Bot settings
5. Go to **OAuth2 → URL Generator**:
   - Scopes: `bot`
   - Permissions: `Send Messages`, `Read Message History`
6. Copy the generated URL and open it to invite the bot to your server
7. Run:

```bash
neuralclaw channels setup
# Paste your token when prompted for Discord
```

### Start

```bash
neuralclaw gateway
```

---

## Slack

### Setup

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App**
2. Choose **From scratch** → name it → select workspace
3. Enable **Socket Mode** (Settings → Socket Mode → toggle on)
4. Generate an **App-Level Token** with `connections:write` scope
   - This gives you `xapp-...`
5. Go to **OAuth & Permissions** → add bot scopes:
   - `chat:write`, `app_mentions:read`, `im:history`, `im:read`, `im:write`
6. Install to workspace and copy the **Bot User OAuth Token** (`xoxb-...`)
7. Run:

```bash
neuralclaw channels setup
# Paste both tokens when prompted
```

### Start

```bash
neuralclaw gateway
```

---

## WhatsApp

WhatsApp uses a Node.js bridge (`whatsapp-web.js`).

### Prerequisites

- Node.js 18+ installed

### Setup

```bash
neuralclaw channels setup
# Enter a session ID (or press Enter for default "neuralclaw")
```

When the gateway starts, it will show a QR code in the terminal.
Scan it with WhatsApp on your phone (Linked Devices → Link a Device).

### Start

```bash
neuralclaw gateway
```

---

## Signal

Signal uses the `signal-cli` JSON-RPC bridge.

### Prerequisites

- [signal-cli](https://github.com/AsamK/signal-cli) installed and registered

### Setup

```bash
neuralclaw channels setup
# Enter your Signal phone number (+1234567890)
```

### Start

```bash
neuralclaw gateway
```

---

## Web Chat

The built-in web chat adapter starts automatically with the gateway.
No configuration needed.

---

## Starting the Gateway

The gateway runs **all configured channels simultaneously**:

```bash
neuralclaw gateway
```

Output will show which channels are active:

```
🧠 NeuralClaw Gateway is running (Phase 3: Swarm)
   Provider: OpenAI (gpt-4o)
   Skills: 4 (12 tools)
   Channels: ['telegram', 'discord', 'web']
   Evolution: calibrator + distiller + synthesizer
   Swarm: delegation + consensus + mesh
```

### View Configured Channels

```bash
neuralclaw channels list
```

---

## Environment Variables

You can also set channel tokens via environment variables:

```bash
export NEURALCLAW_TELEGRAM_TOKEN=123456:ABC-DEF...
export NEURALCLAW_DISCORD_TOKEN=MTIz...
```

Channels with tokens configured (keychain or env var) are **auto-enabled**.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError: telegram` | Install: `pip install "neuralclaw[telegram]"` |
| `ModuleNotFoundError: discord` | Install: `pip install "neuralclaw[discord]"` |
| Discord bot not responding | Ensure **Message Content Intent** is enabled |
| Slack not connecting | Verify Socket Mode is enabled and both tokens are correct |
| WhatsApp QR not showing | Ensure Node.js 18+ is installed |
