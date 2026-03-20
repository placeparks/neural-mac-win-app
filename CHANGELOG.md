# Changelog

All notable changes to NeuralClaw will be documented in this file.

## [1.2.0] - 2026-03-20

### Added — SkillScout (Discovery Layer)
- **`neuralclaw/skills/scout.py`**: New `SkillScout` engine that searches PyPI,
  GitHub, npm, MCP registries, and Claw Club marketplace in parallel
- **Automatic ranking**: LLM-powered ranking with heuristic fallback (stars,
  license, registry priority)
- **Full pipeline**: `scout("need X")` → search → rank → `forge.steal()` → live
  skill in under 2 minutes
- **`neuralclaw/skills/scout_handlers.py`**: Channel command handlers —
  `!scout`, `/scout`, `scout:` across Discord, Telegram, Slack, WhatsApp
- **`scout_skill` agent tool**: Agent can self-scout mid-conversation
- **CLI commands**: `neuralclaw scout find <query>` and
  `neuralclaw scout search <query>` (search-only, no forge)
- **Gateway wiring**: Scout command interception in `_on_channel_message()`,
  tool registration with policy allowlisting
- **14 tests** covering command detection, heuristic ranking, Claw Club
  priority, URL encoding, and end-to-end mock flow

## [1.1.6] - 2026-03-20

### Fixed — Memory System
- **Consolidation was dead code**: `MemoryMetabolism._consolidate()` passed
  `properties=` and `confidence=` to `SemanticMemory.upsert_entity()` which
  expects `attributes=`. Silently failed on every call. Now fixed.
- **`EpisodicMemory.get_recent(since=0.0)` skipped filter**: `if since:` was
  falsy for `0.0`, ignoring the WHERE clause. Fixed to `if since is not None:`.

### Fixed — SkillForge
- **Handler name mismatch in auto-appended `get_manifest()`**: Now extracts
  actual `async def` names from generated code and maps them to spec tool names
  using exact → fuzzy → order-based fallback.
- **Final safety for `get_manifest()`**: Added check right before `_persist_skill()`
  so neither `_attempt_fix()` nor any other code path can strip it.

## [1.1.5] - 2026-03-20

### Fixed — SkillForge End-to-End
- **Gateway crash on startup**: `AttributeError: 'NeuralClawGateway' object has no
  attribute '_sandbox'` — SkillForge now creates its own `Sandbox` instance using
  `forge.sandbox_timeout` from config.
- **CLI `forge create` crash**: `Sandbox(config=config)` used wrong constructor
  signature; fixed to `Sandbox(timeout_seconds=...)`.
- **Hot loader duplicate tools**: `SkillHotLoader._load_skill_file()` called
  `register()` instead of `hot_register()`, causing duplicate tool entries on
  skill reload.
- **Null safety for `importlib` spec loading**: Added `None` checks for
  `spec_from_file_location()` return value in `forge.py`, `hot_loader.py`, and
  `registry.py` — prevents `AttributeError` on malformed skill files.
- **Missing session in clarification retry**: `forge_handlers.py`
  `_handle_clarification_reply()` now passes `session` to `forge.steal()` so
  multi-turn context is preserved.
- **Forged tools denied by policy**: `forge_skill` and all dynamically forged
  tools are now auto-added to `policy.allowed_tools` — applies to
  `_forge_skill_tool`, `SkillHotLoader`, and `load_user_skills`.
- **Forged skills had no handlers**: `_build_manifest_from_spec()` now keeps
  loaded modules alive (prevents GC), loads from persisted skill files, and
  creates lazy on-demand handlers as a last resort.
- **LLM omits `get_manifest()`**: Auto-appends `get_manifest()` from the spec
  if the generated code is missing it. Final safety check runs right before
  `_persist_skill()` so neither `_attempt_fix()` nor any other path can strip it.
  Strengthened the generation prompt with NON-NEGOTIABLE instruction.
- **Handler name mismatch**: `_append_manifest_function()` now extracts actual
  `async def` names from the generated code and maps them to spec tool names
  using exact match → fuzzy match → order-based fallback. Previously it assumed
  the LLM would name functions identically to the spec tool names.
- **`steal()` used `register()` instead of `hot_register()`**: Re-forging the
  same skill now properly replaces old tool entries instead of duplicating them.
- **4 test failures**: Fixed `AuditRecord.reason` → `.denied_reason`,
  `config.providers.primary` → `config.primary_provider.name`, canary token
  assertion, and `Capability.CODE_EXECUTION` → `.SHELL_EXECUTE`.

## [1.1.0] - 2026-03-20

### Added — SkillForge: Proactive Skill Synthesis
- **`neuralclaw/skills/forge.py`**: Complete SkillForge engine with 10 input
  source types — URL, OpenAPI, GraphQL, Python library, natural language
  description, code, file, GitHub repo, MCP server, and auto-detection.
- **Use-case interview**: Before generating code, SkillForge asks the LLM
  to design domain-specific tools tailored to the user's exact use case.
  Stripe + "charge chiro patients" → `charge_patient`, `issue_refund`,
  `list_invoices` — NOT 200 generic wrappers.
