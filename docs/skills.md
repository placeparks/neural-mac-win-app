# Skills Framework

NeuralClaw exposes tools through `SkillManifest`, `ToolDefinition`, and the
`SkillRegistry`.

## Built-in Skills

| Skill | Purpose | Example tools |
|---|---|---|
| `web_search` | search and fetch | `web_search`, `fetch_url` |
| `file_ops` | bounded filesystem access | `read_file`, `write_file`, `list_directory` |
| `code_exec` | sandboxed execution | `execute_python` |
| `calendar_skill` | local calendar operations | `create_event`, `list_events`, `delete_event` |
| `github_repos` | repo management | `clone_repo`, `install_repo_deps`, `list_repos` |
| `repo_exec` | repo-local command execution | `run_repo_script`, `run_repo_command` |
| `api_client` | authenticated outbound APIs | `api_request`, `save_api_config`, `list_api_configs` |
| `tts` | text-to-speech | `speak`, `list_voices`, `speak_and_play` |
| `google_workspace` | Gmail, Calendar, Drive, Docs, Sheets | `gmail_*`, `gcal_*`, `gdrive_*`, `gdocs_*`, `gsheets_*`, `gmeet_create` |
| `microsoft365` | Outlook, Teams, OneDrive, SharePoint | `outlook_*`, `ms_cal_*`, `teams_*`, `onedrive_*`, `sharepoint_*` |

Dynamic tool groups are registered by the gateway only when enabled:

- browser tools
- desktop tools

## Manifest Model

```python
from neuralclaw.skills.manifest import SkillManifest, ToolDefinition, ToolParameter

manifest = SkillManifest(
    name="my_skill",
    description="Does useful work",
    tools=[
        ToolDefinition(
            name="my_tool",
            description="Example tool",
            parameters=[
                ToolParameter("query", "string", "What to search for"),
            ],
            handler=my_tool,
        )
    ],
)
```

## Capability Model

Important capability groups now include:

- browser control and browser JS
- desktop control
- audio output and voice channel
- Google Workspace capabilities
- Microsoft 365 capabilities

The capability verifier provides default grants for built-ins and blocks
ungranted capabilities at runtime.

## Security Requirements

Builtin skill handlers should:

- return `dict[str, Any]`
- catch failures and return `{"error": "..."}`
- validate outbound URLs through `validate_url_with_dns()`
- rely on policy and idempotency for side-effect safety

## SkillScout — Intelligent Skill Discovery

### Overview

SkillScout is a discovery layer that sits in front of SkillForge. Instead of
requiring users to find a skill source and forge it manually, SkillScout lets
them describe what they need in plain language. It searches five registries in
parallel, ranks the results using a combination of LLM reasoning and heuristic
signals, selects the best candidate, and pipes it directly to
`SkillForge.steal()` for automatic skill creation.

### Supported Registries

| Registry | What it searches |
|----------|-----------------|
| PyPI | Python packages by keyword and classifier |
| GitHub | Repositories by topic, description, and README |
| npm | Node packages by keyword |
| MCP Registry | Model Context Protocol servers and tools |
| Claw Club | NeuralClaw community marketplace |

All five registries are queried concurrently. Results are merged into a single
ranked candidate list before selection.

### Ranking

Candidates are ranked using a hybrid approach:

1. **LLM-powered ranking** — an LLM scores each candidate for relevance to the
   user's query, weighing description match, documentation quality, and
   ecosystem fit.
2. **Heuristic fallback** — when LLM ranking is unavailable or as a tiebreaker,
   candidates are scored by stars/downloads, maintenance recency, license
   permissiveness, and registry priority.

The top-ranked candidate is automatically forwarded to SkillForge for skill
generation.

### Channel Commands

```
Discord:   !scout <query>
Telegram:  /scout <query>
Slack:     scout <query>
WhatsApp:  scout: <query>
CLI:       neuralclaw scout find <query>
           neuralclaw scout search <query>
```

### Agent Self-Scouting

The `scout_skill` tool lets the agent discover and install new capabilities
mid-conversation. When the agent determines it lacks a skill needed for the
current task, it can call `scout_skill` to search all registries, rank results,
and forge the best match — all without user intervention.

### CLI Commands

```bash
neuralclaw scout find <query>       # Search and auto-forge the best result
neuralclaw scout search <query>     # Search only — list candidates without forging
```

### Full Flow Example

