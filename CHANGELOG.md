# Changelog

All notable changes to NeuralClaw will be documented in this file.

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