- **`neuralclaw/skills/forge_handlers.py`**: Multi-platform channel handlers.
  Trigger from Discord (`!forge`), Telegram (`/forge`), Slack (`forge`),
  WhatsApp (`forge:`), or CLI. Multi-turn clarification sessions.
- **`neuralclaw/skills/hot_loader.py`**: Watch `~/.neuralclaw/skills/` for
  new files and hot-load them into the registry without restart.
- **Registry `hot_register()`**: Replace a skill at runtime, removing old
  tool definitions before registering new ones.
- **`load_user_skills()`**: Load all user-generated skills on startup.
- **`forge_skill` agent tool**: The agent can proactively forge its own
  skills mid-conversation when asked to "learn" something new.
- **CLI `neuralclaw forge` group**: `create`, `list`, `remove`, `show`
  commands for managing forged skills.
- **`ForgeConfig` dataclass**: `[forge]` config section with model, sandbox
  timeout, max tools per skill, network/filesystem allowlists.
- **`skill_forge` feature flag**: Master switch in `[features]`.
- **`tests/test_skillforge.py`**: Input detection, command parsing,
  clarification detection, slugify, and hot loader tests.

### Fixed
- **Threat screener gaps**: Added 9 new injection patterns covering Cyrillic
  homoglyphs, base64 smuggling, token/MASK smuggling, roleplay jailbreak,
  fake authority overrides, context extraction, and fake system prompt boundaries.
- **SSRF octal/hex bypass**: `_normalize_ip()` now converts octal (`0177.0.0.1`)
  and hex (`0x7f000001`) IP encodings to standard notation before validation.
- **Jailbreak confirmation detection**: Added 8 dangerous output hints (pipe bomb,
  as DAN, disabled restrictions, no guidelines) and 12 confirmation prefixes.
- **Test fixes**: Corrected `_canary` → `_canary_token`, `tool=` → `skill_name=`
  in AuditRecord, `str(path)` → `Path` for load_config, `Capability` enum import,
  `DBPool` import path.

## [1.0.0] - 2026-03-19

### Production Stable Release

NeuralClaw reaches 1.0 — every feature in both `AGENT.md` and `AGENT_PROD.md`
is fully implemented, tested, and production-hardened.

### Added — Production Test Suite
- **Adversarial test expansion**: 14 injection payloads (up from 5) covering
  Cyrillic homoglyphs, base64 encoding, markdown code blocks, fake system
  overrides, multi-turn escalation, and semantic disguise.
- **PII output detection tests**: Parametrized test cases for SSN, email, and
  phone number leakage in LLM output.
- **SSRF URL validation tests**: 8 parametrized cases covering cloud metadata,
  localhost, IPv6 loopback, octal/hex IP encodings.
- **Jailbreak confirmation tests**: 4 parametrized cases detecting LLM
  responses that confirm a jailbreak.
- **Rate limiter flood test**: Validates SlidingWindowUserLimiter blocks the
  6th request when limit is 5/minute.
- **Circuit breaker open/recover tests**: Verifies CLOSED → OPEN transition
  after 3 failures, HALF_OPEN recovery after timeout, and full CLOSED recovery.
- **Chaos engineering harness**: `provider_outage()`, `slow_provider()`, and
  `burst_messages()` async context managers plus `TestChaosProviderDown` and
  `TestChaosBurstLoad` test classes.
- **Load test expansion**: `test_concurrent_requests_db_no_deadlock` (10
  concurrent requests), `test_memory_retrieval_under_large_db` (10k episodes,
  <200ms), `test_traceline_write_throughput` (100 traces/sec).
- **Integration matrix**: `test_evolution_synthesizer_produces_valid_skill`
  added.

### Changed — Production Hardening
- **Dockerfile**: Multi-stage build (builder + runtime), non-root user
  (`neuralclaw:1000`), `HEALTHCHECK` directive, Playwright browser install,
  `VOLUME` for persistent state.
- **Development status**: Upgraded from `Beta` to `Production/Stable` in
  PyPI classifiers.
- **pytest markers**: Added `slow` and `chaos` markers to `pyproject.toml`.
- **Dependencies**: Added `watchfiles>=0.22` to core dependencies.

## [0.8.0] - 2026-03-18

### Added — Computer Use & Desktop Control
- **End-to-end desktop screenshot delivery**: Screenshots captured via
  `desktop_screenshot` are now sent as actual Telegram photos (not just
  described in text). Added `send_photo()` to the Telegram adapter.
- **Vision-powered screen analysis**: Screenshot tool results are sent to
  the LLM as multimodal vision content (`image_url` with base64), enabling
  the model to describe what's on screen, identify UI elements, and guide
  click coordinates for computer use workflows.
- **Desktop app launcher (Windows)**: `desktop_run_app` now works on Windows
  with `shell=True` for PATH resolution. Case-insensitive allowlist matching
  (e.g., "notepad", "Notepad", and "notepad.exe" all match).
- **Default app allowlist**: Pre-configured `desktop_allowed_apps` with 25+
  common Windows applications (Notepad, Calculator, VS Code, Chrome, Edge,
  PowerShell, Terminal, Python, Git, etc.).