```
User:  "I need to send SMS reminders"

  1. SkillScout receives the query
  2. Searches PyPI, GitHub, npm, MCP Registry, and Claw Club in parallel
  3. Collects candidates: twilio (PyPI), vonage-sms (npm), sms-mcp (MCP Registry), ...
  4. LLM + heuristic ranking picks twilio as the best match
  5. Pipes "twilio" to SkillForge.steal(source="twilio", use_case="send SMS reminders")
  6. SkillForge generates the skill, tests it, and registers it
  7. Agent now has SMS tools available and responds to the user
```

---

## SkillForge — Proactive Skill Synthesis

### Overview

SkillForge is the proactive counterpart to the reactive SkillSynthesizer. While the
synthesizer triggers when tasks fail, SkillForge takes any input and produces a
deployable skill on demand. Point it at a URL, an OpenAPI spec, a Python library
name, or even a plain-English description and it will generate a fully functional
skill — complete with manifest, async tool handlers, and sandbox tests — ready for
the agent to use immediately.

### Supported Input Types

| Input | Example | How it works |
|-------|---------|--------------|
| URL | `https://api.stripe.com/v1` | Probes endpoint, checks for OpenAPI spec, infers interface |
| OpenAPI/Swagger | `https://api.example.com/openapi.json` | Parses spec, groups endpoints by semantic purpose |
| GraphQL | `https://api.example.com/graphql` | Introspects schema, generates query/mutation tools |
| Python library | `twilio` | Introspects public functions, generates async wrappers |
| Description | `"send appointment reminders via SMS"` | Pure LLM synthesis with use-case interview |
| Code | Existing `.py` file | Wraps functions as async tools with error handling |
| GitHub repo | `https://github.com/owner/repo` | Fetches README + code, identifies key interfaces |
| MCP server | `https://mcp.example.com/sse` | Fetches tools/list, generates NeuralClaw wrappers |
| File | `./openapi.json`, `./script.py` | Auto-detects format and routes accordingly |

### The Use-Case Interview

The key differentiator. Before generating code, SkillForge asks: "What do you
actually need this to do?" A Stripe skill for a solar company gets different tools
than one for a chiro clinic. This ensures the generated skill contains only the
tools that matter for the user's domain, with sensible defaults and parameter names
tailored to their workflow.

### Channel Commands

```
Discord:   !forge <source> [--for <use_case>]
Telegram:  /forge <source> [for: <use_case>]
Slack:     forge <source> [for: <use_case>]
WhatsApp:  forge: <source>
CLI:       neuralclaw forge create <source> [--use-case <use_case>]
```

### Multi-Turn Clarification

If SkillForge can't design good domain-specific tools from the input alone, it asks
clarification questions in the channel thread. The user answers, and the forge
continues. This keeps the conversation natural and avoids generating overly generic
skills when a few follow-up questions would produce something far more useful.

### Agent Self-Forging

The `forge_skill` tool lets the agent proactively expand its own capabilities
mid-conversation. When a user asks the agent to "learn" something new, the agent
can call `forge_skill` to create and register a new skill on the spot. The new
tools become available immediately without restarting the gateway.

### Hot Loading

Skills saved to `~/.neuralclaw/skills/` are automatically detected and loaded by
the `SkillHotLoader` without requiring a gateway restart. Modified skills are
re-loaded on the next poll cycle (3 seconds).

### Security

- All URLs pass SSRF validation before any HTTP request
- Generated code runs through `StaticAnalyzer.scan()` — high-severity findings block the forge
- All code is sandbox-tested before registration
- Auto-fix is attempted once if sandbox test fails
- Skills that access the filesystem require `allow_filesystem_skills = true`

### Configuration

```toml
[forge]
model                   = "claude-sonnet-4-20250514"
user_skills_dir         = ""          # defaults to ~/.neuralclaw/skills/
hot_reload              = true
sandbox_timeout         = 15
max_tools_per_skill     = 10
allow_network_skills    = true
allow_filesystem_skills = false
require_use_case        = false

[features]
skill_forge             = true
```

### CLI Commands

```bash
neuralclaw forge create <source> [--use-case "..."] [--dry-run]
neuralclaw forge list
neuralclaw forge show <skill_name>
neuralclaw forge remove <skill_name>
```

### Architecture

```
User Input → detect_input_type() → forge_from_*()
                                       ↓
                              _run_use_case_interview()
                                       ↓
                              _generate_skill_code()
                                       ↓
                              StaticAnalyzer.scan()
                                       ↓
                              _sandbox_test() → _attempt_fix() if failed
                                       ↓
                              _persist_skill() → _build_manifest_from_spec()
                                       ↓
                              registry.register() → live in agent
```
