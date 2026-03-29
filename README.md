# NeuralClaw

Version: `1.5.5`

NeuralClaw is a Python agent framework built around a five-cortex runtime:
Perception, Memory, Reasoning, Action, and Evolution. The current repository
state now covers the full `AGENT.md` roadmap, including vector memory,
persistent identity modeling, browser and desktop control, streaming,
structured output, observability, output filtering, audit replay, workspace
integrations, and A2A-compatible federation.

## Current Capabilities

- **Computer use**: Take screenshots, analyze screen content with vision,
  click UI elements, type text, press hotkeys, and launch apps — all
  controllable remotely via Telegram, Discord, or any channel
- **SkillForge**: Proactive skill synthesis — give it a URL, API spec, Python
  library, GitHub repo, MCP server, or plain description and it generates
  domain-specific tools tailored to your use case. Works from any channel
  (`/forge`, `!forge`, `forge:`) or the agent forges its own skills mid-conversation
- **SkillScout**: Discovery layer on top of SkillForge — searches PyPI, GitHub,
  npm, and MCP registries, ranks results by stars, maintenance, license, and
  relevance, then auto-forges the best match into a ready-to-use skill.
  Works from any channel (`/scout`, `!scout`, `scout:`)
- **App Builder**: Dedicated `build_app` workflow that provisions new projects
  under the approved apps workspace root and returns the exact directory for
  follow-up writes
- **Controlled self-improvement**: Repeated capability failures are journaled,
  converted into candidate initiatives, forged or scouted off the live path,
  and only promoted after probationary tool calls succeed in real use
- **Dynamic self-awareness**: Agent knows its own capabilities and active
  tools; never says "I can't" when it has a tool for the job
- **Multi-provider routing**: `openai` (GPT-5.4), `anthropic` (Claude 4.6),
  `openrouter`, `proxy`, `local` (Ollama) — with GPT-5/o-series API compat
- managed browser-session providers: `chatgpt_app`, `claude_app`
- token-backed session auth: `chatgpt_token`, `claude_token`
- episodic, semantic, procedural, vector, and identity memory with smart
  importance scoring
- managed workspaces for app scaffolds and cloned repos
- fast-path, deliberative, reflective, structured, and meta-cognitive reasoning
- vision perception, browser automation, and desktop automation
- streaming responses and Discord voice playback
- Google Workspace and Microsoft 365 built-in skills
- traceline observability, Prompt Armor v2, and audit replay
- swarm, native federation, and A2A interoperability

## SkillForge — Teach Your Agent New Tricks

SkillForge turns any input into a deployable NeuralClaw skill. No developer needed.

```bash
# CLI
neuralclaw forge create "https://api.stripe.com" --use-case "charge chiro patients"
neuralclaw forge create "twilio" --use-case "send appointment reminders"
neuralclaw forge create "I want to look up drug interactions"

# From Telegram
/forge https://github.com/owner/repo for: analyze X-ray reports

# From Discord
!forge twilio --for send SMS reminders

# The agent can forge its own skills mid-conversation
User: "Can you learn to query our Google Sheets?"
Agent: [forges sheets_query skill] → "Done, I can now read your reports directly."
```

Supported sources: URLs, OpenAPI/Swagger specs, GraphQL endpoints, Python libraries,
GitHub repos, MCP servers, code files, or natural language descriptions.

Skills are saved to `~/.neuralclaw/skills/` and hot-loaded without restart.

## SkillScout — Find the Best Tool, Automatically

SkillScout is a discovery layer on top of SkillForge. Instead of handing it a
specific URL or library, you describe what you need and SkillScout searches
package registries and repositories to find the best candidate, then forges it
for you.

**Flow:**

1. User says: `scout: verify patient insurance eligibility`
2. SkillScout searches PyPI, GitHub, npm, and MCP registries
3. Results are ranked by stars, maintenance status, license, and relevance
4. The best match is automatically forged into a deployable skill