- **Media pipeline in reasoning**: `ConfidenceEnvelope` now carries a `media`
  field so tool-generated images flow from the reasoning cortex through the
  gateway to the channel adapter.

### Added — Dynamic Self-Awareness
- **Capability-aware system prompt**: The gateway now injects a dynamic
  `## Your Active Capabilities` section into the LLM system prompt, built
  from actually-enabled features (memory, identity, vision, evolution, shell,
  browser, desktop, workspace integrations, TTS, etc.).
- **Tool awareness injection**: Every request includes an `## Active Tools`
  section listing all registered tool names, plus a `## Desktop Control`
  section when desktop tools are active — explicitly instructing the LLM to
  use desktop tools for screen/computer requests even from remote users.
- **Anti-refusal guidelines**: System prompt now includes "NEVER say 'I can't'
  when you have a tool that can do it" and instructs the LLM to ignore past
  memory showing it previously refused (memory poisoning defense).

### Added — Provider Model Updates (March 2026)
- **OpenAI GPT-5 API compatibility**: `max_completion_tokens` replaces
  `max_tokens` and `temperature` parameter removed for GPT-5/GPT-4.1/o-series
  models. New `_is_new_api_model()` check covers `gpt-5*`, `gpt-4.1*`, `o1*`,
  `o3*`, `o4*` prefixes.
- **Updated default models**: OpenAI → `gpt-5.4` / `gpt-5.4-mini`, Anthropic →
  `claude-sonnet-4-6`, OpenRouter → `anthropic/claude-sonnet-4-6`, Local →
  `qwen3:8b`.
- **Configurator model lists refreshed**: All provider model dropdowns now
  include March 2026 releases (GPT-5.4 family, Claude Opus/Sonnet 4.6,
  o4-mini, Gemini 2.5 Pro/Flash, Llama 4 Scout/Maverick, DeepSeek R1/V3,
  Qwen3 235B).

### Added — Memory & Reasoning Hardening
- **Smart importance scoring**: New `_score_importance()` heuristic ranks
  personal facts (0.85), instructions (0.75), past references (0.70),
  code (0.60), and casual greetings (0.30) for episodic memory storage.
- **FTS5 query sanitization**: Special characters are stripped, tokens are
  quoted, and empty/short queries return early instead of crashing SQLite.
- **Entity extraction improvements**: Regex-based extraction of proper nouns,
  quoted strings, multi-word capitalized phrases, with stop-word filtering.
- **Distiller fix**: Evolution distiller no longer accesses private `_db` on
  episodic memory — uses public `get_recent()` API instead.

### Added — Infrastructure
- **Vector memory**: `cortex/memory/vector.py` with similarity retrieval
  integrated into episodic storage, retrieval merging, and metabolism pruning.
- **Persistent identity memory**: `cortex/memory/identity.py` with canonical
  user IDs, cross-channel aliases, and prompt injection of user context.
- **Vision perception**: Multimodal media processing and visual-context
  injection with `cortex/perception/vision.py`.
- **Browser cortex**: `cortex/action/browser.py` with low-level browser tools
  plus a multi-step planner for `browser_act`.
- **Streaming responses**: Adapter-level `send_stream()` support and gateway
  orchestration for streamed responses.
- **Structured output enforcement**: `cortex/reasoning/structured.py` wired
  into reflective reasoning and evolution paths.
- **Traceline observability**: `cortex/observability/traceline.py` with
  SQLite-backed reasoning and tool trace persistence.
- **Prompt Armor v2**: Output-side response screening for canary leaks,
  prompt disclosure, PII leakage, hallucinated tool payloads, and jailbreak
  confirmation patterns.
- **Audit replay**: Extended `cortex/action/audit.py` with indexed replay,
  request-scoped exports, and audit CLI commands.
- **TTS and Discord voice**: Builtin TTS skill, gateway voice-response
  orchestration, and Discord voice playback support.
- **Google Workspace skill**: Gmail, Calendar, Drive, Docs, Sheets, and Meet
  integrations with config-gated allowlisting.
- **Microsoft 365 skill**: Outlook, Calendar, Teams, OneDrive, and SharePoint
  integrations with config-gated allowlisting.
- **A2A federation**: Agent cards, `/a2a` JSON-RPC, task lookup/cancel APIs,
  and skill metadata exposure.

### Changed
- **Configuration surface**: Expanded `config.py` with feature flags and config
  sections for identity, traceline, audit, TTS, browser, desktop, Google
  Workspace, Microsoft 365, and A2A federation.
- **Capability model**: Extended built-in capability grants for browser,
  desktop, TTS, Google Workspace, and Microsoft 365 integrations.
- **Policy behavior**: `parallel_tool_execution` support, automatic
  allowlisting, and `desktop_allowed_apps` configuration.
- **Gateway orchestration**: Dynamic self-awareness prompt, tool awareness
  injection, media pipeline, and capability fragment propagation to the
  deliberative reasoner.

### Fixed
- **Desktop tools not invoked**: LLM refused to use desktop tools because
  capability descriptions were generic ("local desktop") and never reached
  the system prompt. Fixed with explicit "THIS machine" language, capability
  fragment injection into `extra_system_sections`, and anti-memory-poisoning
  guidelines.
