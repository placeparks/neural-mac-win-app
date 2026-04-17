# NeuralClaw Agent Charter

## Product Thesis

NeuralClaw is being built as a desktop-first agent operating system for builders, operators, and small teams.

The product is not meant to feel like:

- a generic chatbot
- a loose collection of tools
- an assistant that only talks but cannot operate
- a hidden-power framework that requires internal knowledge to use

The product should feel like:

- an intelligent operator with memory, context, and initiative
- a trustworthy control plane for agentic work
- a local-first desktop system with real integrations and action surfaces
- a product that can become commercially credible, not only technically interesting

## Current Mission

The immediate goal is to turn the current codebase into a coherent, sellable runtime with:

- strong agent orchestration
- visible trust and approval controls
- real integrations and channels
- premium Windows desktop UX
- reliable web research, memory, and computer-use capability

## What Exists Today

### Runtime and Orchestration

- durable task delegation across:
  - manual
  - auto-route
  - consensus
  - pipeline
- approval-gated execution flow in the task system
- role-based model routing for:
  - `primary`
  - `fast`
  - `micro`
  - `embed`
- self-config tooling for controlled runtime changes
- skill forge and skill scout capability

### Memory and Knowledge

- episodic, semantic, procedural, vector, and identity memory
- knowledge-base ingestion and search
- startup auto-indexing from configured project paths
- embedding-only model separation for memory/RAG

### Integrations and Channels

- connections surface for:
  - GitHub
  - Google Workspace
  - Slack
  - Jira
  - Notion
  - Supabase
  - databases
- channel surface for:
  - Telegram
  - Discord
  - Slack
  - WhatsApp
  - Signal

### Desktop Product

- setup wizard that persists real runtime configuration
- settings surface for providers, models, memory, features, channels, search providers, and assistant controls
- task inbox and orchestration visibility
- connections control plane
- operator dashboard with:
  - brief
  - recommended actions
  - recent actions audit trail
- floating avatar / assistant surface

## Boundaries

These constraints are deliberate and should remain explicit.

### Autonomy Boundaries

- The agent must not self-configure unless the user has explicitly permitted it.
- The agent must not assume forge/scout/user-skill mutation powers are available.
- Mutating integration actions should trend toward approval or explicit policy gates.
- Embedding-only models must remain blocked from chat and delegation roles.

### UX Boundaries

- The desktop app should not expose power only through hidden or inconsistent controls.
- Every major page should explain what it is for and how the user should use it.
- The avatar must not behave like a toy, gimmick, or unstable animation shell.
- Feature toggles must map to real runtime behavior and be visibly trustworthy.

### Product Boundaries

- “Connected” is not the same as “operationally ready.”
- A build passing is not enough; installed runtime behavior matters.
- Hidden backend capability that is not surfaced clearly in desktop UX is unfinished product work.
- Observability is a first-class product need, not only an engineering convenience.

## Current Known Gaps

### Voice and Assistant

- Voice input still depends too heavily on desktop/browser speech support.
- A stronger backend STT path is still needed for consistently premium Windows behavior.
- The avatar bundle remains large and should be optimized further.

### Integrations

- Slack is improved, but full deep operation still needs stronger activity surfaces and end-user polish.
- OAuth experiences exist, but should keep moving toward true consumer-grade sign-in flows.
- Discord, Jira, Notion, and Supabase still need deeper end-to-end workflows after connection.

### Agentic Core

- Planner/executor/reviewer orchestration exists for pipeline runs with explicit stage metadata.
- Approval metadata includes persistence after task completion, alongside a transactional rollback mechanic via the `CompensatingRollbackRegistry`.
- Proactive operation is now actively driven by memory, integrations, and recent action trails using the new `AdaptiveControlPlane`.

### Observability

- File logging in packaged runs has been inconsistent.
- Tool/audit failures are being hardened so denied or crashed actions keep a non-empty diagnostic reason instead of blank error fields.
- The dashboard audit trail is now the primary source of truth for recent tool execution, especially when packaged log capture is incomplete.
- The dashboard now exposes recent audit actions, but observability still needs to expand into a richer runtime diagnostics story.

## Operating Principles

When working on NeuralClaw, optimize for:

1. Real capability over demo tricks
2. Clear user control over hidden magic
3. Strong installed-app behavior, not only source-tree behavior
4. Desktop UX that teaches the product instead of hiding it
5. Agent actions that can be inspected, trusted, and approved

## Roadmap Spine

The roadmap should continue in this order.

### Phase 1: Trustworthy Agent Core

- approval-gated durable execution
- clearer autonomy controls
- runtime action visibility
- stronger operator dashboard

Status:

- largely in place

### Phase 2: Planner / Executor / Reviewer Loop

- structured multi-step work graph
- explicit review stage before finalization
- artifact handoff between stages
- resumable execution checkpoints
- better “why this happened” traces

Status:

- in active implementation, core pipeline path now exists

### Phase 3: Integration-Driven Agent Work

- GitHub operational loops
- Slack operator workflows
- Google follow-up loops
- Supabase / DB aware execution
- stronger connection health and recent activity

Status:

- successfully in place, backed by transactional rollback guarantees and the `AdaptiveControlPlane` operator brief.

### Phase 4: Multimodal Operator Mode

- reliable backend STT
- stronger push-to-talk entry
- better screen-to-action handoff
- more premium assistant and computer-use experience

Status:

- partially in place, needs stronger reliability and deeper actionability

### Phase 5: Proactive Context Engine

- richer memory-backed operator brief
- daily or contextual proactive suggestions
- better “what changed / what needs action” behavior
- integration-aware summaries

Status:

- completely integrated; proactive `RoutineScheduler` and `IntentPredictor` now poll background patterns directly on the central runtime bus.

## Short-Term Priority List

1. Ship planner/executor/reviewer orchestration
2. Extend staged execution beyond pipeline-only runs
3. Tighten packaged runtime logging and diagnostics
4. Deepen Slack and GitHub into operational workflows
5. Improve voice initiation with a backend STT path

## Validation Baseline

Current source-tree validation expected after meaningful runtime work:

- `python -m py_compile neuralclaw/gateway.py neuralclaw/dashboard.py`
- `npm run build` in `desktop/`

Installed-app validation remains required for:

- sidecar lifecycle changes
- settings persistence and live toggle behavior
- integrations and channels
- avatar / assistant behavior
- approval and orchestration flows

## Product Aspiration

NeuralClaw should become an intelligent operator that can:

- understand the current state of work
- choose strong next actions
- operate across tools and channels
- ask for approval when appropriate
- explain what it did and why
- feel premium, deliberate, and reliable on Windows

It should not feel like a dumb worker waiting for instructions.