```
User: scout: verify patient insurance eligibility

SkillScout searching...
  PyPI:   eligibility-check (★ 340, MIT, maintained)
  GitHub: open-insurance/eligibility-api (★ 1.2k, Apache-2.0)
  npm:    insurance-verify (★ 89, MIT)
  MCP:    mcp-insurance-eligibility (★ 210, MIT)

Best match: open-insurance/eligibility-api (★ 1.2k, Apache-2.0, active)
Forging skill... done.

✓ Skill "insurance_eligibility" forged and loaded.
  Commands: check_eligibility, get_payer_list, verify_member
```

Channel commands: `/scout`, `!scout`, `scout:`

## Install

```bash
# Core package
pip install neuralclaw

# Local checkout
pip install -e .

# Development
pip install -e ".[dev]"

# Optional extras
pip install -e ".[voice]"
pip install -e ".[browser]"
pip install -e ".[desktop]"
pip install -e ".[google]"
pip install -e ".[microsoft]"
pip install -e ".[vector]"

# Everything
pip install -e ".[all,dev]"
```

External runtimes still required for some integrations:

- Playwright browser binaries
- Node.js for the WhatsApp bridge
- `signal-cli` for Signal
- FFmpeg for Discord voice playback

```bash
python -m playwright install chromium
```

## Quick Start

```bash
neuralclaw init

neuralclaw session setup chatgpt
neuralclaw session setup claude

neuralclaw session auth chatgpt
neuralclaw session auth claude
neuralclaw session auth google
neuralclaw session auth microsoft

neuralclaw local setup
neuralclaw channels setup

neuralclaw status
neuralclaw session status
neuralclaw doctor

neuralclaw chat
neuralclaw gateway            # foreground terminal session
neuralclaw daemon             # detached background gateway
neuralclaw startup install    # auto-start on login (Windows)
neuralclaw service install    # install managed service
neuralclaw service start      # start managed service
```

## Workspace-Constrained Project Creation

For fresh coding projects, NeuralClaw now uses `build_app` instead of
inventing output directories. By default:

- app scaffolds are created under `~/.neuralclaw/workspace/apps/`
- cloned repositories live under `~/.neuralclaw/workspace/repos/`

This keeps file writes inside approved roots and gives the agent an exact
project path to use for the rest of the task.

## Providers

| Provider | Purpose | Setup |
|---|---|---|
| `openai` | official OpenAI API | `neuralclaw init` |
| `anthropic` | official Anthropic API | `neuralclaw init` |
| `openrouter` | OpenRouter relay | `neuralclaw init` |
| `proxy` | OpenAI-compatible proxy | `neuralclaw proxy setup` |
| `local` | Ollama or compatible local endpoint | `neuralclaw local setup` |
| `chatgpt_app` | managed ChatGPT browser session | `neuralclaw session setup chatgpt` |
| `claude_app` | managed Claude browser session | `neuralclaw session setup claude` |
| `chatgpt_token` | direct ChatGPT token access | `neuralclaw session auth chatgpt` |
| `claude_token` | direct Claude token access | `neuralclaw session auth claude` |

## Channel Trust

Each route can run in one of three modes:

| Mode | Behavior |
|---|---|
| `open` | always accept inbound messages |
| `pair` | require one-time `/pair` for that route |
| `bound` | only trusted bindings may talk |

Discord also supports streamed text edits and optional voice playback.

## Project Layout

```text
neuralclaw/
  bus/         event bus and telemetry
  channels/    Telegram, Discord, Slack, Signal, WhatsApp, Web, trust layer
  cortex/      perception, memory, reasoning, action, evolution, observability
  providers/   API providers, session providers, router
  session/     managed browser-session runtime
  skills/      manifest model, registry, built-ins
  swarm/       delegation, consensus, mesh, federation
  gateway.py   orchestration entrypoint
  cli.py       command-line interface
  config.py    config, keychain helpers, validation
```

## Docs

- [docs/README.md](docs/README.md)
- [docs/configuration.md](docs/configuration.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/security.md](docs/security.md)
- [docs/federation.md](docs/federation.md)

## Verification

```bash
pytest -q
python -m compileall neuralclaw
python -m build
python -m twine check dist/*
```

## PyPI Release

```bash
pip install -e ".[dev]"
pytest -q
python -m compileall neuralclaw
python -m build
python -m twine check dist/*
```

Publish from GitHub Actions by pushing a tag like `v1.5.5`, or run the manual
publish workflow after validating the changelog and built artifacts.