- **Screenshot not delivered**: Tool returned base64 PNG but it was serialized
  as JSON text in the tool result — user only got "Here's the screenshot"
  without the image. Fixed with media pipeline through ConfidenceEnvelope.
- **OpenAI GPT-5 400 errors**: `max_tokens` and `temperature` parameters
  rejected by GPT-5/GPT-4.1/o-series. Fixed with `_is_new_api_model()` gate.
- **Tool-use loop cop-out**: After 10 failed iterations the bot said "could
  you rephrase?" — now makes a final tool-free call summarizing what was
  tried, with consecutive error tracking (bail after 3 rounds).
- **Memory poisoning**: Past "I can't capture your screen" responses were
  retrieved and reinforced refusal behavior. Deleted poisoned entries and
  added anti-poisoning system prompt directive.
- **FTS5 crash on special characters**: Unquoted punctuation in search
  queries caused SQLite FTS5 syntax errors.
- **Distiller private DB access**: `_db` attribute access on episodic memory
  replaced with public API.
- **Google/Microsoft config refresh**: Workspace modules now refresh
  module-global service instances when gateway config changes.
- **Workspace SSRF gap**: Google and Microsoft outbound requests now pass
  through URL validation.
- **Federation A2A integration**: Gateway federation initialization now
  forwards persona, skill metadata, and bearer token settings.
- **Discord voice behavior**: Auto-disconnect driven by channel config
  instead of hard-wired.

### Testing
- Added targeted tests for TTS, Google Workspace, Microsoft 365, and A2A.
- Extended config validation coverage for new feature flags and sections.
- Verified desktop screenshot → Telegram photo pipeline end-to-end.
- Verified desktop app launch on Windows with allowlist.
- Verified GPT-5 API parameter compatibility.

## [0.7.7] - 2026-03-12

### Added
- **Stealth OAuth**: `neuralclaw session auth chatgpt --stealth` allows users in headless environments to manually copy-paste the URL and redirect link instead of failing on local browser execution.
- **Claude Stealth Auth**: `neuralclaw session auth claude --stealth` allows users to quickly paste their extracted Anthropico cookie without requiring a full Playwright profile.
- **Async Event Loop Fix**: Fully refactored the OAuth token callback process into native `async/await` coroutines, removing buggy `sync-to-async` event loop deadlocks.

### Fixed
- **OpenAI Auth Error**: Fixed 404 page for ChatGPT session extraction by upgrading our internal Auth client to the newest upstream client ID (`app_EMoamEEZ73f0CkXaXp7hrann`) and correctly implementing PKCE and `auth.openai.com/oauth/authorize` endpoints.

## [0.7.5] - 2026-03-11

### Changed
- **ChatGPT token bootstrap**: `neuralclaw session auth chatgpt` now uses a
  managed-browser login flow that captures the ChatGPT session cookie directly
  from the managed profile instead of relying on the dead Auth0 login endpoint.
- **Cloudflare UX**: ChatGPT auth now surfaces state changes while it waits,
  including explicit terminal guidance when Cloudflare verification is active,
  when normal login is still pending, and when the session is ready for cookie
  capture.
- **Token recovery**: `chatgpt_token` and `claude_token` providers now try to
  recover credentials from their managed browser profiles when stored tokens are
  stale or missing, and `session refresh` can reacquire credentials from those
  profiles.

### Fixed
- **Gateway token-provider bootstrapping**: token-backed providers are no longer
  rejected just because the stored credential has expired when a recoverable
  managed profile exists.
- **Legacy ChatGPT cookie support**: ChatGPT token auth now accepts both
  `__Secure-next-auth.session-token` and `next-auth.session-token` cookies
  across `chatgpt.com` and `chat.openai.com` profile domains.

## [0.7.0] - 2026-03-11

### Added
- **Token-based auth for ChatGPT**: Managed-browser login and session cookie
  extraction for `neuralclaw session auth chatgpt`.
- **Token-based auth for Claude**: Session key extraction from browser cookies.
  Run `neuralclaw session auth claude`.
- **New providers**: `chatgpt_token` (supports tool use) and `claude_token` for
  token-based API access without persistent browser automation.
- **CLI auth wizard**: `neuralclaw session auth <provider>` guides users through
  managed cookie or session key setup with Rich panels and step-by-step flow.
- **Token refresh**: `neuralclaw session refresh chatgpt` refreshes or reacquires
  the stored ChatGPT credential when possible.
- **Token health monitoring**: `neuralclaw session status` shows token validity and
  expiry alongside browser session status. `neuralclaw doctor` reports token health.
- **Secure token storage**: All tokens stored in OS keychain via `keyring`, never
  in config files or logs.
- **Auto-fallback chain**: Token providers automatically fall back to browser session
  providers, then to API key providers.
- **42 new tests**: Comprehensive coverage for auth module, token store, credential
  lifecycle, and both token providers (324 total).

