# Agent Implementation Notes

This file is a compact handoff log for ongoing `AGENT.md` implementation work.
Update it when a roadmap slice lands so later sessions do not need to rediscover
the current state from scratch.

## Implemented slices

### Vector memory

- Added `neuralclaw/cortex/memory/vector.py`.
- `EpisodicMemory.store()` now indexes vector rows when vector memory is enabled.
- `MemoryRetriever.retrieve()` now merges vector similarity results with existing memory retrieval.
- `MemoryMetabolism._prune()` deletes vector rows for pruned episodes.
- Config wiring:
  - `features.vector_memory`
  - `memory.vector_memory`
  - `memory.embedding_provider`
  - `memory.embedding_model`
  - `memory.embedding_dimension`
  - `memory.vector_similarity_top_k`
- Gateway wiring:
  - lazy init and close of `self._vector_memory`
  - retriever and metabolism receive the vector store
- Tests:
  - `tests/test_vector_memory.py`
  - config validation coverage extended

### Identity memory

- Added `neuralclaw/cortex/memory/identity.py`.
- `UserIdentityStore` persists canonical users plus platform aliases.
- Gateway wiring:
  - lazy init and close of `self._identity`
  - per-message `get_or_create()` lookup
  - identity prompt section injection into deliberate/reflective reasoning
  - episodic interaction tags now include `user_id:<canonical_id>`
  - post-process syncs calibrator preferences back into identity state
- Config wiring:
  - `features.identity`
  - `[identity]` section via `IdentityConfig`
- Tests:
  - `tests/test_identity.py`
  - prompt injection coverage in `tests/test_session_and_gateway.py`

### Structured output enforcement

- Added `neuralclaw/cortex/reasoning/structured.py`.
- New components:
  - `StructuredReasoner`
  - `StructuredOutputError`
  - built-in schemas: `GeneratedSkill`, `ExtractedFact`, `TaskDecomposition`
- Config wiring:
  - `features.structured_output`
- Gateway wiring:
  - lazy init of `self._structured`
  - `ReflectiveReasoner` now receives a structured reasoner when enabled
- Reflective integration:
  - `_decompose()` now prefers `StructuredReasoner.extract(..., TaskDecomposition)`
  - falls back to legacy JSON-array parsing if structured extraction fails
- Project dependency:
  - added `pydantic>=2.0` in `pyproject.toml`
- Tests:
  - `tests/test_structured.py`

### Streaming responses

- Added backward-compatible `send_stream()` to `ChannelAdapter`.
- Added buffered fallback `stream_complete()` to `LLMProvider` and `ProviderRouter`.
- Added `DeliberativeReasoner.reason_stream()` plus `wrap_streamed_response()`.
- Gateway wiring:
  - `_on_channel_message()` now attempts `_try_stream_channel_message()` first
  - streaming is enabled behind `features.streaming_responses`
  - reflective requests fall back to the existing buffered path
- Adapter overrides implemented:
  - `DiscordAdapter.send_stream()` edits a placeholder message
  - `TelegramAdapter.send_stream()` edits a placeholder message
  - `WebChatAdapter.send_stream()` pushes incremental websocket deltas
- Config wiring:
  - `features.streaming_responses`
  - `features.streaming_edit_interval`
- Tests:
  - `tests/test_streaming.py`

### Traceline observability

- Added `neuralclaw/cortex/observability/traceline.py`.
- Added `ToolCallTrace`, `ReasoningTrace`, and `Traceline`.
- Config wiring:
  - `features.traceline`
  - `[traceline]` via `TracelineConfig`
- Gateway wiring:
  - lazy init and close of `self._traceline`
  - richer event payloads now include request/user/channel metadata on
    `SIGNAL_RECEIVED`, `CONTEXT_ENRICHED`, `ACTION_*`, and `RESPONSE_READY`
- Traceline subscribes to the neural bus and persists traces in SQLite.
- Implemented query/export/metrics/prune APIs.
- Tests:
  - `tests/test_traceline.py`

### Prompt Armor v2

- Added `neuralclaw/cortex/perception/output_filter.py`.
- New components:
  - `OutputThreatFilter`
  - `OutputFilterResult`
- Output detections implemented:
  - prompt/canary leakage
  - PII leakage not present in the inbound user message
  - hallucinated tool-call JSON payloads
  - jailbreak-confirming responses
  - excessive refusal flagging on otherwise safe requests
- `ThreatScreener` additions:
  - `multi_turn_escalation` pattern
  - `obfuscated_instruction` pattern
  - dynamic canary echo detection via `set_canary_token()`
