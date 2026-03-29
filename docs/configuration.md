# Configuration

NeuralClaw stores config in `~/.neuralclaw/config.toml` and secrets in the OS
keychain or local fallback secret file managed by `config.py`.

## Key Paths

| Path | Purpose |
|---|---|
| `~/.neuralclaw/config.toml` | main configuration |
| `~/.neuralclaw/data/memory.db` | memory and idempotency state |
| `~/.neuralclaw/data/traces.db` | traceline store |
| `~/.neuralclaw/logs/audit.jsonl` | audit replay log |
| `~/.neuralclaw/data/channel_bindings.json` | trusted route bindings |
| `~/.neuralclaw/sessions/` | managed ChatGPT / Claude browser profiles |
| `~/projects/` | approved root for `build_app` project scaffolds |
| `~/.neuralclaw/workspace/repos/` | managed git clone workspace |

## Important Sections

### `[features]`

Feature-gates optional subsystems:

- `vector_memory`
- `identity`
- `vision`
- `voice`
- `browser`
- `structured_output`
- `streaming_responses`
- `traceline`
- `desktop`
- `swarm`
- `dashboard`
- `evolution`
- `reflective_reasoning`
- `procedural_memory`
- `semantic_memory`
- `a2a_federation`
- `skill_forge`
- `rag` — RAG knowledge base document ingestion and retrieval
- `workflow_engine` — DAG-based multi-step task pipelines
- `mcp_server` — Expose NeuralClaw as an MCP provider (opt-in, default false)

### `[memory]`

- `db_path`
- `max_episodic_results`
- `max_semantic_results`
- `importance_threshold`
- `vector_memory`
- `embedding_provider`
- `embedding_model`
- `embedding_dimension`
- `vector_similarity_top_k`

### `[identity]`

- `enabled`
- `cross_channel`
- `inject_in_prompt`
- `notes_enabled`

### `[traceline]`

- `enabled`
- `db_path`
- `retention_days`
- `include_input`
- `include_output`
- `max_preview_chars`

### `[audit]`

- `enabled`
- `jsonl_path`
- `max_memory_entries`
- `retention_days`
- `siem_export`
- `include_args`

### `[tts]`

- `enabled`
- `provider`
- `voice`
- `speed`
- `output_format`
- `auto_speak`
- `max_tts_chars`
- `temp_dir`
- `piper_binary`
- `piper_model`

### `[browser]`

- `enabled`
- `headless`
- `browser_type`
- `viewport_width`
- `viewport_height`
- `stealth`
- `allow_js_execution`
- `max_steps_per_task`
- `chrome_ai_enabled`
- `navigation_timeout`
- `allowed_domains`
- `blocked_domains`

### `[desktop]`

- `enabled`
- `screenshot_on_action`
- `action_delay_ms`

### `[google_workspace]`

- `enabled`
- `scopes`
- `max_email_results`
- `max_drive_results`
- `default_calendar_id`
- `response_body_limit`

### `[microsoft365]`

- `enabled`
- `tenant_id`
- `scopes`
- `max_email_results`
- `max_file_results`
- `default_user`

### `[security]`

- `threat_threshold`
- `block_threshold`
- `threat_verifier_model`
- `max_content_chars`
- `max_skill_timeout_seconds`
- `allow_shell_execution`
- `output_filtering`
- `output_pii_detection`
- `output_prompt_leak_check`
- `canary_tokens`
- `pii_patterns`

### `[policy]`

- `max_tool_calls_per_request`
- `max_request_wall_seconds`
- `allowed_tools`
- `mutating_tools`
- `allowed_filesystem_roots`
- `deny_private_networks`
- `deny_shell_execution`
- `parallel_tool_execution`
- `desktop_allowed_apps`
- `desktop_blocked_regions`

Default production-safe behavior:

- `build_app` is allowlisted as a mutating tool.
- `allowed_filesystem_roots` includes the managed apps workspace root so files
  created after `build_app` stay inside an approved path.

### `[forge]` — SkillForge & SkillScout Settings

> **Note:** SkillScout reuses the `[forge]` configuration section. No additional
> config keys are needed for scout -- it reads `model`, `user_skills_dir`,
> `sandbox_timeout`, and the other forge keys directly.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `model` | string | `"claude-sonnet-4-20250514"` | LLM model used for skill synthesis |
| `user_skills_dir` | string | `""` | Custom skills directory (default: `~/.neuralclaw/skills/`) |
| `hot_reload` | bool | `true` | Watch skills directory for new files |
| `sandbox_timeout` | int | `15` | Seconds for sandbox test execution |
| `max_tools_per_skill` | int | `10` | Maximum tools per generated skill |
| `allow_network_skills` | bool | `true` | Allow skills that make HTTP calls |
| `allow_filesystem_skills` | bool | `false` | Allow skills with file system access |
| `require_use_case` | bool | `false` | Require use_case before generating |

### `[federation]`

- `enabled`
- `port`
- `bind_host`
- `seed_nodes`
- `heartbeat_interval`
- `node_name`
- `a2a_enabled`
- `a2a_auth_required`