### Changed
- `ProviderConfig` gains `auth_method` field for token-based providers.
- `validate_config()` recognizes `chatgpt_token` and `claude_token` as keyless providers.
- Health checker now includes token validity and expiry warnings.

## [0.6.7] - 2026-03-11

### Added
- **Telegram pairing support**: `/pair` now reaches the trust controller on
  Telegram instead of being dropped as a command before evaluation.

### Fixed
- **Slack thread reply routing**: Gateway replies now propagate `thread_ts`
  so trust-bound Slack thread routes reply in the originating thread.
- **Pairing reliability**: DM and route pairing behavior is now consistent
  across Telegram, Discord, and Slack.

### Changed
- **WhatsApp troubleshooting docs**: Documented the current upstream Baileys
  `405` fresh-session failure mode more clearly so users can distinguish local
  setup errors from upstream bridge issues.

## [0.6.6] - 2026-03-11

### Added
- **Session diagnosis commands**: Added `neuralclaw session diagnose` and
  `neuralclaw session open` to inspect managed browser sessions and guide manual
  login/bootstrap flows.
- **Local Ollama setup**: Added `neuralclaw local setup` and `neuralclaw local status`
  to detect installed Ollama models and save the selected local model in config.

### Changed
- **ChatGPT session guidance**: Documented `chatgpt_app` as experimental and
  clarified recommended fallbacks when upstream auth rejects browser-controlled
  login.
- **Session UX**: Session setup, status, and repair output now surface clearer
  recommendations when ChatGPT or Claude sessions are blocked by upstream auth
  or challenge pages.
- **Local provider defaults**: The local provider now defaults to `qwen3.5:2b`
  instead of the stale `llama3` placeholder, matching common local Ollama setups.

### Fixed
- **Session state reporting**: App-session health now distinguishes
  `auth_rejected`, `challenge`, `login_required`, and `session_error` states
  instead of collapsing them into a generic login failure.

## [0.6.5] - 2026-03-11

### Added
- **Direct app-session providers**: `chatgpt_app` and `claude_app` now run through
  managed Playwright-backed persistent browser profiles instead of requiring an
  external proxy-first setup.
- **Session runtime**: Added `neuralclaw/session/runtime.py` with persistent
  profile launch, login-state detection, readiness checks, session repair, and
  completion polling for browser-backed providers.
- **Session CLI**: Added `neuralclaw session setup`, `session status`,
  `session login`, and `session repair`.
- **Channel trust layer**: Added simple trust-and-binding modes:
  `open`, `pair`, and `bound`, with persisted trusted routes in
  `~/.neuralclaw/data/channel_bindings.json`.
- **New tests**: Added coverage for channel trust decisions, app-session health,
  provider override behavior, and Anthropic tool replay conversion.

### Fixed
- **Provider override bug**: `neuralclaw chat -p proxy` and other overrides now
  reuse configured provider settings instead of constructing empty defaults.
- **Anthropic tool replay**: Tool-use follow-up turns are now converted to the
  correct Anthropic message/content-block format, so tool calling remains usable
  in fallback chains.
- **WhatsApp routing mismatch**: The Baileys adapter now registers as
  `whatsapp`, so inbound responses route back through the correct adapter.
- **Packaging mismatch**: Added install extras for `telegram`, `discord`,
  `slack`, `sessions`, `all-channels`, and `all`, matching documented install
  commands.
- **Default install coverage**: `pip install neuralclaw` now pulls in the
  Python dependencies needed for all built-in provider and channel features,
  while docs clearly separate the remaining external prerequisites.
- **Build metadata**: Switched to SPDX-style `license = "MIT"` to remove
  setuptools deprecation warnings from release builds.

### Changed
- **Documentation refresh**: Updated README, channels, configuration, commands,
  getting-started, and troubleshooting docs to reflect the actual repo state and
  current CLI/provider/trust flows.
- **CLI guidance**: Top-level and subgroup `--help` output now gives a clearer
  first-run path for install, session setup, channels, chat, and gateway usage.
- **Session hardening UX**: App-session health now distinguishes login-required,
  auth-rejected, Cloudflare challenge, and generic session-error states, and the
  CLI now exposes `session diagnose` and `session open` for manual bootstrap and
  clearer fallback guidance.
- **Status/health surfaces**: Provider and channel status output now includes
  app-session and trust-mode state.

## [0.6.0] - 2026-03-11

### Added
- **GitHub Repository Management** (`github_repos` skill): Clone repos from
  GitHub/GitLab/Bitbucket, auto-detect and install dependencies (Python venvs,
  Node.js node_modules, Rust Cargo, Go modules), list and remove managed repos.
  All repos stored in `~/.neuralclaw/workspace/repos/`.
- **Repository Execution** (`repo_exec` skill): Run scripts and commands from
  cloned repos in sandboxed environments with proper dependency resolution.
  Detects runtime from file extension (.py/.js/.sh/.ts), injects venv/NODE_PATH
  automatically. Command allowlist blocks dangerous executables.
- **API Client** (`api_client` skill): Make authenticated HTTP requests with
  SSRF protection. Supports Bearer, API-key-header, API-key-query, and Basic
  auth types. Save and reuse API configurations with keychain-stored keys.