- Config wiring in `[security]`:
  - `output_filtering`
  - `output_pii_detection`
  - `output_prompt_leak_check`
  - `canary_tokens`
  - `pii_patterns`
- Gateway wiring:
  - `self._output_filter`
  - startup canary generation `CANARY_<12 hex>` when output filtering is enabled
  - invisible canary injection into system prompt sections
  - per-response filtering before storage/history/delivery
  - streaming now falls back to buffered delivery when output filtering is enabled
- Tests:
  - `tests/test_output_filter.py`
  - `tests/test_perception.py`
  - `tests/test_streaming.py`
  - `tests/test_session_and_gateway.py`

### Audit forensic replay

- Extended `neuralclaw/cortex/action/audit.py`.
- New components:
  - `AuditRecord`
  - `AuditSearchIndex`
  - enhanced `AuditLogger` with indexed replay/search/export/stats
- Config wiring:
  - `[audit]` via `AuditConfig`
  - `enabled`
  - `jsonl_path`
  - `max_memory_entries`
  - `retention_days`
  - `siem_export`
  - `include_args`
- Runtime wiring:
  - gateway now initializes `self._audit` from config
  - `DeliberativeReasoner` receives the audit logger
  - tool executions and policy denials now write request/user/channel-scoped audit records
  - request context now carries `user_id`, `channel_id`, and `platform`
- CLI surface added in `neuralclaw/cli.py`:
  - `neuralclaw audit list`
  - `neuralclaw audit show <request_id>`
  - `neuralclaw audit export --format jsonl|csv|cef`
  - `neuralclaw audit stats`
- Replay/export support:
  - `search(tool=..., user_id=..., since=..., denied_only=...)`
  - `get_trace_actions(request_id)`
  - `export(..., format="jsonl"|"csv"|"cef")`
  - `stats()`
- Tests:
  - `tests/test_audit_replay.py`
  - config validation coverage extended

### Desktop control

- Added `neuralclaw/cortex/action/desktop.py`.
- New component:
  - `DesktopCortex`
- Implemented methods:
  - `screenshot()`
  - `click()`
  - `type_text()`
  - `hotkey()`
  - `get_clipboard()`
  - `set_clipboard()`
  - `run_app()`
- Config wiring:
  - `features.desktop`
  - `[desktop]` via `DesktopConfig`
  - `policy.desktop_allowed_apps`
  - `policy.desktop_blocked_regions`
- Capability wiring:
  - added `Capability.DESKTOP_CONTROL`
  - added default grant entry for `"desktop"` in `CapabilityVerifier`
- Gateway wiring:
  - lazy desktop cortex init behind `features.desktop` and `desktop.enabled`
  - desktop tools are only registered when desktop is actually enabled
  - exposed tools:
    - `desktop_screenshot`
    - `desktop_click`
    - `desktop_type`
    - `desktop_hotkey`
    - `desktop_get_clipboard`
    - `desktop_set_clipboard`
    - `desktop_run_app`
- Packaging:
  - added `desktop` optional dependency extra in `pyproject.toml`
- Tests:
  - `tests/test_desktop.py`
  - config validation coverage extended

### Vision perception

- Added `neuralclaw/cortex/perception/vision.py`.
- New component:
  - `VisionPerception`
- Implemented methods:
  - `describe()`
  - `extract_text()`
  - `answer_about()`
  - `locate_element()`
  - `process_media()`
- Config wiring:
  - `features.vision`
- Gateway wiring:
  - lazy init of `self._vision` after provider setup
  - `_on_channel_message()` now forwards `ChannelMessage.media`
  - `process_message()` and `_build_streaming_response()` now pass media into intake
  - visual summaries are prepended to the signal as a `## Visual Context` section
- Tests:
  - `tests/test_vision.py`
  - gateway coverage extended in `tests/test_session_and_gateway.py`
  - config loading coverage extended in `tests/test_config_validation.py`

### Parallel tool execution

- `DeliberativeReasoner.reason()` now executes multiple tool calls concurrently
  with `asyncio.gather(..., return_exceptions=True)` by default.
- Added a policy switch:
  - `policy.parallel_tool_execution`
- Behavior details:
  - tool result ordering remains stable when messages are appended back into the
    model conversation
  - a single tool failure no longer blocks sibling tool calls in the same batch
  - sequential execution is still available by disabling the policy flag
- Tests:
  - `tests/test_parallel_tools.py`
  - config loading coverage extended in `tests/test_config_validation.py`

### Structured output integrations

- Existing `StructuredReasoner` is now wired into the evolution cortex paths that
  AGENT explicitly called out.
