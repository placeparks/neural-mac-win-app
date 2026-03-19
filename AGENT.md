# AGENT.md — NeuralClaw Implementation Roadmap

This file is the authoritative implementation guide for any agent session working on
NeuralClaw. Read it fully before touching any code. It describes every planned feature,
the exact file locations, the architecture contracts each piece must honour, and the
comprehensive configuration system that ties everything together.

NeuralClaw is at **v1.0.0**. The five-cortex architecture (Perception → Memory →
Reasoning → Action → Evolution) is proven and stable. Everything in this document
extends it without rewrites.

---

## Table of Contents

1. [Repository Layout](#1-repository-layout)
2. [Architecture Contracts](#2-architecture-contracts)
3. [Feature Implementations](#3-feature-implementations)
   - [3.1 Vector Embedding Memory](#31-vector-embedding-memory)
   - [3.2 Persistent User Identity & Mental Model](#32-persistent-user-identity--mental-model)
   - [3.3 Browser Cortex + Chrome AI](#33-browser-cortex--chrome-ai)
   - [3.4 Vision Perception](#34-vision-perception)
   - [3.5 TTS Skill + Discord Voice](#35-tts-skill--discord-voice)
   - [3.6 Google Workspace Skill](#36-google-workspace-skill)
   - [3.7 Microsoft 365 Skill](#37-microsoft-365-skill)
   - [3.8 Parallel Tool Execution](#38-parallel-tool-execution)
   - [3.9 Streaming Responses](#39-streaming-responses)
   - [3.10 Structured Output Enforcement](#310-structured-output-enforcement)
   - [3.11 A2A Federation Protocol](#311-a2a-federation-protocol)
   - [3.12 Traceline Observability](#312-traceline-observability)
   - [3.13 Prompt Armor v2](#313-prompt-armor-v2)
   - [3.14 Audit Forensic Replay](#314-audit-forensic-replay)
   - [3.15 Desktop Control Skill](#315-desktop-control-skill)
4. [Configuration System](#4-configuration-system)
   - [4.1 Full config.toml Reference](#41-full-configtoml-reference)
   - [4.2 Config Dataclass Changes](#42-config-dataclass-changes)
   - [4.3 DEFAULT_CONFIG Changes](#43-default_config-changes)
   - [4.4 Feature Flag Reference](#44-feature-flag-reference)
5. [Capability Enum Additions](#5-capability-enum-additions)
6. [pyproject.toml Optional Extras](#6-pyprojecttoml-optional-extras)
7. [Policy Allowlist Additions](#7-policy-allowlist-additions)
8. [Testing Checklist](#8-testing-checklist)
9. [Architectural Rules](#9-architectural-rules)

---

## 1. Repository Layout

```
neuralclaw/
├── cortex/
│   ├── memory/
│   │   ├── episodic.py          ✅ exists
│   │   ├── semantic.py          ✅ exists
│   │   ├── procedural.py        ✅ exists
│   │   ├── retrieval.py         ✅ exists
│   │   ├── metabolism.py        ✅ exists
│   │   ├── vector.py            🔨 NEW — sqlite-vec embedding store
│   │   └── identity.py          🔨 NEW — persistent user mental model
│   ├── perception/
│   │   ├── intake.py            ✅ exists
│   │   ├── classifier.py        ✅ exists
│   │   ├── threat_screen.py     ✅ exists
│   │   ├── vision.py            🔨 NEW — multimodal image perception
│   │   └── output_filter.py     🔨 NEW — Prompt Armor v2 output screening
│   ├── reasoning/
│   │   ├── fast_path.py         ✅ exists
│   │   ├── deliberate.py        ✅ exists  (parallel tool exec goes here)
│   │   ├── reflective.py        ✅ exists
│   │   ├── meta.py              ✅ exists
│   │   └── structured.py        🔨 NEW — Pydantic-enforced structured output
│   ├── action/
│   │   ├── sandbox.py           ✅ exists
│   │   ├── capabilities.py      ✅ exists  (new enums go here)
│   │   ├── audit.py             ✅ exists
│   │   ├── idempotency.py       ✅ exists
│   │   ├── network.py           ✅ exists
│   │   ├── policy.py            ✅ exists
│   │   ├── browser.py           🔨 NEW — Playwright browser cortex
│   │   └── desktop.py           🔨 NEW — PyAutoGUI desktop control
│   └── evolution/
│       ├── calibrator.py        ✅ exists
│       ├── distiller.py         ✅ exists
│       └── synthesizer.py       ✅ exists
├── cortex/
│   └── observability/
│       └── traceline.py         🔨 NEW — full reasoning trace store + export
├── channels/
│   ├── protocol.py              ✅ exists  (add send_stream ABC method)
│   ├── discord_adapter.py       ✅ exists  (extend with VC + stream)
│   ├── telegram.py              ✅ exists  (extend with stream editing)
│   ├── web.py                   ✅ exists  (extend with SSE)
│   └── ...
├── skills/
│   └── builtins/
│       ├── web_search.py        ✅ exists
│       ├── file_ops.py          ✅ exists
│       ├── code_exec.py         ✅ exists
│       ├── calendar_skill.py    ✅ exists
│       ├── github_repos.py      ✅ exists
│       ├── repo_exec.py         ✅ exists
│       ├── api_client.py        ✅ exists
│       ├── tts.py               🔨 NEW — TTS skill (edge-tts / OpenAI / ElevenLabs)
│       ├── google_workspace.py  🔨 NEW — Gmail, Calendar, Drive, Docs, Sheets
│       └── microsoft365.py      🔨 NEW — Outlook, Teams, OneDrive, SharePoint
├── swarm/
│   ├── federation.py            ✅ exists  (extend with A2A envelope)
│   └── ...
├── config.py                    ✅ exists  (comprehensive additions — see §4)
└── gateway.py                   ✅ exists  (wire new subsystems)
```

---

## 2. Architecture Contracts

Every piece of new code must honour these invariants. Do not break them.

### The Neural Bus contract
All subsystems communicate through `NeuralBus`. New modules must:
- Accept `bus: NeuralBus | None = None` in `__init__`
- Call `await self._bus.publish(EventType.X, {...}, source="module.name")` for state changes
- Never raise exceptions that bubble past the gateway — catch and publish `EventType.ERROR`

### The Skill contract
Every new builtin skill must:
- Live in `neuralclaw/skills/builtins/<name>.py`
- Export a `get_manifest() -> SkillManifest` function (auto-discovered by `load_builtins()`)
- Declare required `Capability` enums in the manifest
- Have async handler functions for every `ToolDefinition`
- Return `dict[str, Any]` from every handler — never raise, return `{"error": "..."}` instead
- Pass all outbound URLs through `validate_url_with_dns()` from `cortex/action/network.py`

### The ChannelAdapter contract
All channel adapters must implement the `ChannelAdapter` ABC from `channels/protocol.py`:
- `async def start() -> None`
- `async def stop() -> None`
- `async def send(channel_id: str, content: str, **kwargs) -> None`
- `async def test_connection() -> tuple[bool, str]`

New optional capabilities (streaming, voice) are **additive mixins** — they never change
the base ABC so existing channels keep working unchanged.

### The Config contract
Every new feature must:
- Have a feature flag in `[features]` section (`bool`, default `false` for experimental)
- Have its own `[section]` in `config.toml` for per-feature settings
- Add a corresponding `@dataclass` in `config.py`
- Be loaded in `load_config()` with `_filter_fields()` protection
- Be lazy-initialized in `gateway.py` behind `if feat.feature_name:`

### The Capability contract
Every skill that touches external resources, audio, UI, or OS APIs must declare a
`Capability` enum value. The `CapabilityVerifier` in `cortex/action/capabilities.py`
enforces this. New capabilities go in the `Capability(Enum)` class. Default grants
for new builtin skills go in `CapabilityVerifier.__init__`'s `self._grants` dict.

---

## 3. Feature Implementations

---

### 3.1 Vector Embedding Memory

**File:** `neuralclaw/cortex/memory/vector.py`

**Purpose:** Semantic similarity search alongside the existing FTS5 keyword search.
Closes the gap where "book medical appointment" doesn't match "schedule a doctor visit".

**Backend:** `sqlite-vec` (SQLite extension, zero external service dependency).
Embedding model: `nomic-embed-text` via Ollama (local, free) or OpenAI
`text-embedding-3-small` (cheap, high quality). Provider is configurable.

**Schema:**
```sql
CREATE VIRTUAL TABLE IF NOT EXISTS vec_embeddings USING vec0(
    id TEXT PRIMARY KEY,
    source TEXT,          -- "episodic" | "semantic" | "procedural"
    ref_id TEXT,          -- FK to the source table row
    embedding FLOAT[768], -- nomic-embed-text dimension; 1536 for OpenAI
    content_preview TEXT  -- first 200 chars for debugging
);
```

**Class interface:**
```python
class VectorMemory:
    def __init__(self, db_path: str, embedding_provider: str = "local",
                 embedding_model: str = "nomic-embed-text",
                 dimension: int = 768, bus: NeuralBus | None = None) -> None: ...

    async def initialize(self) -> None: ...

    async def embed_and_store(
        self,
        content: str,
        ref_id: str,
        source: str = "episodic",
    ) -> str: ...
    # Returns vector row ID. Called by EpisodicMemory.store() hook.

    async def similarity_search(
        self,
        query: str,
        top_k: int = 10,
        source_filter: str | None = None,
    ) -> list[VectorResult]: ...
    # Returns list of (ref_id, source, score, content_preview)

    async def delete_by_ref(self, ref_id: str) -> None: ...
    # Called when episodic memory prunes an episode (metabolism)

    async def close(self) -> None: ...
```

**Integration points:**
- `EpisodicMemory.store()` → call `vector_memory.embed_and_store(content, episode.id, "episodic")` after inserting
- `MemoryRetriever.retrieve()` → add fourth result source: `vector_memory.similarity_search(query)`, merge with existing FTS + recency + semantic results, deduplicate by `ref_id`
- `MemoryMetabolism` pruning path → call `vector_memory.delete_by_ref(episode_id)` when pruning episodes
- `NeuralClawGateway.__init__` → lazy-init behind `if feat.vector_memory:`

**Config section `[memory]` additions:**
```toml
vector_memory           = true   # master switch
embedding_provider      = "local"      # "local" (Ollama) | "openai"
embedding_model         = "nomic-embed-text"   # or "text-embedding-3-small"
embedding_dimension     = 768          # 768 for nomic, 1536 for OpenAI
vector_similarity_top_k = 10
```

**pyproject.toml extra:** `pip install neuralclaw[vector]` pulls `sqlite-vec`.

---

### 3.2 Persistent User Identity & Mental Model

**File:** `neuralclaw/cortex/memory/identity.py`

**Purpose:** Build and maintain a living model of each user across sessions and channels.
A user on Telegram and the same user on Discord share the same `UserModel`. The model is
injected into every prompt so the agent knows who it's talking to without needing to
re-learn preferences every session.

**Data model:**
```python
@dataclass
class UserModel:
    user_id: str                      # canonical ID (hashed from platform+user_id)
    display_name: str
    platform_aliases: dict[str, str]  # {"telegram": "123", "discord": "456"}
    communication_style: dict         # from BehavioralCalibrator preferences
    active_projects: list[str]        # inferred from episodic keyword frequency
    expertise_domains: list[str]      # inferred from semantic graph entity types
    language: str                     # detected from messages
    timezone: str                     # inferred from timestamps
    preferences: dict                 # explicit corrections ("be shorter", "no emojis")
    last_seen: float
    first_seen: float
    session_count: int
    message_count: int
    notes: str                        # freeform notes the agent can write about the user
```

**Class interface:**
```python
class UserIdentityStore:
    def __init__(self, db_path: str, bus: NeuralBus | None = None) -> None: ...
    async def initialize(self) -> None: ...

    async def get_or_create(self, platform: str, platform_user_id: str,
                             display_name: str) -> UserModel: ...
    async def update(self, user_id: str, updates: dict) -> None: ...
    async def merge_aliases(self, canonical_id: str, platform: str,
                             platform_user_id: str) -> None: ...
    # Cross-channel identity linking — when a user /pairs their accounts

    async def synthesize_model(self, user_id: str) -> UserModel: ...
    # Re-derive active_projects and expertise_domains from memory stores

    async def to_prompt_section(self, user_id: str) -> str: ...
    # Returns "## Who I'm talking to\n- Name: ...\n- Projects: ...\n- Style: ..."
    # Injected by gateway into deliberative reasoner system prompt
```

**Integration points:**
- `gateway._handle_message()` → resolve `UserModel` from `ChannelMessage.author_id` + channel name, pass to `DeliberativeReasoner._build_messages()` as additional system context
- `BehavioralCalibrator` → write preference changes back to `UserIdentityStore`
- `ExperienceDistiller.distill()` → call `identity_store.synthesize_model(user_id)` to refresh active_projects and expertise_domains after each distillation cycle
- Trust controller pairing → call `identity_store.merge_aliases()` when a user successfully pairs two channels

**Config section `[identity]`:**
```toml
[identity]
enabled        = true
cross_channel  = true    # link same user across Telegram/Discord/Slack
inject_in_prompt = true  # add user model section to every prompt
notes_enabled  = true    # agent can write structured notes about each user
```

---

### 3.3 Browser Cortex + Chrome AI

**File:** `neuralclaw/cortex/action/browser.py`

**Purpose:** Playwright-powered browser automation with LLM-guided action planning.
`playwright` is already a declared dependency. No new install required for basic use.
Chrome AI APIs (on-device Prompt API, Summarizer API) are exposed via CDP injection
when the agent runs on Chrome/Chromium.

**Architecture:** The browser cortex is a stateful service — one browser context
per agent instance, reused across tool calls in a session. Not one browser per call.

**Core data models:**
```python
@dataclass
class BrowserState:
    url: str
    title: str
    screenshot_b64: str     # current viewport screenshot as base64 PNG
    text_content: str       # extracted text from page (truncated to 8000 chars)
    interactive_elements: list[dict]  # buttons, inputs, links visible

@dataclass
class BrowserAction:
    action: str             # "navigate" | "click" | "type" | "scroll" | "extract" | "js"
    target: str             # CSS selector, text description, or JS code
    value: str = ""         # text to type, scroll direction, etc.
    reasoning: str = ""     # why this action was chosen (for audit)

@dataclass
class BrowserResult:
    success: bool
    state: BrowserState | None
    extracted_data: dict
    error: str = ""
    actions_taken: list[BrowserAction] = field(default_factory=list)
```

**Class interface:**
```python
class BrowserCortex:
    def __init__(self, config: BrowserConfig, bus: NeuralBus | None = None,
                 vision: "VisionPerception | None" = None) -> None: ...

    async def start(self) -> None: ...
    # Launch Playwright browser, apply stealth settings

    async def stop(self) -> None: ...

    # --- Low-level tool handlers (registered as skills) ---

    async def navigate(self, url: str) -> dict: ...
    async def screenshot(self) -> dict: ...
    # Returns {"screenshot_b64": "...", "url": "...", "title": "..."}

    async def click(self, selector: str) -> dict: ...
    # selector can be CSS, XPath, or natural language description
    # Natural language → VisionPerception locates the element in screenshot

    async def type_text(self, selector: str, text: str) -> dict: ...
    async def scroll(self, direction: str = "down", amount: int = 3) -> dict: ...
    async def extract(self, query: str) -> dict: ...
    # LLM-powered extraction: "find all product prices on this page"

    async def execute_js(self, code: str) -> dict: ...
    # Runs sanitized JS. Blocked by policy unless browser.allow_js = true

    async def wait_for(self, condition: str, timeout: int = 10) -> dict: ...
    # "wait for login button to appear", "wait for page to stop loading"

    # --- Chrome AI API integration ---
    async def chrome_summarize(self, selector: str = "body") -> dict: ...
    # Uses window.ai.summarizer (Chrome 127+, on-device, no API call)

    async def chrome_translate(self, text: str, target_lang: str = "en") -> dict: ...
    # Uses window.translation Chrome API

    async def chrome_prompt(self, prompt: str, context_selector: str = "") -> dict: ...
    # Uses chrome.aiOriginTrial.languageModel.create() — on-device LLM

    # --- High-level task execution ---
    async def act(self, task: str, url: str | None = None,
                  max_steps: int = 20) -> BrowserResult: ...
    # Natural language task: "log in to example.com and download the invoice"
    # Loop: screenshot → VisionPerception/LLM plans next action → execute → repeat
```

**Skill manifest tools to register:**
`browser_navigate`, `browser_screenshot`, `browser_click`, `browser_type`,
`browser_scroll`, `browser_extract`, `browser_execute_js`, `browser_act`,
`chrome_summarize`, `chrome_translate`

**Required new capability:** `BROWSER_CONTROL = auto()` in `Capability` enum.

**Integration:** Browser cortex is instantiated in `gateway.py` behind
`if feat.browser:`. The `BrowserCortex` instance is passed into `SkillRegistry`
tool registrations — its methods become tool handlers directly.

**Config section `[browser]`:**
```toml
[browser]
enabled             = false   # master switch — requires playwright + chromium
headless            = true    # false for debug/demo
browser_type        = "chromium"   # "chromium" | "firefox" | "webkit"
viewport_width      = 1280
viewport_height     = 900
stealth             = true    # apply stealth JS patches (avoid bot detection)
allow_js_execution  = false   # execute_js tool — off by default, security risk
max_steps_per_task  = 20      # max actions in a single browser_act call
screenshot_on_error = true    # capture screenshot when an action fails
chrome_ai_enabled   = false   # Chrome on-device AI APIs (requires Chrome, not Chromium)
navigation_timeout  = 30      # seconds
user_data_dir       = ""      # persist browser profile (cookies, logins)
allowed_domains     = []      # if non-empty, only these domains are navigable
blocked_domains     = ["localhost", "127.0.0.1", "169.254.169.254"]
```

**pyproject.toml extra:** `pip install neuralclaw[browser]` — Playwright is already
in core deps but `pip install neuralclaw[browser]` also runs `playwright install chromium`.

---

### 3.4 Vision Perception

**File:** `neuralclaw/cortex/perception/vision.py`

**Purpose:** Process images sent by users or captured by the browser cortex. The
`ChannelMessage.media: list[dict]` field already exists but nothing consumes it.
This closes that gap.

**Supported backends (in priority order):**
1. Anthropic Claude (existing provider — natively multimodal, zero extra cost)
2. OpenAI GPT-4o vision (existing provider — natively multimodal)
3. Ollama `llava` or `llama3.2-vision` (local, free)

**Class interface:**
```python
class VisionPerception:
    def __init__(self, provider: LLMProvider, bus: NeuralBus | None = None) -> None: ...

    async def describe(self, image_b64: str, context: str = "",
                        detail: str = "auto") -> str: ...
    # Returns natural language description of the image

    async def extract_text(self, image_b64: str) -> str: ...
    # OCR — extracts all readable text from image

    async def answer_about(self, image_b64: str, question: str) -> str: ...
    # VQA — "what is the total on this invoice?"

    async def locate_element(self, screenshot_b64: str,
                              description: str) -> dict | None: ...
    # Returns {"x": int, "y": int, "confidence": float} for browser cortex click()
    # "Find the Submit button" → pixel coordinates

    async def process_media(self, media_item: dict,
                             user_query: str) -> str: ...
    # Called by gateway when ChannelMessage.media is non-empty
    # Dispatches to describe/extract_text/answer_about based on context
```

**Integration points:**
- `gateway._handle_message()` → when `msg.media` is non-empty, call
  `vision.process_media(item, msg.content)` for each item, prepend result to the
  signal content so the reasoning cortex has the visual context
- `BrowserCortex.click()` and `BrowserCortex.act()` → call
  `vision.locate_element(screenshot, description)` for natural language selectors
- No new config section needed — vision uses existing provider config.
  Add one flag: `features.vision = true`

---

### 3.5 TTS Skill + Discord Voice

**File:** `neuralclaw/skills/builtins/tts.py`
**File:** extend `neuralclaw/channels/discord_adapter.py`

#### TTS Skill

**Backends (controlled by `tts.provider` config):**
- `edge-tts` — free, Microsoft neural voices, no API key, ~100ms latency
- `openai` — OpenAI TTS-1 / TTS-1-HD, uses existing OpenAI API key
- `elevenlabs` — highest quality, requires ElevenLabs API key
- `piper` — fully local, runs on CPU, zero cost, requires `piper-tts` binary

**Tool handlers to register:**
```python
async def speak(text: str, voice: str = "", speed: float = 1.0,
                output_format: str = "mp3") -> dict: ...
# Returns {"audio_path": "/tmp/nc_tts_<id>.mp3", "duration_seconds": float}
# Audio file is written to a temp path, cleaned up after playback

async def list_voices(provider: str = "") -> dict: ...
# Returns available voice names for the configured provider

async def speak_and_play(text: str, channel_id: str,
                          platform: str = "discord") -> dict: ...
# TTS + route audio to voice channel in one call
```

**Required new capability:** `AUDIO_OUTPUT = auto()` in `Capability` enum.

#### Discord Voice Extension

Extend `DiscordAdapter` with an inner `VoiceManager` that handles VC lifecycle:

```python
class DiscordAdapter(ChannelAdapter):
    # --- existing methods unchanged ---

    # --- new voice methods ---
    async def join_voice(self, channel_id: str) -> bool: ...
    # Joins the voice channel. Returns True on success.

    async def leave_voice(self) -> None: ...

    async def speak(self, audio_path: str,
                    channel_id: str | None = None) -> None: ...
    # Plays audio file in connected VC via FFmpegPCMAudio.
    # Joins channel_id first if not already connected.

    async def is_in_voice(self) -> bool: ...

    @property
    def current_voice_channel(self) -> str | None: ...
```

**New `on_voice_state_update` handler:** When the bot is the last member in a VC,
auto-disconnect to avoid idle connection. Controlled by
`channels.discord.auto_disconnect_empty_vc = true`.

**gateway integration:** After `adapter.send(channel_id, response_text)`,
if `feat.voice` is true and the channel adapter is Discord and TTS is enabled,
call `tts_skill.speak(response_text)` then `discord_adapter.speak(audio_path)`.
This is opt-in per-channel via `channels.discord.voice_responses = false`.

**Required new capability:** `VOICE_CHANNEL = auto()` in `Capability` enum.

**Config section `[tts]`:**
```toml
[tts]
enabled          = false
provider         = "edge-tts"        # "edge-tts" | "openai" | "elevenlabs" | "piper"
voice            = "en-US-AriaNeural"  # provider-specific voice name
speed            = 1.0
output_format    = "mp3"             # "mp3" | "wav" | "ogg"
piper_binary     = "piper"           # path to piper binary if using local TTS
piper_model      = ""                # path to piper voice model file
auto_speak       = false             # auto-TTS all responses in voice channels
max_tts_chars    = 2000              # truncate text longer than this before TTS
temp_dir         = ""                # override temp dir for audio files (default: system tmp)
```

**Config additions to `[channels.discord]`:**
```toml
[channels.discord]
enabled              = false
trust_mode           = ""
voice_responses      = false    # send TTS audio in addition to text
auto_disconnect_empty_vc = true
voice_channel_id     = ""       # default VC to join (optional)
```

**pyproject.toml extra:** `pip install neuralclaw[voice]` pulls `edge-tts`,
`discord.py[voice]` (PyNaCl + ffmpeg-python).

---

### 3.6 Google Workspace Skill

**File:** `neuralclaw/skills/builtins/google_workspace.py`

**Auth:** OAuth 2.0 via `google-auth-oauthlib`. Refresh token stored in OS keychain
under key `google_oauth_refresh`. One-time setup via `neuralclaw session auth google`.

**Tool handlers to register:**

| Tool name | Description |
|---|---|
| `gmail_search` | Search Gmail with a query string |
| `gmail_send` | Send an email |
| `gmail_get` | Get a specific email by ID |
| `gmail_label` | Apply/remove label on an email |
| `gmail_draft` | Create a draft |
| `gcal_list_events` | List calendar events in a time range |
| `gcal_create_event` | Create a calendar event |
| `gcal_update_event` | Update an existing event |
| `gcal_delete_event` | Delete an event |
| `gdrive_search` | Search Google Drive for files |
| `gdrive_read` | Read a file from Drive (text/Docs/Sheets) |
| `gdrive_upload` | Upload a file to Drive |
| `gdocs_read` | Read Google Doc as plain text |
| `gdocs_append` | Append content to a Google Doc |
| `gsheets_read` | Read a Google Sheet range |
| `gsheets_write` | Write values to a Google Sheet range |
| `gmeet_create` | Create a Google Meet link |

**Required new capabilities:**
```python
GOOGLE_GMAIL   = auto()
GOOGLE_CALENDAR = auto()
GOOGLE_DRIVE   = auto()
GOOGLE_DOCS    = auto()
GOOGLE_SHEETS  = auto()
```

**Config section `[google_workspace]`:**
```toml
[google_workspace]
enabled              = false
scopes               = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]
max_email_results    = 10
max_drive_results    = 10
default_calendar_id  = "primary"
response_body_limit  = 20000     # max chars of email body to inject into context
```

**pyproject.toml extra:** `pip install neuralclaw[google]` pulls
`google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2`.

**Policy additions:** Add all `gmail_*`, `gcal_*`, `gdrive_*`, `gdocs_*`,
`gsheets_*`, `gmeet_*` to `allowed_tools` in default policy when skill is enabled.
Mark `gmail_send`, `gcal_create_event`, `gcal_delete_event`, `gdrive_upload`,
`gdocs_append`, `gsheets_write` as `mutating_tools`.

---

### 3.7 Microsoft 365 Skill

**File:** `neuralclaw/skills/builtins/microsoft365.py`

**Auth:** MSAL (Microsoft Authentication Library). OAuth 2.0 device-code flow
(works headless). Refresh token stored in keychain under `microsoft_oauth_refresh`.
Setup via `neuralclaw session auth microsoft`.

**Tool handlers to register:**

| Tool name | Description |
|---|---|
| `outlook_search` | Search Outlook email |
| `outlook_send` | Send email via Outlook |
| `outlook_get` | Get specific email |
| `ms_cal_list` | List calendar events |
| `ms_cal_create` | Create calendar event |
| `ms_cal_delete` | Delete calendar event |
| `teams_send` | Send Teams message to channel/chat |
| `teams_list_channels` | List Teams channels |
| `onedrive_search` | Search OneDrive |
| `onedrive_read` | Read a file from OneDrive |
| `onedrive_upload` | Upload to OneDrive |
| `sharepoint_search` | Search SharePoint |
| `sharepoint_read` | Read a SharePoint document |

**Required new capabilities:**
```python
MS_OUTLOOK   = auto()
MS_CALENDAR  = auto()
MS_TEAMS     = auto()
MS_ONEDRIVE  = auto()
MS_SHAREPOINT = auto()
```

**Config section `[microsoft365]`:**
```toml
[microsoft365]
enabled           = false
tenant_id         = ""       # Azure tenant ID (or "common" for personal accounts)
scopes            = [
    "Mail.ReadWrite",
    "Calendars.ReadWrite",
    "Files.ReadWrite",
    "Chat.ReadWrite",
    "ChannelMessage.Send",
]
max_email_results = 10
max_file_results  = 10
default_user      = "me"
```

**pyproject.toml extra:** `pip install neuralclaw[microsoft]` pulls `msal`,
`msgraph-sdk`.

---

### 3.8 Parallel Tool Execution

**File:** `neuralclaw/cortex/reasoning/deliberate.py` — modify `reason()` method.

**Change:** When the LLM returns multiple tool calls in a single response, execute
them concurrently with `asyncio.gather` instead of sequentially.

**Exact change location:** In the `while iterations < self.MAX_ITERATIONS:` loop,
replace the `for tc in response.tool_calls:` sequential block:

```python
# BEFORE (sequential):
for tc in response.tool_calls:
    result = await self._execute_tool_call(tc, tools, request_ctx)
    tool_calls_made += 1
    messages.append(...)

# AFTER (parallel):
tool_results = await asyncio.gather(*[
    self._execute_tool_call(tc, tools, request_ctx)
    for tc in response.tool_calls
], return_exceptions=True)
tool_calls_made += len(response.tool_calls)

for tc, result in zip(response.tool_calls, tool_results):
    if isinstance(result, Exception):
        result = {"error": str(result)}
    messages.append({"role": "assistant", "content": None, "tool_calls": [tc.to_dict()]})
    messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
```

**Note:** Idempotency and policy checks inside `_execute_tool_call` are already
async-safe. No other changes needed. This is a 15-line diff.

**Config addition to `[policy]`:**
```toml
parallel_tool_execution = true   # execute independent tool calls concurrently
```

---

### 3.9 Streaming Responses

**Purpose:** Emit response tokens to channels as they arrive from the LLM instead
of buffering the full response. Dramatically improves perceived latency.

**Changes required:**

**1. `ChannelAdapter` ABC** — add optional streaming method:
```python
# In channels/protocol.py
async def send_stream(self, channel_id: str,
                       token_iterator: AsyncIterator[str],
                       **kwargs) -> None:
    # Default implementation: buffer all tokens, call send() at end.
    # Channels that support live-editing override this.
    tokens = []
    async for token in token_iterator:
        tokens.append(token)
    await self.send(channel_id, "".join(tokens), **kwargs)
```

**2. `DiscordAdapter`** — override `send_stream`:
```python
async def send_stream(self, channel_id: str,
                       token_iterator: AsyncIterator[str], **kwargs) -> None:
    channel = await self._get_channel(channel_id)
    message = await channel.send("▌")   # placeholder with cursor
    buffer = []
    async for token in token_iterator:
        buffer.append(token)
        # Edit every 20 tokens to avoid rate limit (5 edits/sec)
        if len(buffer) % 20 == 0:
            await message.edit(content="".join(buffer) + "▌")
    await message.edit(content="".join(buffer))   # final edit, remove cursor
```

**3. `TelegramAdapter`** — override `send_stream` with `editMessageText`.

**4. `WebAdapter`** — override `send_stream` with Server-Sent Events push.

**5. Provider layer** — add `stream_complete()` to `LLMProvider` ABC:
```python
async def stream_complete(self, messages: list[dict],
                           tools: list | None = None) -> AsyncIterator[str]: ...
```
Implement in `AnthropicProvider` (uses `stream=True`), `OpenAIProvider`
(uses `stream=True`). Local/proxy providers fall back to `complete()` buffered.

**6. `DeliberativeReasoner`** — add `reason_stream()` method that uses
`stream_complete()` and yields tokens. Called by gateway when streaming is enabled.

**Config addition to `[features]`:**
```toml
streaming_responses = false   # stream tokens to supported channels
streaming_edit_interval = 20  # tokens between Discord message edits
```

---

### 3.10 Structured Output Enforcement

**File:** `neuralclaw/cortex/reasoning/structured.py`

**Purpose:** Guarantee LLM output conforms to a Pydantic schema. Used internally
by `SkillSynthesizer` (generated skill code), `ExperienceDistiller` (extracted facts),
and by any skill that needs structured data back from the LLM.

**Class interface:**
```python
class StructuredReasoner:
    def __init__(self, deliberate: DeliberativeReasoner,
                 bus: NeuralBus | None = None) -> None: ...

    async def reason_structured(
        self,
        signal: Signal,
        schema: type[BaseModel],          # Pydantic model
        memory_ctx: MemoryContext | None = None,
        max_retries: int = 3,
        use_json_mode: bool = True,        # use provider JSON mode if available
    ) -> BaseModel: ...
    # Retries on validation failure. On third failure raises StructuredOutputError.

    async def extract(
        self,
        text: str,
        schema: type[BaseModel],
        instructions: str = "",
        max_retries: int = 3,
    ) -> BaseModel: ...
    # Simpler: extract structured data from an existing text string
```

**Built-in schemas to define alongside `StructuredReasoner`:**
```python
class GeneratedSkill(BaseModel):
    name: str
    description: str
    code: str
    test_cases: list[str]
    required_imports: list[str]
    estimated_risk: float   # 0.0-1.0

class ExtractedFact(BaseModel):
    subject: str
    predicate: str
    obj: str
    confidence: float
    source_quote: str

class TaskDecomposition(BaseModel):
    sub_tasks: list[str]
    estimated_complexity: str   # "simple" | "moderate" | "complex"
    requires_tools: list[str]
```

**Integration:**
- `SkillSynthesizer.synthesize_skill()` → use `StructuredReasoner.reason_structured(schema=GeneratedSkill)` replacing the raw LLM call + regex code extraction
- `ExperienceDistiller.distill()` → use `StructuredReasoner.extract(schema=ExtractedFact)` for fact extraction from episodes
- `ReflectiveReasoner` task decomposition → use `StructuredReasoner.extract(schema=TaskDecomposition)`

---

### 3.11 A2A Federation Protocol

**File:** `neuralclaw/swarm/federation.py` — extend `FederationProtocol`.

**Purpose:** Make NeuralClaw nodes speak Google's Agent-to-Agent (A2A) protocol so
they can interoperate with any A2A-compliant agent (LangGraph, Vertex AI agents,
CrewAI, etc.).

**A2A envelope wrapper** (add alongside existing `FederationMessage`):
```python
@dataclass
class A2AMessage:
    jsonrpc: str = "2.0"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    method: str = ""
    # methods: "message/send", "message/stream", "tasks/get",
    #          "tasks/cancel", "agent/authenticatedExtendedCard"
    params: dict = field(default_factory=dict)

@dataclass
class A2APart:
    kind: str       # "text" | "data" | "file"
    text: str = ""
    data: dict = field(default_factory=dict)

@dataclass
class A2AMessage:
    message_id: str
    role: str       # "user" | "agent"
    parts: list[A2APart]
    context_id: str = ""
    task_id: str = ""
```

**New HTTP endpoints on `FederationProtocol`:**
```
POST /.well-known/agent.json          # agent card discovery
POST /a2a                             # A2A JSON-RPC endpoint
GET  /a2a/tasks/{task_id}             # task status polling
```

**Agent card** (`.well-known/agent.json`):
```json
{
  "name": "<config.name>",
  "description": "<config.persona>",
  "url": "http://<bind_host>:<port>",
  "version": "<neuralclaw.__version__>",
  "capabilities": {
    "streaming": true,
    "pushNotifications": false,
    "stateTransitionHistory": true
  },
  "skills": [ ... from SkillRegistry ... ]
}
```

**Backward compatibility:** existing `/federation/*` endpoints remain unchanged.
A2A is additive. Controlled by `federation.a2a_enabled = false`.

**Config additions to `[federation]`:**
```toml
a2a_enabled       = false     # expose A2A protocol endpoints
a2a_auth_required = true      # require bearer token for A2A inbound
a2a_token         = ""        # bearer token (stored in keychain as "a2a_token")
```

---

### 3.12 Traceline Observability

**File:** `neuralclaw/cortex/observability/traceline.py`

**Purpose:** Record the full reasoning trace for every request — every step from
intake to response — in a queryable, exportable format. The Neural Bus already emits
all the right events. Traceline subscribes to the bus and assembles them into traces.

**Data model:**
```python
@dataclass
class ToolCallTrace:
    tool: str
    args_preview: str     # first 200 chars of args, secrets redacted
    result_preview: str   # first 200 chars of result
    duration_ms: float
    success: bool
    idempotency_key: str = ""

@dataclass
class ReasoningTrace:
    trace_id: str
    request_id: str
    user_id: str
    channel: str
    platform: str
    input_preview: str          # first 500 chars
    output_preview: str         # first 500 chars
    confidence: float
    reasoning_path: str         # "fast_path" | "deliberative" | "reflective"
    threat_score: float
    memory_hits: int
    tool_calls: list[ToolCallTrace]
    total_tool_calls: int
    tokens_used: int
    cost_usd: float
    duration_ms: float
    timestamp: float
    error: str = ""
    tags: list[str] = field(default_factory=list)
```

**Class interface:**
```python
class Traceline:
    def __init__(self, db_path: str, bus: NeuralBus,
                 export_otlp: bool = False,
                 otlp_endpoint: str = "") -> None: ...

    async def initialize(self) -> None: ...
    # Creates traces table in SQLite

    # Called automatically via bus subscriptions:
    async def _on_signal_received(self, event: dict) -> None: ...
    async def _on_reasoning_complete(self, event: dict) -> None: ...
    async def _on_action_complete(self, event: dict) -> None: ...
    async def _on_response_ready(self, event: dict) -> None: ...

    # Query API:
    async def get_trace(self, trace_id: str) -> ReasoningTrace | None: ...
    async def query_traces(
        self,
        user_id: str | None = None,
        channel: str | None = None,
        tool: str | None = None,
        since: float | None = None,
        until: float | None = None,
        min_confidence: float | None = None,
        limit: int = 50,
    ) -> list[ReasoningTrace]: ...

    async def export_jsonl(self, path: str,
                            since: float | None = None) -> int: ...
    # Returns number of traces exported

    async def get_metrics(self) -> dict: ...
    # Returns: total_traces, avg_confidence, avg_duration_ms, tool_usage_breakdown,
    #          reasoning_path_distribution, error_rate, cost_last_7d

    async def prune(self, keep_days: int = 30) -> int: ...
    # Delete traces older than keep_days, return count deleted
```

**CLI command:** Add `neuralclaw traces` command group:
```
neuralclaw traces list [--user USER] [--since 7d] [--tool TOOL]
neuralclaw traces show <trace_id>
neuralclaw traces metrics
neuralclaw traces export --format jsonl --output traces.jsonl
neuralclaw traces prune --keep-days 30
```

**Dashboard integration:** Add a "Traces" panel to the web dashboard that shows
the last 50 traces with filtering. Data served via new WebSocket event type
`TRACE_RECORDED`.

**Config section `[traceline]`:**
```toml
[traceline]
enabled           = true
db_path           = ""          # defaults to ~/.neuralclaw/data/traces.db
retention_days    = 30
export_otlp       = false       # export to OpenTelemetry collector
otlp_endpoint     = ""          # e.g. "http://localhost:4317"
export_prometheus = false       # expose /metrics endpoint
metrics_port      = 9090
include_input     = true        # store input previews (disable for privacy)
include_output    = true        # store output previews
max_preview_chars = 500
```

---

### 3.13 Prompt Armor v2

**File:** `neuralclaw/cortex/perception/output_filter.py`

**Purpose:** Screen LLM responses *before* they reach the user. The existing
`ThreatScreener` protects inputs. This protects outputs. Also adds three new
input-side detection patterns to the existing `ThreatScreener`.

**`OutputThreatFilter` class:**
```python
class OutputThreatFilter:
    def __init__(self, bus: NeuralBus | None = None,
                 config: SecurityConfig | None = None) -> None: ...

    async def screen(self, response: str,
                      original_signal: Signal) -> OutputFilterResult: ...
```

```python
@dataclass
class OutputFilterResult:
    safe: bool
    response: str           # original or sanitized response
    flags: list[str]        # what was detected
    action: str             # "pass" | "sanitize" | "block"
```

**Detections to implement:**
- **System prompt leakage:** response contains verbatim text from system prompt
  (detected via Jaccard similarity with known system prompt fragments)
- **PII in output:** phone numbers, email addresses, SSNs in responses when the
  input didn't contain them (agent hallucinating or leaking PII)
- **Hallucinated tool calls:** response text that looks like a tool call JSON block
  outside the LLM's structured output (prompt injection via tool result)
- **Jailbreak confirmation:** response starts with "Sure, here's how to..."
  followed by flagged content categories
- **Excessive refusal:** response is a refusal on a safe request — flag for
  calibration feedback (not a security issue but a quality signal)

**New input-side patterns** to add to `ThreatScreener._INJECTION_PATTERNS`:
```python
# Multi-turn escalation
(re.compile(r"(as we (discussed|agreed|established))[^\n]{0,50}(ignore|bypass|override)", re.I), 0.80, "multi_turn_escalation"),
# Semantic intent disguise (base64 in instructions)
(re.compile(r"(base64|decode|eval|exec)\s*[\(\[{]", re.I), 0.75, "obfuscated_instruction"),
# Canary leak detection — inserted by the system, detected if echoed back
# (canary string is set at gateway init and injected invisibly into system prompt)
```

**Canary token system:**
- Gateway generates a random 12-char hex canary on startup: `CANARY_<hex>`
- Inject invisibly into system prompt: `<!-- CANARY_<hex> -->`
- `OutputThreatFilter` checks every response for the canary string
- If detected: log high-severity security event, return sanitized response

**Config additions to `[security]`:**
```toml
output_filtering         = true    # screen LLM responses before delivery
output_pii_detection     = true    # flag PII in responses
output_prompt_leak_check = true    # detect system prompt leakage
canary_tokens            = true    # inject invisible canary to detect leakage
pii_patterns             = []      # additional regex patterns for PII detection
```

---

### 3.14 Audit Forensic Replay

**File:** Extend `neuralclaw/cortex/action/audit.py` + new CLI commands.

**Current state:** `AuditLogger` writes action records to a JSONL file and keeps
200 in-memory. Each record has: timestamp, request_id, skill, args_preview,
result_preview, allowed, denied_reason.

**Additions:**

**1. Cross-reference with Traceline:** Link audit records to `ReasoningTrace` via
`request_id`. `audit.get_trace_actions(request_id)` returns all actions in a trace.

**2. `AuditSearchIndex`** — build an in-memory index on startup from the JSONL file:
```python
async def search(
    self,
    tool: str | None = None,
    user_id: str | None = None,
    since: float | None = None,
    until: float | None = None,
    denied_only: bool = False,
    limit: int = 100,
) -> list[AuditRecord]: ...
```

**3. CLI commands** — add `neuralclaw audit` command group:
```
neuralclaw audit list [--tool web_search] [--since 7d] [--denied]
neuralclaw audit show <request_id>     # full action sequence for a request
neuralclaw audit export [--format jsonl|csv] [--since 7d]
neuralclaw audit stats                  # denial rate, top tools, top users
```

**4. SIEM export:** `export --format cef` produces Common Event Format output
for enterprise SIEM integration (Splunk, QRadar, Sentinel).

**Config additions to `[audit]`:**
```toml
[audit]
enabled          = true
jsonl_path       = ""        # defaults to ~/.neuralclaw/logs/audit.jsonl
max_memory_entries = 200
retention_days   = 90
siem_export      = false     # enable CEF format export
include_args     = true      # store sanitized args (disable for strict privacy)
```

---

### 3.15 Desktop Control Skill

**File:** `neuralclaw/cortex/action/desktop.py`

**Purpose:** Allow the agent to control the host desktop — take screenshots, click,
type, and interact with applications. The "Devin but yours" capability. Combined with
browser cortex and code execution, the agent can perform full computer tasks.

**Disabled by default. Requires explicit `features.desktop = true` + user
confirmation during `neuralclaw init`.**

**Backend:** `mss` (fast cross-platform screenshots) + `pyautogui` (keyboard/mouse).

**Class interface:**
```python
class DesktopCortex:
    async def screenshot(self, monitor: int = 0) -> dict: ...
    # Returns {"screenshot_b64": "...", "width": int, "height": int}

    async def click(self, x: int, y: int, button: str = "left",
                     clicks: int = 1) -> dict: ...

    async def type_text(self, text: str, interval: float = 0.05) -> dict: ...
    async def hotkey(self, *keys: str) -> dict: ...
    # e.g. hotkey("ctrl", "c")

    async def find_window(self, title: str) -> dict: ...
    async def focus_window(self, title: str) -> dict: ...

    async def get_clipboard(self) -> dict: ...
    async def set_clipboard(self, text: str) -> dict: ...

    async def run_app(self, app: str, args: list[str] | None = None) -> dict: ...
    # Limited to apps in policy.desktop_allowed_apps

    async def locate_on_screen(self, description: str,
                                 vision: "VisionPerception") -> dict | None: ...
    # Uses vision to find element by description, returns (x, y)
```

**Required new capability:** `DESKTOP_CONTROL = auto()` in `Capability` enum.

**Strict policy controls:**
- `policy.desktop_allowed_apps: list[str]` — allowlist of app names `run_app` can launch
- `policy.desktop_blocked_regions: list[str]` — screen regions the agent cannot interact with
- All desktop actions are audit-logged with screenshot evidence

**Config section `[desktop]`:**
```toml
[desktop]
enabled             = false    # must be explicitly enabled
screenshot_on_action = true    # capture before+after screenshot for every action
action_delay_ms     = 100      # delay between actions (safety)
```

**pyproject.toml extra:** `pip install neuralclaw[desktop]` pulls `mss`,
`pyautogui`, `pillow`.

---

## 4. Configuration System

### 4.1 Full config.toml Reference

This is the complete, documented `config.toml` that users see after `neuralclaw init`.
Every key is present with its default and a comment. This replaces the existing
generated config with a comprehensive, self-documenting version.

```toml
# ─────────────────────────────────────────────────────────────────────────────
# NeuralClaw Configuration
# ~/.neuralclaw/config.toml
#
# Keys marked [REQUIRED] must be set before the gateway starts.
# Keys marked [SECRET] are stored in OS keychain — set via `neuralclaw init`
#   or by running `neuralclaw config set-secret <key> <value>`.
# All other keys have safe defaults.
# ─────────────────────────────────────────────────────────────────────────────

[general]
name               = "NeuralClaw"
persona            = "You are NeuralClaw, a helpful and intelligent AI assistant."
log_level          = "INFO"       # DEBUG | INFO | WARNING | ERROR
telemetry_stdout   = true         # print reasoning traces to terminal


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE FLAGS
# Disable subsystems to reduce RAM and boot time (lite mode).
# Set all to false for a minimal single-chat deployment.
# ─────────────────────────────────────────────────────────────────────────────

[features]
# Core intelligence
vector_memory          = true     # semantic similarity memory (needs sqlite-vec)
semantic_memory        = true     # entity-relationship knowledge graph
procedural_memory      = true     # reusable workflow patterns
reflective_reasoning   = true     # multi-step planning (uses extra LLM calls)
evolution              = true     # self-improvement: calibrator, distiller, synthesizer

# I/O
streaming_responses    = false    # stream tokens to supported channels
vision                 = false    # process images from channels (needs multimodal LLM)
voice                  = false    # TTS + Discord voice channel support
browser                = false    # Playwright browser automation
desktop                = false    # Desktop control — USE WITH CAUTION

# Infrastructure
swarm                  = true     # agent mesh, delegation, consensus
dashboard              = true     # web monitoring dashboard
identity               = true     # persistent per-user mental model
traceline              = true     # full reasoning trace observability
a2a_federation         = false    # A2A protocol interoperability

# Streaming settings (when streaming_responses = true)
streaming_edit_interval = 20      # Discord: tokens between message edits


# ─────────────────────────────────────────────────────────────────────────────
# LLM PROVIDERS
# Set API keys via: neuralclaw init  [SECRET]
# ─────────────────────────────────────────────────────────────────────────────

[providers]
primary  = "openai"               # primary provider name
fallback = ["openrouter", "local"] # ordered fallback chain

[providers.openai]
model    = "gpt-4o"
base_url = "https://api.openai.com/v1"
# API key stored in keychain: neuralclaw init

[providers.anthropic]
model    = "claude-sonnet-4-20250514"
base_url = "https://api.anthropic.com"

[providers.openrouter]
model    = "anthropic/claude-sonnet-4-20250514"
base_url = "https://openrouter.ai/api/v1"

[providers.local]
model    = "qwen3.5:2b"           # any Ollama model
base_url = "http://localhost:11434/v1"

[providers.proxy]
model    = "gpt-4"
base_url = ""                     # [REQUIRED if using proxy provider]

[providers.chatgpt_token]
model       = "auto"
auth_method = "cookie"
profile_dir = "~/.neuralclaw/sessions/chatgpt"

[providers.claude_token]
model       = "auto"
auth_method = "session_key"
profile_dir = "~/.neuralclaw/sessions/claude"


# ─────────────────────────────────────────────────────────────────────────────
# MEMORY
# ─────────────────────────────────────────────────────────────────────────────

[memory]
db_path                = "~/.neuralclaw/data/memory.db"
max_episodic_results   = 10       # max episodes returned per retrieval
max_semantic_results   = 5        # max knowledge triples per retrieval
importance_threshold   = 0.3      # min importance score to store an episode

# Vector memory (features.vector_memory must be true)
vector_memory           = true
embedding_provider      = "local"             # "local" (Ollama) | "openai"
embedding_model         = "nomic-embed-text"  # or "text-embedding-3-small"
embedding_dimension     = 768                 # 768 nomic | 1536 openai
vector_similarity_top_k = 10


# ─────────────────────────────────────────────────────────────────────────────
# IDENTITY  (features.identity must be true)
# ─────────────────────────────────────────────────────────────────────────────

[identity]
enabled           = true
cross_channel     = true   # link same user across Telegram/Discord/Slack
inject_in_prompt  = true   # add user context section to every LLM prompt
notes_enabled     = true   # agent can write structured notes about users


# ─────────────────────────────────────────────────────────────────────────────
# SECURITY
# ─────────────────────────────────────────────────────────────────────────────

[security]
threat_threshold           = 0.7    # score above this is flagged
block_threshold            = 0.9    # score above this is blocked outright
threat_verifier_model      = ""     # secondary model for borderline cases (empty = off)
threat_borderline_low      = 0.35
threat_borderline_high     = 0.65
max_content_chars          = 8000   # truncate inputs longer than this
max_skill_timeout_seconds  = 30
allow_shell_execution      = false  # master shell kill switch

# Prompt Armor v2 output filtering (features must include output_filter)
output_filtering           = true   # screen LLM responses before delivery
output_pii_detection       = true   # detect PII leakage in responses
output_prompt_leak_check   = true   # detect system prompt echoing
canary_tokens              = true   # invisible canary injection + leak detection
pii_patterns               = []     # additional regex PII patterns


# ─────────────────────────────────────────────────────────────────────────────
# POLICY
# ─────────────────────────────────────────────────────────────────────────────

[policy]
max_tool_calls_per_request  = 10
max_request_wall_seconds    = 120.0
parallel_tool_execution     = true   # execute independent tool calls concurrently

# Tool allowlist — any tool NOT in this list is denied.
# Add tools here as you enable new skills.
allowed_tools = [
    # Core
    "web_search", "fetch_url",
    "read_file", "write_file", "list_directory",
    "execute_python",
    "create_event", "list_events", "delete_event",
    # GitHub
    "clone_repo", "install_repo_deps", "list_repos", "remove_repo",
    "run_repo_script", "run_repo_command",
    # API client
    "api_request", "save_api_config", "list_api_configs",
    # TTS (add when [tts] enabled = true)
    # "speak", "list_voices", "speak_and_play",
    # Google Workspace (add when [google_workspace] enabled = true)
    # "gmail_search", "gmail_send", "gmail_get", "gmail_label", "gmail_draft",
    # "gcal_list_events", "gcal_create_event", "gcal_update_event", "gcal_delete_event",
    # "gdrive_search", "gdrive_read", "gdrive_upload",
    # "gdocs_read", "gdocs_append", "gsheets_read", "gsheets_write", "gmeet_create",
    # Microsoft 365 (add when [microsoft365] enabled = true)
    # "outlook_search", "outlook_send", "outlook_get",
    # "ms_cal_list", "ms_cal_create", "ms_cal_delete",
    # "teams_send", "teams_list_channels",
    # "onedrive_search", "onedrive_read", "onedrive_upload",
    # "sharepoint_search", "sharepoint_read",
    # Browser (add when [browser] enabled = true)
    # "browser_navigate", "browser_screenshot", "browser_click", "browser_type",
    # "browser_scroll", "browser_extract", "browser_act",
    # "chrome_summarize", "chrome_translate",
    # Desktop (add when [desktop] enabled = true — HIGH RISK)
    # "desktop_screenshot", "desktop_click", "desktop_type", "desktop_hotkey",
    # "desktop_find_window", "desktop_get_clipboard", "desktop_set_clipboard",
]

mutating_tools = [
    "write_file", "create_event", "delete_event",
    "clone_repo", "install_repo_deps", "remove_repo",
    "save_api_config", "gmail_send", "gmail_draft",
    "gcal_create_event", "gcal_update_event", "gcal_delete_event",
    "gdrive_upload", "gdocs_append", "gsheets_write",
    "outlook_send", "ms_cal_create", "ms_cal_delete",
    "teams_send", "onedrive_upload",
]

allowed_filesystem_roots = [
    "~/workspace",
    "~/.neuralclaw/workspace/repos",
]

deny_private_networks     = true
deny_shell_execution      = true
desktop_allowed_apps      = []     # apps desktop skill can launch (empty = none)


# ─────────────────────────────────────────────────────────────────────────────
# CHANNELS
# Tokens stored in keychain: neuralclaw channels setup
# ─────────────────────────────────────────────────────────────────────────────

[channels.telegram]
enabled    = false
trust_mode = "open"    # "open" | "pair" | "bound"

[channels.discord]
enabled                  = false
trust_mode               = "open"
voice_responses          = false   # TTS audio in voice channel (needs [tts])
auto_disconnect_empty_vc = true
voice_channel_id         = ""      # default voice channel ID (optional)

[channels.slack]
enabled    = false
trust_mode = "open"

[channels.whatsapp]
enabled    = false
trust_mode = "pair"

[channels.signal]
enabled    = false
trust_mode = "pair"


# ─────────────────────────────────────────────────────────────────────────────
# TTS — Text-to-Speech  (features.voice must be true)
# ─────────────────────────────────────────────────────────────────────────────

[tts]
enabled         = false
provider        = "edge-tts"          # "edge-tts" | "openai" | "elevenlabs" | "piper"
voice           = "en-US-AriaNeural"  # provider-specific voice name
speed           = 1.0
output_format   = "mp3"
auto_speak      = false               # auto-TTS all responses in voice channels
max_tts_chars   = 2000
temp_dir        = ""
piper_binary    = "piper"
piper_model     = ""


# ─────────────────────────────────────────────────────────────────────────────
# BROWSER CORTEX  (features.browser must be true)
# Run: pip install "neuralclaw[browser]" && playwright install chromium
# ─────────────────────────────────────────────────────────────────────────────

[browser]
enabled               = false
headless              = true
browser_type          = "chromium"     # "chromium" | "firefox" | "webkit"
viewport_width        = 1280
viewport_height       = 900
stealth               = true
allow_js_execution    = false          # HIGH RISK — enables browser_execute_js tool
max_steps_per_task    = 20
screenshot_on_error   = true
chrome_ai_enabled     = false          # requires Chrome (not Chromium)
navigation_timeout    = 30
user_data_dir         = ""             # set to persist browser sessions/cookies
allowed_domains       = []             # empty = all domains allowed
blocked_domains       = [
    "localhost", "127.0.0.1", "0.0.0.0",
    "169.254.169.254", "metadata.google.internal",
]


# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE WORKSPACE  (requires: pip install "neuralclaw[google]")
# Setup: neuralclaw session auth google
# ─────────────────────────────────────────────────────────────────────────────

[google_workspace]
enabled              = false
scopes               = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]
max_email_results    = 10
max_drive_results    = 10
default_calendar_id  = "primary"
response_body_limit  = 20000


# ─────────────────────────────────────────────────────────────────────────────
# MICROSOFT 365  (requires: pip install "neuralclaw[microsoft]")
# Setup: neuralclaw session auth microsoft
# ─────────────────────────────────────────────────────────────────────────────

[microsoft365]
enabled           = false
tenant_id         = ""      # Azure tenant ID or "common" for personal accounts
scopes            = [
    "Mail.ReadWrite", "Calendars.ReadWrite",
    "Files.ReadWrite", "Chat.ReadWrite", "ChannelMessage.Send",
]
max_email_results = 10
max_file_results  = 10
default_user      = "me"


# ─────────────────────────────────────────────────────────────────────────────
# DESKTOP CONTROL  (features.desktop must be true)
# Run: pip install "neuralclaw[desktop]"
# WARNING: grants the agent control of your screen and keyboard.
# ─────────────────────────────────────────────────────────────────────────────

[desktop]
enabled              = false
screenshot_on_action = true
action_delay_ms      = 100


# ─────────────────────────────────────────────────────────────────────────────
# TRACELINE OBSERVABILITY  (features.traceline must be true)
# ─────────────────────────────────────────────────────────────────────────────

[traceline]
enabled           = true
db_path           = ""          # defaults to ~/.neuralclaw/data/traces.db
retention_days    = 30
export_otlp       = false       # OpenTelemetry OTLP export
otlp_endpoint     = ""          # e.g. "http://localhost:4317"
export_prometheus = false       # Prometheus /metrics endpoint
metrics_port      = 9090
include_input     = true        # store input previews
include_output    = true        # store output previews
max_preview_chars = 500


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT LOG
# ─────────────────────────────────────────────────────────────────────────────

[audit]
enabled             = true
jsonl_path          = ""        # defaults to ~/.neuralclaw/logs/audit.jsonl
max_memory_entries  = 200
retention_days      = 90
siem_export         = false     # enable CEF format for SIEM integration
include_args        = true      # store sanitized args


# ─────────────────────────────────────────────────────────────────────────────
# FEDERATION
# ─────────────────────────────────────────────────────────────────────────────

[federation]
enabled              = true
port                 = 8100
bind_host            = "127.0.0.1"   # change to "0.0.0.0" only for multi-machine
seed_nodes           = []
heartbeat_interval   = 60
node_name            = ""            # defaults to [general] name
a2a_enabled          = false         # A2A protocol interoperability
a2a_auth_required    = true
# a2a_token stored in keychain


# ─────────────────────────────────────────────────────────────────────────────
# WORKSPACE
# ─────────────────────────────────────────────────────────────────────────────

[workspace]
repos_dir                  = "~/.neuralclaw/workspace/repos"
max_repo_size_mb           = 500
allowed_git_hosts          = ["github.com", "gitlab.com", "bitbucket.org"]
max_clone_timeout_seconds  = 120
max_install_timeout_seconds = 300
max_exec_timeout_seconds   = 300


# ─────────────────────────────────────────────────────────────────────────────
# SAVED API CONFIGS
# Set via: neuralclaw config add-api <name> <base_url> <auth_type>
# API keys stored in keychain.
# ─────────────────────────────────────────────────────────────────────────────

# Example:
# [apis.stripe]
# base_url  = "https://api.stripe.com/v1"
# auth_type = "bearer"
```

---

### 4.2 Config Dataclass Changes

Add these dataclasses to `config.py`. All follow the existing `@dataclass` pattern
and are loaded with `_filter_fields()` protection:

```python
@dataclass
class VoiceConfig:
    enabled: bool = False
    provider: str = "edge-tts"
    voice: str = "en-US-AriaNeural"
    speed: float = 1.0
    output_format: str = "mp3"
    auto_speak: bool = False
    max_tts_chars: int = 2000
    temp_dir: str = ""
    piper_binary: str = "piper"
    piper_model: str = ""

@dataclass
class BrowserConfig:
    enabled: bool = False
    headless: bool = True
    browser_type: str = "chromium"
    viewport_width: int = 1280
    viewport_height: int = 900
    stealth: bool = True
    allow_js_execution: bool = False
    max_steps_per_task: int = 20
    screenshot_on_error: bool = True
    chrome_ai_enabled: bool = False
    navigation_timeout: int = 30
    user_data_dir: str = ""
    allowed_domains: list[str] = field(default_factory=list)
    blocked_domains: list[str] = field(default_factory=lambda: [
        "localhost", "127.0.0.1", "0.0.0.0",
        "169.254.169.254", "metadata.google.internal",
    ])

@dataclass
class GoogleWorkspaceConfig:
    enabled: bool = False
    scopes: list[str] = field(default_factory=list)
    max_email_results: int = 10
    max_drive_results: int = 10
    default_calendar_id: str = "primary"
    response_body_limit: int = 20000

@dataclass
class Microsoft365Config:
    enabled: bool = False
    tenant_id: str = ""
    scopes: list[str] = field(default_factory=list)
    max_email_results: int = 10
    max_file_results: int = 10
    default_user: str = "me"

@dataclass
class DesktopConfig:
    enabled: bool = False
    screenshot_on_action: bool = True
    action_delay_ms: int = 100

@dataclass
class TracelineConfig:
    enabled: bool = True
    db_path: str = ""
    retention_days: int = 30
    export_otlp: bool = False
    otlp_endpoint: str = ""
    export_prometheus: bool = False
    metrics_port: int = 9090
    include_input: bool = True
    include_output: bool = True
    max_preview_chars: int = 500

@dataclass
class IdentityConfig:
    enabled: bool = True
    cross_channel: bool = True
    inject_in_prompt: bool = True
    notes_enabled: bool = True
```

**Extend `FeaturesConfig`** with the new flags:
```python
@dataclass
class FeaturesConfig:
    # existing fields...
    swarm: bool = True
    dashboard: bool = True
    evolution: bool = True
    reflective_reasoning: bool = True
    procedural_memory: bool = True
    semantic_memory: bool = True
    # new fields:
    vector_memory: bool = True
    streaming_responses: bool = False
    streaming_edit_interval: int = 20
    vision: bool = False
    voice: bool = False
    browser: bool = False
    desktop: bool = False
    identity: bool = True
    traceline: bool = True
    a2a_federation: bool = False
```

**Extend `NeuralClawConfig`** with new sections:
```python
@dataclass
class NeuralClawConfig:
    # existing fields...
    tts: VoiceConfig = field(default_factory=VoiceConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    google_workspace: GoogleWorkspaceConfig = field(default_factory=GoogleWorkspaceConfig)
    microsoft365: Microsoft365Config = field(default_factory=Microsoft365Config)
    desktop: DesktopConfig = field(default_factory=DesktopConfig)
    traceline: TracelineConfig = field(default_factory=TracelineConfig)
    identity: IdentityConfig = field(default_factory=IdentityConfig)
```

---

### 4.3 DEFAULT_CONFIG Changes

Add the following sections to `DEFAULT_CONFIG` in `config.py` so new installs get
safe defaults written to `config.toml`:

```python
"tts":    {"enabled": False, "provider": "edge-tts", "voice": "en-US-AriaNeural", ...},
"browser": {"enabled": False, "headless": True, ...},
"google_workspace": {"enabled": False},
"microsoft365": {"enabled": False},
"desktop": {"enabled": False},
"traceline": {"enabled": True, "retention_days": 30, ...},
"identity": {"enabled": True, "cross_channel": True, ...},
```

Also extend `"features"` in `DEFAULT_CONFIG` with all new flags (all defaulting
to `false` except `vector_memory`, `identity`, and `traceline` which default to `true`).

---

### 4.4 Feature Flag Reference

Quick-reference table for operators tuning their deployment:

| Flag | Default | Effect when true | Dependencies |
|---|---|---|---|
| `vector_memory` | `true` | Semantic similarity search in memory | `sqlite-vec` |
| `semantic_memory` | `true` | Knowledge graph entity storage | none |
| `procedural_memory` | `true` | Workflow trigger pattern matching | none |
| `reflective_reasoning` | `true` | Multi-step planning (extra LLM calls) | none |
| `evolution` | `true` | Calibrator, distiller, synthesizer | none |
| `streaming_responses` | `false` | Token-by-token response delivery | multimodal provider |
| `vision` | `false` | Process images from channels | multimodal LLM |
| `voice` | `false` | TTS + Discord VC audio | `edge-tts` or OpenAI |
| `browser` | `false` | Playwright browser automation | `playwright`, Chromium |
| `desktop` | `false` | Screen + keyboard control | `pyautogui`, `mss` |
| `swarm` | `true` | Agent mesh, delegation, consensus | none |
| `dashboard` | `true` | Web monitoring UI | `aiohttp` |
| `identity` | `true` | Persistent user mental models | none |
| `traceline` | `true` | Full reasoning trace observability | none |
| `a2a_federation` | `false` | A2A protocol interoperability | none |

**Lite mode** (minimal deployment, e.g. Claw Club single-tenant):
```toml
[features]
vector_memory        = false
semantic_memory      = false
procedural_memory    = false
reflective_reasoning = false
evolution            = false
swarm                = false
dashboard            = false
identity             = false
traceline            = false
```

---

## 5. Capability Enum Additions

Add to `Capability(Enum)` in `neuralclaw/cortex/action/capabilities.py`:

```python
# Audio
AUDIO_OUTPUT    = auto()   # TTS output
VOICE_CHANNEL   = auto()   # Join/speak in voice channel

# Browser
BROWSER_CONTROL = auto()   # Playwright browser automation
BROWSER_JS      = auto()   # Execute JavaScript in browser (high risk)

# Desktop
DESKTOP_CONTROL = auto()   # Screenshot, click, keyboard control

# Google Workspace
GOOGLE_GMAIL    = auto()
GOOGLE_CALENDAR = auto()
GOOGLE_DRIVE    = auto()
GOOGLE_DOCS     = auto()
GOOGLE_SHEETS   = auto()

# Microsoft 365
MS_OUTLOOK      = auto()
MS_CALENDAR     = auto()
MS_TEAMS        = auto()
MS_ONEDRIVE     = auto()
MS_SHAREPOINT   = auto()
```

Add grants for new builtins in `CapabilityVerifier.__init__` `self._grants`:
```python
"tts": [CapabilityGrant(Capability.AUDIO_OUTPUT, scope="*")],
"google_workspace": [
    CapabilityGrant(Capability.GOOGLE_GMAIL, scope="*"),
    CapabilityGrant(Capability.GOOGLE_CALENDAR, scope="*"),
    CapabilityGrant(Capability.GOOGLE_DRIVE, scope="*"),
    CapabilityGrant(Capability.GOOGLE_DOCS, scope="*"),
    CapabilityGrant(Capability.GOOGLE_SHEETS, scope="*"),
    CapabilityGrant(Capability.NETWORK_HTTP, scope="googleapis.com"),
],
"microsoft365": [
    CapabilityGrant(Capability.MS_OUTLOOK, scope="*"),
    CapabilityGrant(Capability.MS_CALENDAR, scope="*"),
    CapabilityGrant(Capability.MS_TEAMS, scope="*"),
    CapabilityGrant(Capability.MS_ONEDRIVE, scope="*"),
    CapabilityGrant(Capability.MS_SHAREPOINT, scope="*"),
    CapabilityGrant(Capability.NETWORK_HTTP, scope="graph.microsoft.com"),
],
"browser": [
    CapabilityGrant(Capability.BROWSER_CONTROL, scope="*"),
    CapabilityGrant(Capability.NETWORK_HTTP, scope="*"),
],
"desktop": [
    CapabilityGrant(Capability.DESKTOP_CONTROL, scope="*"),
],
```

---

## 6. pyproject.toml Optional Extras

Replace the current `[project.optional-dependencies]` section:

```toml
[project.optional-dependencies]
# Channel extras
telegram      = ["python-telegram-bot>=21.0"]
discord       = ["discord.py>=2.3"]
slack         = ["slack-bolt>=1.18"]
all-channels  = ["python-telegram-bot>=21.0", "discord.py>=2.3", "slack-bolt>=1.18"]

# Voice / TTS
voice         = ["edge-tts>=6.1", "discord.py[voice]>=2.3", "ffmpeg-python>=0.2"]

# Browser automation
browser       = ["playwright>=1.52"]
# After install: playwright install chromium

# Vision / multimodal
# (no extra deps — uses existing OpenAI/Anthropic providers natively)
# For local vision: install Ollama and pull llava

# Vector memory
vector        = ["sqlite-vec>=0.1"]

# Google Workspace integration
google        = [
    "google-api-python-client>=2.100",
    "google-auth-oauthlib>=1.1",
    "google-auth-httplib2>=0.2",
]

# Microsoft 365 integration
microsoft     = ["msal>=1.26", "msgraph-sdk>=1.0"]

# Desktop control
desktop       = ["mss>=9.0", "pyautogui>=0.9", "pillow>=10.0"]

# Browser sessions (existing)
sessions      = ["playwright>=1.52"]

# Observability
observability = ["opentelemetry-sdk>=1.20", "opentelemetry-exporter-otlp>=1.20",
                  "prometheus-client>=0.18"]

# Everything
all = [
    "python-telegram-bot>=21.0", "discord.py[voice]>=2.3", "slack-bolt>=1.18",
    "edge-tts>=6.1", "ffmpeg-python>=0.2",
    "playwright>=1.52",
    "sqlite-vec>=0.1",
    "google-api-python-client>=2.100", "google-auth-oauthlib>=1.1",
    "google-auth-httplib2>=0.2",
    "msal>=1.26", "msgraph-sdk>=1.0",
    "mss>=9.0", "pyautogui>=0.9", "pillow>=10.0",
    "opentelemetry-sdk>=1.20", "opentelemetry-exporter-otlp>=1.20",
    "prometheus-client>=0.18",
]

# Development
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "ruff>=0.3"]
```

---

## 7. Policy Allowlist Additions

When a new skill's config section has `enabled = true`, the gateway must
auto-extend `policy.allowed_tools` with that skill's tools at runtime
(if the user hasn't already customized their allowlist). Add this logic
to `gateway.py` after config load:

```python
def _extend_policy_for_enabled_skills(config: NeuralClawConfig) -> None:
    """Auto-add tool names to allowed_tools when their skill is enabled."""
    additions: list[str] = []

    if config.tts.enabled:
        additions += ["speak", "list_voices", "speak_and_play"]
    if config.google_workspace.enabled:
        additions += ["gmail_search", "gmail_send", "gmail_get", "gmail_label",
                      "gmail_draft", "gcal_list_events", "gcal_create_event",
                      "gcal_update_event", "gcal_delete_event", "gdrive_search",
                      "gdrive_read", "gdrive_upload", "gdocs_read", "gdocs_append",
                      "gsheets_read", "gsheets_write", "gmeet_create"]
    if config.microsoft365.enabled:
        additions += ["outlook_search", "outlook_send", "outlook_get",
                      "ms_cal_list", "ms_cal_create", "ms_cal_delete",
                      "teams_send", "teams_list_channels", "onedrive_search",
                      "onedrive_read", "onedrive_upload", "sharepoint_search",
                      "sharepoint_read"]
    if config.browser.enabled:
        additions += ["browser_navigate", "browser_screenshot", "browser_click",
                      "browser_type", "browser_scroll", "browser_extract",
                      "browser_act", "chrome_summarize", "chrome_translate"]
        if config.browser.allow_js_execution:
            additions += ["browser_execute_js", "chrome_prompt"]
    if config.desktop.enabled:
        additions += ["desktop_screenshot", "desktop_click", "desktop_type",
                      "desktop_hotkey", "desktop_find_window",
                      "desktop_get_clipboard", "desktop_set_clipboard"]

    for tool in additions:
        if tool not in config.policy.allowed_tools:
            config.policy.allowed_tools.append(tool)
```

---

## 8. Testing Checklist

Every new module must ship with tests in `tests/`. Follow existing test patterns
(pytest-asyncio, `conftest.py` fixtures). Minimum coverage per feature:

| Feature | Test file | Minimum cases |
|---|---|---|
| Vector memory | `test_vector_memory.py` | embed+store, similarity_search returns ranked results, delete_by_ref, close |
| User identity | `test_identity.py` | get_or_create, update, merge_aliases, to_prompt_section |
| Browser cortex | `test_browser.py` | navigate, screenshot, click, extract, blocked_domain rejected |
| Vision perception | `test_vision.py` | describe, extract_text, locate_element |
| TTS skill | `test_tts.py` | speak returns audio_path, list_voices, max_tts_chars truncation |
| Google Workspace | `test_google_workspace.py` | manifest loads, SSRF validation on URLs, auth error handled |
| Microsoft 365 | `test_microsoft365.py` | manifest loads, SSRF validation, auth error handled |
| Parallel tools | `test_parallel_tools.py` | two tools execute concurrently, exceptions don't kill other tools |
| Streaming | `test_streaming.py` | send_stream default fallback, Discord override |
| Structured output | `test_structured.py` | valid schema passes, invalid retries, fails after max_retries |
| A2A federation | `test_a2a.py` | agent card valid JSON, message/send roundtrip, TTL enforcement |
| Traceline | `test_traceline.py` | trace recorded on bus events, query returns filtered results, export_jsonl |
| Prompt Armor v2 | `test_output_filter.py` | PII detection, canary leak detection, jailbreak confirmation, clean response passes |
| Audit replay | `test_audit_replay.py` | search by tool, search by user, export jsonl |
| Desktop control | `test_desktop.py` | screenshot returns b64, blocked when disabled |

---

## 9. Architectural Rules

These rules apply to all code in this repository. Never violate them.

1. **No silent failures.** Every `except` block either re-raises, publishes
   `EventType.ERROR` to the bus, or returns a `{"error": "..."}` dict.
   Empty `except: pass` blocks are forbidden in new code.

2. **No synchronous blocking in async context.** All I/O (file, network, DB,
   subprocess) must use async equivalents. Use `asyncio.to_thread()` only as
   a last resort for libraries that offer no async API.

3. **All secrets in keychain.** No API key, token, OAuth credential, or
   password may appear in `config.toml`, logs, or audit records. Use
   `_get_secret()` / `_set_secret()`. Redact with `redact_secrets()` before
   logging.

4. **Feature flags are respected everywhere.** Every new subsystem checks
   its feature flag in `gateway.py` before instantiation. Disabled features
   must have zero memory footprint — no objects created, no imports run.

5. **SSRF protection is non-negotiable.** Every outbound HTTP call in any
   skill or cortex must pass through `validate_url_with_dns()` before
   executing. No exceptions. No "this URL is safe, I'll skip validation."

6. **Skill handlers return dicts, never raise.** Handler functions registered
   as tool definitions must catch all exceptions and return
   `{"error": str(e)}`. The deliberative reasoner feeds tool results back to
   the LLM — an unhandled exception breaks the tool loop.

7. **One `get_manifest()` per builtin skill file.** The `load_builtins()`
   auto-discovery relies on this. If a file doesn't export `get_manifest`,
   it won't be loaded.

8. **Config changes are backward-compatible.** New keys added to config
   dataclasses must have defaults. `_filter_fields()` already strips unknown
   keys, so new keys added to `DEFAULT_CONFIG` won't crash existing
   `config.toml` files.

9. **Neural Bus events are the integration contract.** Subsystems must not
   call each other's methods directly outside of their initialization wiring
   in `gateway.py`. Cross-cortex communication goes through the bus.

10. **Tests ship with the feature.** A feature without tests is not done.
    PRs that add new modules without corresponding test files will not be
    merged.