- **New Capabilities**: `GITHUB_CLONE` and `API_CLIENT` in the capability model
  with scoped grants for the three new skills.
- **Config sections**: `[workspace]` for repo management settings (clone/install
  timeouts, allowed git hosts, max repo size), `[apis]` for saved API configs.
- **Sandbox enhancement**: `extra_env` parameter on `execute_command()` for
  injecting environment variables (VIRTUAL_ENV, NODE_PATH) into subprocess.
- **88 new tests**: 13 for github_repos (URL validation, name sanitization,
  dep detection, path traversal), 27 for repo_exec (command validation, env
  building, security blocking), 17 for api_client (SSRF, auth injection,
  keychain storage), 4 for policy engine (new tool coverage).

### Security
- Git clone restricted to HTTPS + allowed hosts only (github.com, gitlab.com,
  bitbucket.org by default). Embedded credentials blocked.
- All API requests go through SSRF validation with DNS rebinding defense.
  Redirect URLs validated before following.
- Script execution gated by `deny_shell_execution` policy (default: deny).
  Users must explicitly opt in via config.
- API keys stored in OS keychain, never in config.toml plaintext. Redacted
  from audit logs.
- Command allowlist for repo execution blocks `rm`, `sudo`, `curl`, `wget`,
  `nc`, `ssh`, pipe-to-shell, and other dangerous patterns.

### Changed
- Policy engine now validates `clone_repo`, `api_request`, `run_repo_script`,
  and `run_repo_command` tool calls with appropriate SSRF and shell-execution
  checks.
- Default `allowed_tools` list expanded with 9 new tools.
- Default `allowed_filesystem_roots` includes `~/.neuralclaw/workspace/repos`.
- Deliberative reasoner DNS-rebinding check extended to `clone_repo` and
  `api_request` (was only `fetch_url`).

## [0.5.3] - 2026-03-10

### Fixed
- **WhatsApp 405 reconnect loop**: Bridge script now retries up to 5 times
  with exponential backoff instead of looping infinitely. Emits `fatal` event
  when retries exhausted and exits cleanly.

## [0.5.2] - 2026-03-10

### Added
- **Auto-install npm dependencies**: `ensure_baileys_installed()` automatically
  installs `@whiskeysockets/baileys` and `@hapi/boom` into managed
  `~/.neuralclaw/bridge/` directory on first WhatsApp use. Users no longer
  need to manually run `npm install`.

## [0.5.1] - 2026-03-09

### Added
- **Proxy setup wizard** (`neuralclaw proxy setup`): Interactive guided
  configuration for reverse proxy providers with connectivity test.
- **WhatsApp QR connection** (`neuralclaw channels connect whatsapp`): QR code
  rendered in terminal for phone pairing.
- **`update_config()` helper**: Programmatic deep-merge updates to config.toml.

## [0.5.0] - 2026-03-08

### Added
- **WhatsApp Baileys adapter**: QR-based WhatsApp connection using Node.js bridge.
- **Signal adapter** placeholder.
- **`qrcode` dependency** for terminal QR rendering.

## [0.4.8] - 2026-03-07

### Added
- **Proxy provider** (`ProxyProvider`): Route through OpenAI-compatible reverse
  proxies (ChatGPT-to-API, one-api, LiteLLM, LobeChat).
- **Circuit breaker** improvements.

## [0.4.7] - 2026-02-26

### Added
- **GPT4Free Integration (`g4f`)**: Users can now use free web account wrappers out of the box. No API keys are required.
- **Dependencies**: Added `g4f`, `curl_cffi`, `python-telegram-bot`, `discord.py`, and `slack-bolt` to the core `dependencies` list so they are installed by default with `pip install neuralclaw`.

### Fixed
- **Windows Terminal Output**: Fixed a crash in `cli.py` on Windows legacy terminals that attempted to print UTF-8 ASCII banners using `CP1252`.
- **CLI Arguments**: Fixed a bug where `--provider` overrides via CLI (e.g., `neuralclaw chat --provider g4f`) were ignored by the Gateway.

## [0.4.3] - 2026-02-25

### Added
- **Interactive Dashboard** — fully rewritten dashboard with 7 monitoring panels
  and interactive controls: spawn/despawn agents, send test messages through the
  cognitive pipeline, join federation peers, message peers, clear memory, and
  toggle feature flags. Live WebSocket data push every 5 seconds.
- **Cross-Node Conversation** — federated agents now process incoming task
  messages through the full cognitive pipeline (perception → threat screen →
  memory → reasoning → action) instead of just acknowledging. Agents think
  with their full brain across the network.
- **Dashboard Message Peer** — click "Message" on any federation node in the
  dashboard to send a message and receive the peer's pipeline-processed response.
- **Gateway CLI Flags** — `--federation-port`, `--dashboard-port`, `--web-port`,
  `--name`, and `--seed` options for running multiple instances without config
  file changes.
- **Agent Spawner** (`swarm/spawn.py`) — unified agent lifecycle manager that
  registers agents in both AgentMesh and DelegationChain. Supports local
  in-process agents and remote HTTP-proxy agents.