- `SkillSynthesizer` changes:
  - accepts an optional shared `StructuredReasoner`
  - `synthesize_skill()` now prefers `GeneratedSkill` schema generation before
    falling back to the legacy raw-code path
  - structured `required_imports` are materialized into the runnable code blob
- `ExperienceDistiller` changes:
  - accepts an optional shared `StructuredReasoner`
  - `distill()` now extracts `ExtractedFact` relationships from recent episodes
    and persists them into semantic memory
  - heuristic pattern extraction remains as a fallback/adjacent source
- Gateway wiring:
  - the shared structured reasoner is passed into both distiller and synthesizer
  - those components are re-bound after provider setup
- Tests:
  - `tests/test_structured.py`
  - regression coverage in `tests/test_evolution_security_swarm.py`

### Browser cortex

- Added `neuralclaw/cortex/action/browser.py`.
- New components:
  - `BrowserState`
  - `BrowserAction`
  - `BrowserResult`
  - `BrowserCortex`
- Implemented methods:
  - `start()`
  - `stop()`
  - `navigate()`
  - `screenshot()`
  - `click()`
  - `type_text()`
  - `scroll()`
  - `extract()`
  - `execute_js()`
  - `wait_for()`
  - `chrome_summarize()`
  - `chrome_translate()`
  - `chrome_prompt()`
  - `act()`
- `browser_act()` is now a real iterative planner:
  - captures browser state each step
  - asks the configured provider for the next JSON action
  - executes `navigate` / `click` / `type` / `scroll` / `wait` / `extract`
  - re-observes and repeats until `done` or max-step exhaustion
  - uses `VisionPerception.describe()` for visual planning context when available
  - preserves a fallback one-shot extract path when no provider is configured
- Config wiring:
  - `features.browser`
  - `[browser]` via `BrowserConfig`
- Capability wiring:
  - added `Capability.BROWSER_CONTROL`
  - added default grant entry for `"browser"` in `CapabilityVerifier`
- Gateway wiring:
  - lazy browser init during provider setup
  - dynamic browser tool registration:
    - `browser_navigate`
    - `browser_screenshot`
    - `browser_click`
    - `browser_type`
    - `browser_scroll`
    - `browser_extract`
    - `browser_execute_js`
    - `browser_wait_for`
    - `browser_act`
    - `chrome_summarize`
    - `chrome_translate`
    - `chrome_prompt`
  - browser shutdown integrated into gateway stop path
  - browser reuses `VisionPerception` for natural-language click targets
- Packaging:
  - added `browser` optional dependency extra in `pyproject.toml`
- Tests:
  - `tests/test_browser.py`
  - config validation coverage extended in `tests/test_config_validation.py`

### TTS skill and Discord voice

- Added `neuralclaw/skills/builtins/tts.py`.
- New tool handlers:
  - `speak`
  - `list_voices`
  - `speak_and_play`
- Runtime behavior:
  - text is truncated to `tts.max_tts_chars`
  - audio is written to a temp path in the configured format
  - adapter playback is routed through a simple per-platform registry
- Config wiring:
  - `features.voice`
  - `[tts]` via `VoiceConfig`
  - `[channels.discord].voice_responses`
  - `[channels.discord].auto_disconnect_empty_vc`
  - `[channels.discord].voice_channel_id`
- Gateway wiring:
  - builtin TTS config is injected during `initialize()`
  - channel adapters are registered with the TTS module on `add_channel()`
  - text responses can trigger Discord voice playback through `_maybe_send_voice_response()`
- Discord adapter wiring:
  - added `join_voice()`
  - added `leave_voice()`
  - added `speak()`
  - added `is_in_voice()`
  - added `current_voice_channel`
  - auto-disconnect from empty voice channels is now configurable
- Packaging:
  - added `voice` optional dependency extra in `pyproject.toml`
- Tests:
  - `tests/test_tts.py`

### Google Workspace skill

- Added `neuralclaw/skills/builtins/google_workspace.py`.
- New tool handlers:
  - `gmail_search`
  - `gmail_send`
  - `gmail_get`
  - `gmail_label`
  - `gmail_draft`
  - `gcal_list_events`
  - `gcal_create_event`
  - `gcal_update_event`
  - `gcal_delete_event`
  - `gdrive_search`
  - `gdrive_read`
  - `gdrive_upload`
  - `gdocs_read`
  - `gdocs_append`
  - `gsheets_read`
  - `gsheets_write`
  - `gmeet_create`
- Runtime behavior:
  - reads Google OAuth secrets from keychain-backed config helpers
  - outbound requests are passed through `validate_url_with_dns()`
  - module-global service config now refreshes correctly when gateway config changes
