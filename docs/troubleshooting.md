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

## SkillForge Issues

### `forge` command not recognized

Make sure SkillForge is enabled in your config:

```toml
[features]
skill_forge = true
```

### Static analysis blocked my skill

The generated code triggered a security flag during static analysis. Try providing a more specific use case description so the generator produces narrower code, or edit the generated file manually in `~/.neuralclaw/skills/` to remove the flagged pattern.

### Sandbox test failed

SkillForge attempts one automatic fix when a sandbox test fails. If it still fails after the retry, inspect the error details:

```bash
neuralclaw forge show <name>
```

Review the reported error and fix the generated file manually.

### Forged skill not loading

Verify that hot reload is enabled so the gateway picks up new skill files:

```toml
[forge]
hot_reload = true
```

Also confirm the generated file is valid Python and exports a `get_manifest()` function.

### `forge_skill` tool not appearing

Ensure SkillForge is enabled in features and restart the gateway:

```toml
[features]
skill_forge = true
```

```bash
neuralclaw restart
```

## SkillScout Issues

### "No candidates found"

The search query may be too broad or too long. Try a more specific or shorter query:

```bash
neuralclaw scout find "password strength checker"
```

### Wrong candidate chosen

If Scout auto-selects the wrong candidate, run the search step separately, review the results, then forge the correct one manually:

```bash
neuralclaw scout search "what you need"
neuralclaw forge create "<correct-candidate>" --use-case "your use case"
```

### Scout works but forged skill does not execute

This is a known code-generation fragility. The candidate metadata was valid but the generated code failed at runtime. Try re-forging the same candidate:

```bash
neuralclaw scout find "your query"
```

If the problem persists, inspect the generated file in `~/.neuralclaw/skills/` and fix it manually.

## Validation and Build

Run the full release validation path:

```bash
pytest -q
python -m compileall neuralclaw
python -m build --sdist --wheel
python -m twine check dist/*
```

If build artifacts look stale, delete `build/`, the extracted `neuralclaw-*` source tree, and old `dist/` files, then rebuild.

For PyPI publishing, make sure the version in `pyproject.toml`, `neuralclaw/__init__.py`,
and `CHANGELOG.md` all match before pushing the release tag or triggering the
publish workflow manually.