- **Federation Bridge** integration — auto-syncs federation peers into the
  local mesh as `fed:<name>` agents via AgentSpawner.
- **Memory methods** — `count()` and `clear()` on SemanticMemory and
  ProceduralMemory; `clear()` on EpisodicMemory (with FTS5 index rebuild).

### Fixed
- **Dashboard memory panel** always showed 0 for semantic/procedural — used
  nonexistent `entity_count`/`count` properties. Now uses proper async `count()`.
- **Duplicate `fed:` agents** in Swarm Agents panel — manual federation append
  overlapped with FederationBridge auto-sync. Removed the duplicate source.
- **Federation trust score** showed 0% — field name mismatch (`trust` vs
  `trust_score`) between `get_status()` and dashboard JS.
- **Dashboard JS SyntaxError** — `'Enter'` inside a JS single-quoted string
  broke the parser. Fixed quote escaping in Python triple-quoted string.

### Changed
- **COMMANDS.md** fully updated with gateway CLI options, dashboard panel
  reference, API endpoint table, cross-node messaging docs, and step-by-step
  cross-machine federation setup guide.
- `dashboard_port` added to `NeuralClawConfig` dataclass.
- Federation `_handle_message()` rewritten to route task messages through
  `set_message_handler()` callback.

## [0.4.2] - 2026-02-23