- Config wiring:
  - `[google_workspace]` via `GoogleWorkspaceConfig`
  - auto-allowlisting and mutating-tool extension in `load_config()`
- CLI/auth wiring:
  - `neuralclaw session auth google` stores pasted access/refresh tokens and enables the skill
- Packaging:
  - added `google` optional dependency extra in `pyproject.toml`
- Tests:
  - `tests/test_google_workspace.py`
  - config validation coverage extended in `tests/test_config_validation.py`

### Microsoft 365 skill

- Added `neuralclaw/skills/builtins/microsoft365.py`.
- New tool handlers:
  - `outlook_search`
  - `outlook_send`
  - `outlook_get`
  - `ms_cal_list`
  - `ms_cal_create`
  - `ms_cal_delete`
  - `teams_send`
  - `teams_list_channels`
  - `onedrive_search`
  - `onedrive_read`
  - `onedrive_upload`
  - `sharepoint_search`
  - `sharepoint_read`
- Runtime behavior:
  - reads Microsoft OAuth secrets from keychain-backed config helpers
  - outbound Graph requests are passed through `validate_url_with_dns()`
  - module-global service config now refreshes correctly when gateway config changes
- Config wiring:
  - `[microsoft365]` via `Microsoft365Config`
  - auto-allowlisting and mutating-tool extension in `load_config()`
- CLI/auth wiring:
  - `neuralclaw session auth microsoft` stores pasted access/refresh tokens and enables the skill
- Packaging:
  - added `microsoft` optional dependency extra in `pyproject.toml`
- Tests:
  - `tests/test_microsoft365.py`
  - config validation coverage extended in `tests/test_config_validation.py`

### A2A federation protocol

- Extended `neuralclaw/swarm/federation.py` with A2A-compatible message handling.
- Added A2A data models:
  - `A2APart`
  - `A2AChatMessage`
  - `A2AEnvelope`
- Added A2A endpoints:
  - `GET /.well-known/agent.json`
  - `POST /a2a`
  - `GET /a2a/tasks/{task_id}`
- Implemented JSON-RPC methods:
  - `message/send`
  - `message/stream`
  - `tasks/get`
  - `tasks/cancel`
  - `agent/authenticatedExtendedCard`
- Gateway wiring:
  - federation now receives `description=self._config.persona`
  - federation now receives an A2A skill-card provider derived from `SkillRegistry`
  - federation A2A enablement requires both `features.a2a_federation` and `federation.a2a_enabled`
  - bearer token auth uses keychain secret `a2a_token`
- Config wiring:
  - `features.a2a_federation`
  - `[federation].a2a_enabled`
  - `[federation].a2a_auth_required`
- Tests:
  - `tests/test_a2a.py`
  - regression coverage in `tests/test_federation_spawn.py`

## Prompt-context plumbing added

- `DeliberativeReasoner.reason()` accepts `extra_system_sections`.
- `ReflectiveReasoner.reflect()` passes `extra_system_sections` through decompose,
  critique, revision, and synthesis steps.
- This was required for identity prompt injection and should be reused by future
  slices such as traceline or output filtering.

## Verification commands last run successfully

```powershell
python -m pytest -q tests/test_tts.py tests/test_google_workspace.py tests/test_microsoft365.py tests/test_a2a.py tests/test_config_validation.py tests/test_federation_spawn.py tests/test_session_and_gateway.py
python -m compileall neuralclaw
```

## Roadmap status

The `AGENT.md` roadmap is now implemented end to end across the currently defined slices.
Future work should be incremental hardening or deeper provider-specific polish, not
missing-roadmap catch-up.

## Known cautions

- `AGENT.md` is a large roadmap, not a single task. Continue by coherent slices.
- Existing code still contains older broad `except Exception: pass` patterns in
  preexisting modules. New code should avoid introducing more of them.
- `git status` from the repo root may show unrelated parent-directory noise in
  this environment; do not rely on that for a clean repo-only diff signal.
- Output filtering currently disables live token streaming by design so the
  final text can be screened before delivery. If streaming must coexist with
  Prompt Armor later, it will need buffered chunk approval or incremental
  screening semantics.
- Audit replay currently logs tool executions directly from the deliberative
  reasoner path. If future tool execution paths are added outside that reasoner,
  they must either reuse `AuditLogger.log_action()` or emit equivalent audit
  records explicitly.
- Desktop tools are registered dynamically in the gateway, not as a static
  builtin manifest, so they stay completely hidden when desktop control is
  disabled. Preserve that property if the tool registration path changes later.