### `[workspace]`

Workspace roots for repo execution and app scaffolding:

- `repos_dir`
- `apps_dir`
- `max_repo_size_mb`
- `allowed_git_hosts`
- `max_clone_timeout_seconds`
- `max_install_timeout_seconds`
- `max_exec_timeout_seconds`

`build_app` always provisions new projects under `workspace.apps_dir` and
returns the exact created path, so agents do not need to guess output paths.

> **Running as a service:** When NeuralClaw runs as a Windows service or under
> a system account, `~` may resolve to the system profile directory
> (e.g. `C:\Windows\System32\config\systemprofile`). Set the
> `NEURALCLAW_PROJECTS_DIR` environment variable to an absolute path to
> override this, or use an absolute path for `apps_dir` in your config:
>
> ```toml
> [workspace]
> apps_dir = "C:/Users/youruser/projects"
> ```

### `[rag]`

RAG knowledge base for document ingestion and semantic retrieval:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `true` | Enable the knowledge base subsystem |
| `db_path` | string | `~/.neuralclaw/data/knowledge.db` | SQLite database for KB storage |
| `chunk_size` | int | `1024` | Max characters per document chunk |
| `overlap` | int | `128` | Character overlap between consecutive chunks |
| `retrieval_top_k` | int | `5` | Number of chunks returned per search |
| `max_doc_size_mb` | int | `50` | Maximum ingested file size in MB |

Supported file types: `.txt`, `.md`, `.html`, `.csv`, `.json`, `.pdf` (requires `pypdf`).

Tools: `kb_ingest`, `kb_ingest_text`, `kb_search`, `kb_list`, `kb_delete`.

### `[workflow]`

DAG-based workflow engine for multi-step task pipelines:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `true` | Enable the workflow engine |
| `db_path` | string | `~/.neuralclaw/data/workflows.db` | SQLite database for workflow state |
| `max_concurrent_workflows` | int | `5` | Max workflows running in parallel |
| `max_steps_per_workflow` | int | `50` | Max steps allowed per workflow |
| `step_timeout_seconds` | int | `120` | Default timeout per step |

Tools: `create_workflow`, `run_workflow`, `pause_workflow`, `resume_workflow`,
`workflow_status`, `list_workflows`, `delete_workflow`.

### `[mcp_server]`

MCP (Model Context Protocol) server exposing NeuralClaw to external agents/IDEs:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `false` | Enable MCP server (opt-in) |
| `port` | int | `3001` | HTTP port for MCP endpoint |
| `bind_host` | string | `"127.0.0.1"` | Bind address (localhost-only by default) |
| `auth_token` | string | `""` | Bearer token for authentication (empty = no auth) |
| `expose_tools` | bool | `true` | Expose registered tools via `tools/list` and `tools/call` |
| `expose_resources` | bool | `true` | Expose KB documents via `resources/list` and `resources/read` |
| `expose_prompts` | bool | `true` | Expose agent persona via `prompts/list` and `prompts/get` |

Endpoints: `POST /mcp` (JSON-RPC 2.0), `GET /mcp/sse` (Server-Sent Events), `GET /mcp/health`.

## Example

```toml
[general]
name = "NeuralClaw"
persona = "You are NeuralClaw, a helpful and intelligent AI assistant."

[features]
vector_memory = true
identity = true
vision = true
voice = false
browser = false
structured_output = true
streaming_responses = true
traceline = true
desktop = false
swarm = true
dashboard = true
evolution = true
reflective_reasoning = true
procedural_memory = true
semantic_memory = true
a2a_federation = false
skill_forge = true
rag = true
workflow_engine = true
mcp_server = false

[providers]
primary = "openai"
fallback = ["openrouter", "local"]

[providers.openai]
model = "gpt-4o"
base_url = "https://api.openai.com/v1"

[memory]
vector_memory = true
embedding_provider = "local"
embedding_model = "nomic-embed-text"
embedding_dimension = 768
vector_similarity_top_k = 10

[identity]
enabled = true
cross_channel = true
inject_in_prompt = true

[security]
output_filtering = true
output_pii_detection = true
output_prompt_leak_check = true
canary_tokens = true

[policy]
parallel_tool_execution = true

[channels.discord]
enabled = false
trust_mode = "bound"
voice_responses = false
auto_disconnect_empty_vc = true
voice_channel_id = ""
```

## Auth and Setup Commands

```bash
neuralclaw init
neuralclaw proxy setup
neuralclaw local setup

neuralclaw session setup chatgpt
neuralclaw session setup claude

neuralclaw session auth chatgpt
neuralclaw session auth claude
neuralclaw session auth google
neuralclaw session auth microsoft
```

## Validation

```bash
neuralclaw status
neuralclaw session status
neuralclaw doctor
```

When browser, desktop, TTS, Google Workspace, or Microsoft 365 sections are
enabled, `load_config()` automatically extends `policy.allowed_tools` with the
matching tool names and appends the relevant mutating tools where needed.