### Added
- **Lite Mode / Feature Flags** (`[features]` in config.toml) — disable swarm,
  dashboard, evolution, reflective reasoning, procedural memory, and semantic
  memory independently. Cuts RAM and cold-start time significantly for minimal
  deployments (e.g. Claw Club agent instances that don't need swarm).
- **`FeaturesConfig` dataclass** with a `FeaturesConfig.lite()` class method
  for programmatic lite-mode instantiation.

### Performance
- **Fast-path before memory retrieval** — greetings, farewells, time/date
  queries, and thanks now return in <100ms without any SQLite I/O. Eliminates
  3+ DB ops per casual message (previously memory retrieval ran unconditionally).
- **Persistent IdempotencyStore connection** — rewrote to use a single
  persistent `aiosqlite` connection (same pattern as `EpisodicMemory`) instead
  of opening a new connection per `get()`/`set()` call. Removes per-tool-call
  SQLite connect overhead. Also prunes stale entries (>7 days) on startup.
- **Async telemetry queue** — `Telemetry.handle_event()` now pushes log lines
  to an `asyncio.Queue` drained by a background task instead of blocking the
  event loop with synchronous file writes. Fallback to sync write if queue is
  full (>2000 pending).
- **Lazy Rich import** — `rich.console` and `rich.text` (~6.4 MB) are now only
  imported when `telemetry_stdout=true`. Headless deployments pay zero cost.
- **Lazy aiohttp / Dashboard import** — `dashboard.py` (and `aiohttp`, ~11.7 MB)
  are now only imported when `features.dashboard=true`. Default-off in lite mode.
- **In-memory history trimmed 40→20** — conversation history buffer now matches
  what's actually passed to the LLM, halving per-session RAM for history storage.
- **Lazy keyring** — `keyring` import deferred to call site; env vars resolved
  first with zero library overhead. Added `NEURALCLAW_<PROVIDER>_API_KEY` generic
  fallback for container deployments.
- **Lazy subsystem init** — swarm (delegation, consensus, mesh), evolution
  (calibrator, distiller, synthesizer, meta-cognitive), procedural memory, and
  dashboard are not instantiated when their feature flag is `false`.

### Security
- **Federation server** now binds to `127.0.0.1` by default instead of `0.0.0.0`
  (was exposing agent to entire LAN). Configurable via `bind_host` parameter.
- **Federation message log** capped at 500 entries to prevent memory DoS.
- **Federation discovery** rate-limited to 100 registered nodes max (prevents
  registration spam DoS).
- **Federation inbound messages** truncated to 8000 chars to prevent memory abuse.
- **IdempotencyStore** now validates table name with regex to prevent SQL injection
  via f-string interpolation.
- **Marketplace** docstrings corrected — was claiming Ed25519 signing but actually
  uses HMAC-SHA256 (symmetric). Documented the limitation.
- **Threat screener** expanded with 5 new patterns: markdown image exfiltration,
  Unicode zero-width smuggling, persistent override attempts ("from now on"),
  and tool/function injection.

### Fixed
- **CRITICAL: Gateway crash** when `evolution=False` but a provider is configured
  — `self._synthesizer.set_provider()` called on `None`. Added guard.
- **Telemetry `stop()` bug** — `return self._metrics` was accidentally inside
  `stop()` (dead code, wrong return type). Separated into proper `metrics` property.
- **Config loading crash** — unknown keys in `config.toml` sections caused
  `TypeError` on startup. Added `_filter_fields()` to strip invalid keys.
- **Episodic memory** `_track_access()` did UPDATEs without COMMIT — access
  counts were lost if no subsequent `store()` call. Now batches with single COMMIT.
- **Audit logger** `_entries` list grew unbounded forever — capped at 200
  in-memory (JSONL file retains full history).
- **Neural bus event log** used list with O(n) slice copy for trimming — switched
  to `deque(maxlen=2000)` for O(1) eviction. Reduced default from 5000 to 2000.
- **Telemetry** `from rich.text import Text` ran on every event — now lazy-cached
  to `self._Text` (single import, reused).
- **Version mismatch** — `__init__.py` said 0.4.1 while `pyproject.toml` said 0.4.2.
- **Docs:** `SkillPackage.risk_score` property added so `package.risk_score`
  example in `skills.md` works (was `trust_score` only).
- **Docs:** `SkillRegistry.register_tool()` added — docs referenced it but the
  method did not exist.
- **Docs:** `[policy]` section fully documented in `configuration.md`.
- **Docs:** Idempotency system fully documented in `security.md`.

## [0.4.1] - 2026-02-23

### Added
- **Security & Reliability Upgrade**
  - Tool Policy Engine (`policy.py`) with runtime bounds and sandbox path constraints
  - SSRF Protection (`network.py`) blocking private IPs, cloud metadata, and DNS rebinding
  - Borderline Threat Verifier (`threat_screen.py`) with secondary model validation
  - Content Sanitization (`intake.py`) enforcing character limits and stripping injection delimiters
  - Memory Token Budgets (`retrieval.py`) to prevent prompt injection overruns
  - Circuit Breakers & Jitter Backoff (`router.py`) for robust provider reliability
  - Cost Metrics (`telemetry.py`) tracking LLM calls, tokens, tool actions, and denials
- New config sections: `[policy]` and `[security]` in `config.toml`

### Fixed
- Web search SSRF vulnerabilities
- Sandbox arbitrary path traversal capabilities
- Bug in URL scheme validation and internal DNS resolution

## [0.4.0] - 2026-02-23

### Added
- **Phase 4: Domination**
  - Federation module (`swarm/federation.py`) — cross-network agent discovery, trust scoring, heartbeat monitoring, HTTP-based message relay with TTL and trust gates
  - Marketplace economy (`skills/economy.py`) — credit-based rewards per skill usage, community ratings (1-5), trending algorithm, author leaderboards, persistent state
  - Benchmark suite (`benchmark.py`) — 5 categories: perception, memory, security, reasoning, neural bus latency with percentile stats and JSON export
- New CLI commands: `neuralclaw benchmark`, `neuralclaw federation`
- PEP 561 `py.typed` marker for typed package support
- Published to PyPI — installable via `pip install neuralclaw`

### Changed
- Version bumped to 0.4.0
- Development status upgraded from Alpha to Beta
- GitHub URLs updated to `placeparks/neuralclaw`
- README updated with `pip install` instructions, Phase 4 documentation, and roadmap marked complete
- COMMANDS.md rewritten comprehensively with all commands, APIs, and guides

### Fixed
- Unicode emoji crash on Windows legacy terminal (cp1252 encoding) in CLI commands

## [0.3.0] - 2026-02-23

### Added
- **Phase 3: Swarm Intelligence**
  - Delegation chains with context preservation and provenance tracking
  - Consensus protocol (majority, unanimous, weighted, quorum modes)
  - Agent mesh with A2A-compatible discovery and registration
  - Web dashboard with live WebSocket reasoning traces
- **Comprehensive test suite** — 70+ tests covering perception, memory, evolution, security, and swarm
- **Adversarial threat screening tests** — 15+ prompt injection patterns validated
- GitHub Actions CI workflow
- CONTRIBUTING.md guide
- OpenClaw migration tool (`neuralclaw migrate`)

### Fixed
- All 32 empty exception handlers now have proper error logging or explanatory comments
- Errors in memory retrieval, metabolism, and distiller now publish to neural bus instead of being silently swallowed
- Gateway post-processing errors are logged via telemetry

### Changed
- README updated to reflect Phase 3 completion
- Version bumped to 0.3.0

## [0.2.0] - 2026-02-15

### Added
- **Phase 2: Intelligence Layer**
  - Procedural memory with trigger pattern matching
  - Memory metabolism (consolidation, decay, strengthening, pruning)
  - Reflective reasoning with multi-step planning and self-critique
  - Behavioral calibrator (learns communication preferences from corrections)
  - Experience distiller (episodic → semantic knowledge extraction)
  - Skill synthesizer (auto-generates skills from failure analysis)
  - Skill marketplace with HMAC-SHA256 signing and static analysis
- Phase 2 functional test suite (6 tests)

## [0.1.0] - 2026-02-01

### Added
- **Phase 1: Foundation**
  - Five-cortex architecture (Perception, Memory, Reasoning, Action, Evolution)
  - Neural Bus (async pub/sub with correlation chains)
  - Episodic memory (SQLite + FTS5)
  - Semantic memory (entity-relationship knowledge graph)
  - Intent classifier (zero-shot classification)
  - Pre-LLM threat screener (25+ injection patterns)
  - Capability-based permission model
  - Sandboxed code execution
  - 4 LLM providers (OpenAI, Anthropic, OpenRouter, local/Ollama)
  - 6 channel adapters (Telegram, Discord, Slack, WhatsApp, Signal, Web)
  - Rich CLI with init wizard
  - OS keychain integration for secrets
