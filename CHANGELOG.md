# Changelog

All notable changes to NeuralClaw should be documented here.

## [Unreleased] - 2026-04-13

### Added - Adaptive Control Plane

- Added `RoutineScheduler` for background proactive script/task execution
- Added `IntentPredictor` mapping recent actions to auto-suggested next steps
- Added `StyleAdapter` for continuous passive tone/format learning in desktop chatter
- Added `CompensatingRollbackRegistry` enabling transactional undo loops on selected integrations
- Tied all observers into the core event bus during Gateway `start()` logic

### Added - Desktop Product Surface

- Added a dedicated `Connections` page to the desktop app as a user-facing connection hub
- Added integration connect/test/disconnect routes and desktop wiring for supported providers
- Added `Computer + Voice Assistant` settings surface for avatar, desktop control, browser control, and voice behavior
- Added assistant screen preview route through the dashboard/gateway
- Added desktop-side assistant auto-speak helper and avatar mic input
- Added project tracker file `agent.md`

### Added - Agentic Platform

- Added richer durable task metadata for delegation/orchestration flows
- Added self-config skill for runtime config and policy changes
- Added GitHub operations skill
- Added KB auto-indexing from configured project paths
- Added role-based local model controls in wizard/settings for `primary`, `fast`, `micro`, and `embed`
- Added approval-gated execution flow for delegation tasks
- Added operator brief and recommended-actions surface in the desktop dashboard
- Added recent-action audit feed in the desktop operator view

### Added - Integrations

- Added GitHub OAuth connection flow
- Added Google Workspace connect/test flow
- Added Slack workspace connection flow in the desktop control plane
- Added Supabase save/test flow
- Added richer integration inventory in the desktop and gateway
- Added more complete per-channel configuration schemas and validation in the desktop/settings flow

### Changed - Web Research Quality

- Improved fallback web search behavior for recommendation-style queries
- Replaced fragile DuckDuckGo library dependency path with direct HTML results parsing
- Added result ranking, dedupe, and editorial weighting
- Improved extracted page readability for fetched content
- Added search provider configuration in desktop settings for:
  - Tavily
  - Brave
  - Serper
  - Google Custom Search
  - SearXNG

### Changed - Local Model and Routing

- Increased local/gateway request timeout ceilings from 120 seconds to 600 seconds
- Lowered deliberate chat default token ceiling to reduce long local-model stalls
- Rebuilt provider and role-router on runtime config refresh
- Fixed direct-model override path so role routing no longer bypasses the requested override

### Fixed - Wizard and Runtime Configuration

- Fixed setup wizard so provider secrets and model selection are actually persisted into gateway config
- Fixed stale provider/model routing after config updates
- Fixed empty timeout error bubbles caused by empty `TimeoutError()` stringification
- Fixed thinking-model empty response path by falling back to reasoning payloads

### Fixed - Delegation and Model Safety

- Fixed consensus dashboard call shape in the installed app
- Blocked embedding-only models from chat/delegation roles and agent definitions
- Preserved embedding models for memory/RAG only
- Fixed feature/autonomy visibility gaps by surfacing all boolean backend feature flags to desktop settings
- Fixed forge/self-config alignment after hot config reload by reconciling runtime allowlists and runtime tool registration

### Fixed - Desktop Runtime Stability

- Added single-instance desktop protection
- Improved sidecar ownership handling so healthy backend attachment is not confused with owned backend lifecycle
- Reduced stale sidecar accumulation across installer validation cycles

### Fixed - Avatar/Assistant Stability

- Reduced duplicate assistant speech on Windows by deduping replayed replies
- Fixed websocket finalize path so speaking state is not immediately cancelled
- Guarded stale emotion-reset timers so newer avatar states are not overwritten by older timers
- Improved mic-input cleanup and input-collapse behavior
- Improved response/error mirroring across avatar state fields
- Improved assistant toggle/runtime alignment for voice, browser, and desktop capabilities

### Changed - Desktop UX and Guidance

- Added visible guidance/info surfaces across Dashboard, Agents, Tasks, Workspace, Connections, and Settings
- Added explicit autonomy controls for self-configuration and skill-forging powers
- Grouped feature toggles by product area instead of a flat list

## [1.5.5] - 2026-03-29

### Changed - Release Refresh

- Rolled up the latest in-repo updates into the `1.5.5` package release
- Refreshed package metadata, version banners, and release references for the `1.5.5` build path

## [1.5.0] - 2026-03-29

### Added - Managed App Workspace Provisioning

- Added a dedicated `build_app` workflow that provisions fresh projects under the approved apps workspace root
- New app scaffolds now carry a `.neuralclaw-app.json` marker

## [1.4.0] - 2026-03-28

### Added - Controlled Capability Self-Improvement

- Added persistent evolution orchestration for repeated capability failures and candidate skill promotion/quarantine

## [1.3.1] - 2026-03-28

### Fixed - Windows Service Runtime Stability

- Fixed Windows service environment/runtime path handling and related status/log behavior

## [1.2.9] - 2026-03-27

### Fixed - Background Gateway Lifecycle

- Fixed stopped gateway PID/status handling

## [1.2.6] - 2026-03-27

### Fixed - SkillForge Runtime Integrity

- Fixed forge validation, repo execution, and generated manifest/runtime registration issues
