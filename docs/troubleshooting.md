# Troubleshooting

## Installation

### `neuralclaw` command not found

```bash
python -m neuralclaw.cli --help
```

Or install with `pipx` / ensure your Python scripts directory is on `PATH`.

### Playwright missing for ChatGPT / Claude sessions

```bash
pip install -e ".[sessions]"
python -m playwright install chromium
```

### Missing channel dependency

```bash
pip install -e ".[all-channels]"
```

## Provider Setup

### No provider configured

```bash
neuralclaw init
neuralclaw status
```

### ChatGPT / Claude session says `login required`

```bash
neuralclaw session login chatgpt
neuralclaw session login claude
neuralclaw session status
```

If the browser profile looks stale:

```bash
neuralclaw session repair chatgpt
neuralclaw session repair claude
```

### ChatGPT lands on `/api/auth/error`

```bash
neuralclaw session diagnose chatgpt
neuralclaw session open chatgpt
```

If the diagnosis reports `auth_rejected`, the upstream login flow is rejecting
the browser-controlled session. In that case prefer:

```bash
neuralclaw chat -p proxy
neuralclaw chat -p openai
```

### ChatGPT gets stuck on Cloudflare verification

Use headed Chrome with the managed profile, complete the challenge manually,
then rerun:

```bash
neuralclaw session diagnose chatgpt
```

If you are using token auth, the preferred bootstrap flow is:

```bash
neuralclaw session auth chatgpt
```

NeuralClaw now keeps waiting while the challenge is active and prints a
terminal hint when Cloudflare is detected. Complete the checkbox in the opened
browser window, keep the terminal open, and wait for the cookie capture to
finish.

### Proxy override does not behave as expected

```bash
neuralclaw proxy status
neuralclaw chat -p proxy
```

Make sure the configured `base_url` and model are correct in `config.toml`.

## Channels

### Route keeps asking to pair

The route is not trusted yet. Send:

```text
/pair
```

in that exact route.

If needed, remove stale bindings from:

```text
~/.neuralclaw/data/channel_bindings.json
```

and pair again.

### Discord bot ignores messages

- ensure `Message Content Intent` is enabled
- DM the bot or mention it
- verify route trust mode / pairing state

### Slack replies look wrong

- verify both `xoxb-` and `xapp-` tokens
- check `channels test`
- confirm the route has been paired or bound if trust mode requires it

### WhatsApp does not connect

```bash
node --version
neuralclaw channels connect whatsapp
```

If you see repeated `Disconnected: 405` even with a fresh auth directory, that
is currently an upstream Baileys / WhatsApp-Web connection failure rather than a
Python-side dependency problem. Retry once with a clean auth dir; if it still
fails, treat WhatsApp as unstable until the upstream bridge path is updated.

## Validation and Build

Run the full release validation path:

```bash
pytest -q
python -m compileall neuralclaw
python -m build --sdist --wheel
```

If build artifacts look stale, delete `build/`, the extracted `neuralclaw-*` source tree, and old `dist/` files, then rebuild.
