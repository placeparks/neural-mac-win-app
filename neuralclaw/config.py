"""
NeuralClaw Configuration — TOML-based config with OS keychain secrets.

Loads from ~/.neuralclaw/config.toml. Secrets (API keys, tokens) are stored
in the OS keychain via the `keyring` library, never in plaintext on disk.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import toml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP_NAME = "neuralclaw"
CONFIG_DIR = Path.home() / f".{APP_NAME}"
CONFIG_FILE = CONFIG_DIR / "config.toml"
DATA_DIR = CONFIG_DIR / "data"
LOG_DIR = CONFIG_DIR / "logs"
SESSION_DIR = CONFIG_DIR / "sessions"
MEMORY_DB = DATA_DIR / "memory.db"
TRACES_DB = DATA_DIR / "traces.db"
AUDIT_LOG = LOG_DIR / "audit.jsonl"
CHANNEL_BINDINGS_FILE = DATA_DIR / "channel_bindings.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "general": {
        "name": "NeuralClaw",
        "persona": "You are NeuralClaw, a self-evolving cognitive AI agent with persistent memory and tool use capabilities.",
        "log_level": "INFO",
        "telemetry_stdout": True,
    },
    # Feature flags — disable to run in lite mode (lower RAM, faster boot)
    "features": {
        "vector_memory": True,   # Semantic similarity search for episodic memory
        "identity": True,        # Persistent per-user mental model
        "vision": False,         # Multimodal image perception
        "voice": False,          # TTS output and Discord voice responses
        "browser": False,        # Stateful browser automation
        "structured_output": True,  # Pydantic-enforced structured reasoning
        "streaming_responses": False,  # Stream responses to supported channels
        "streaming_edit_interval": 20,
        "traceline": True,      # Full reasoning trace observability
        "desktop": False,       # Local desktop control (high risk, explicit opt-in)
        "swarm": True,           # Agent mesh, delegation, consensus
        "dashboard": True,       # Web dashboard on port 7474
        "evolution": True,       # Behavioral calibrator, distiller, synthesizer
        "reflective_reasoning": True,  # Multi-step planning (uses extra LLM calls)
        "procedural_memory": True,     # Trigger-pattern procedure matching
        "semantic_memory": True,       # Knowledge graph
        "a2a_federation": False,       # Agent-to-Agent protocol endpoints
    },
    "providers": {
        "primary": "openai",
        "fallback": ["openrouter", "local"],
        "openai": {
            "model": "gpt-5.4",
            "base_url": "https://api.openai.com/v1",
        },
        "anthropic": {
            "model": "claude-sonnet-4-6",
            "base_url": "https://api.anthropic.com",
        },
        "openrouter": {
            "model": "anthropic/claude-sonnet-4-6",
            "base_url": "https://openrouter.ai/api/v1",
        },
        "local": {
            "model": "qwen3:8b",
            "base_url": "http://localhost:11434/v1",
        },
        "proxy": {
            "model": "gpt-5.4",
            "base_url": "",
        },
        "chatgpt_app": {
            "model": "auto",
            "profile_dir": str(SESSION_DIR / "chatgpt"),
            "headless": False,
            "browser_channel": "",
            "site_url": "https://chatgpt.com/",
        },
        "claude_app": {
            "model": "auto",
            "profile_dir": str(SESSION_DIR / "claude"),
            "headless": False,
            "browser_channel": "",
            "site_url": "https://claude.ai/chats",
        },
        "chatgpt_token": {
            "model": "auto",
            "auth_method": "cookie",
            "profile_dir": str(SESSION_DIR / "chatgpt"),
        },
        "claude_token": {
            "model": "auto",
            "auth_method": "session_key",
            "profile_dir": str(SESSION_DIR / "claude"),
        },
    },
    "memory": {
        "db_path": str(MEMORY_DB),
        "max_episodic_results": 10,
        "max_semantic_results": 5,
        "importance_threshold": 0.3,
        "vector_memory": True,
        "embedding_provider": "local",
        "embedding_model": "nomic-embed-text",
        "embedding_dimension": 768,
        "vector_similarity_top_k": 10,
    },
    "identity": {
        "enabled": True,
        "cross_channel": True,
        "inject_in_prompt": True,
        "notes_enabled": True,
    },
    "traceline": {
        "enabled": True,
        "db_path": str(TRACES_DB),
        "retention_days": 30,
        "export_otlp": False,
        "otlp_endpoint": "",
        "export_prometheus": False,
        "metrics_port": 9090,
        "include_input": True,
        "include_output": True,
        "max_preview_chars": 500,
    },
    "audit": {
        "enabled": True,
        "jsonl_path": str(AUDIT_LOG),
        "max_memory_entries": 200,
        "retention_days": 90,
        "siem_export": False,
        "include_args": True,
    },
    "desktop": {
        "enabled": False,
        "screenshot_on_action": True,
        "action_delay_ms": 100,
    },
    "tts": {
        "enabled": False,
        "provider": "edge-tts",
        "voice": "en-US-AriaNeural",
        "speed": 1.0,
        "output_format": "mp3",
        "piper_binary": "piper",
        "piper_model": "",
        "auto_speak": False,
        "max_tts_chars": 2000,
        "temp_dir": "",
    },
    "browser": {
        "enabled": False,
        "headless": True,
        "browser_type": "chromium",
        "viewport_width": 1280,
        "viewport_height": 900,
        "stealth": True,
        "allow_js_execution": False,
        "max_steps_per_task": 20,
        "screenshot_on_error": True,
        "chrome_ai_enabled": False,
        "navigation_timeout": 30,
        "user_data_dir": "",
        "allowed_domains": [],
        "blocked_domains": ["localhost", "127.0.0.1", "169.254.169.254"],
    },
    "google_workspace": {
        "enabled": False,
        "scopes": [
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/spreadsheets",
        ],
        "max_email_results": 10,
        "max_drive_results": 10,
        "default_calendar_id": "primary",
        "response_body_limit": 20000,
    },
    "microsoft365": {
        "enabled": False,
        "tenant_id": "",
        "scopes": [
            "Mail.ReadWrite",
            "Calendars.ReadWrite",
            "Files.ReadWrite",
            "Chat.ReadWrite",
            "ChannelMessage.Send",
        ],
        "max_email_results": 10,
        "max_file_results": 10,
        "default_user": "me",
    },
    "security": {
        "threat_threshold": 0.7,
        "block_threshold": 0.9,
        "threat_verifier_model": "",
        "threat_borderline_low": 0.35,
        "threat_borderline_high": 0.65,
        "max_content_chars": 8000,
        "max_skill_timeout_seconds": 30,
        "allow_shell_execution": False,
        "output_filtering": True,
        "output_pii_detection": True,
        "output_prompt_leak_check": True,
        "canary_tokens": True,
        "pii_patterns": [],
    },
    "policy": {
        "max_tool_calls_per_request": 10,
        "max_request_wall_seconds": 120.0,
        "allowed_tools": [
            # Built-in tools (safe defaults; unknown tools are denied)
            "web_search",
            "fetch_url",
            "read_file",
            "write_file",
            "list_directory",
            "execute_python",
            "create_event",
            "list_events",
            "delete_event",
            # GitHub repo management
            "clone_repo",
            "install_repo_deps",
            "list_repos",
            "remove_repo",
            # Repo execution
            "run_repo_script",
            "run_repo_command",
            # API client
            "api_request",
            "save_api_config",
            "list_api_configs",
        ],
        "mutating_tools": [
            "write_file",
            "create_event",
            "delete_event",
            "clone_repo",
            "install_repo_deps",
            "remove_repo",
            "save_api_config",
        ],
        "allowed_filesystem_roots": ["~/workspace", "~/.neuralclaw/workspace/repos"],
        "deny_private_networks": True,
        "deny_shell_execution": True,
        "parallel_tool_execution": True,
    },
    "federation": {
        "enabled": True,
        "port": 8100,
        "bind_host": "127.0.0.1",
        "seed_nodes": [],
        "heartbeat_interval": 60,
        "node_name": "",
        "a2a_enabled": False,
        "a2a_auth_required": True,
    },
    "workspace": {
        "repos_dir": "~/.neuralclaw/workspace/repos",
        "max_repo_size_mb": 500,
        "allowed_git_hosts": ["github.com", "gitlab.com", "bitbucket.org"],
        "max_clone_timeout_seconds": 120,
        "max_install_timeout_seconds": 300,
        "max_exec_timeout_seconds": 300,
    },
    "apis": {},  # User-saved API configs: [apis.myapi] = {base_url = "...", auth_type = "bearer"}
    "channels": {
        "telegram": {"enabled": False, "trust_mode": ""},
        "discord": {
            "enabled": False,
            "trust_mode": "",
            "voice_responses": False,
            "auto_disconnect_empty_vc": True,
            "voice_channel_id": "",
        },
        "slack": {"enabled": False, "trust_mode": ""},
        "whatsapp": {"enabled": False, "trust_mode": ""},
        "signal": {"enabled": False, "trust_mode": ""},
    },
}


# ---------------------------------------------------------------------------
# Keyring helpers
# ---------------------------------------------------------------------------

def _get_secret(key: str) -> str | None:
    """Retrieve a secret from OS keychain or local fallback."""
    # First try local secrets file
    secrets_file = CONFIG_DIR / ".secrets.toml"
    if secrets_file.exists():
        try:
            with open(secrets_file, "r", encoding="utf-8") as f:
                secrets = toml.load(f)
            if key in secrets:
                return secrets[key]
        except Exception:
            pass

    # Then try OS keychain
    try:
        import keyring as kr  # lazy import
        val = kr.get_password(APP_NAME, key)
        if val:
            return val
    except Exception:
        pass
        
    return None


def _set_secret(key: str, value: str) -> None:
    """Store a secret in OS keychain, or fallback to local file."""
    # 1. Try OS keychain
    keychain_worked = False
    try:
        import keyring as kr
        kr.set_password(APP_NAME, key, value)
        
        # Verify it actually saved (catches silent fail backends in headless Linux)
        if kr.get_password(APP_NAME, key) == value:
            keychain_worked = True
    except Exception:
        pass
        
    if keychain_worked:
        return

    # 2. Fallback to local secrets file
    try:
        secrets_file = CONFIG_DIR / ".secrets.toml"
        ensure_dirs()
        secrets = {}
        if secrets_file.exists():
            with open(secrets_file, "r", encoding="utf-8") as f:
                secrets = toml.load(f)
            
        secrets[key] = value
        
        with open(secrets_file, "w", encoding="utf-8") as f:
            toml.dump(secrets, f)
            
        try:
            secrets_file.chmod(0o600)  # Secure the file
        except Exception:
            pass
    except Exception as e:
        print(f"Failed to save secret locally: {e}")


def get_api_key(provider: str) -> str | None:
    """Get API key. Checks env vars first (fast, no I/O), then OS keychain."""
    env_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "chatgpt_token": "CHATGPT_TOKEN",
        "claude_token": "CLAUDE_SESSION_KEY",
    }
    # Fast path: env var — no keyring import needed
    env_var = env_map.get(provider)
    if env_var:
        val = os.environ.get(env_var)
        if val:
            return val
    # Generic NEURALCLAW_<PROVIDER>_API_KEY fallback
    generic = os.environ.get(f"NEURALCLAW_{provider.upper()}_API_KEY")
    if generic:
        return generic
    # Slow path: OS keychain (lazy import)
    return _get_secret(f"{provider}_api_key")


def set_api_key(provider: str, key: str) -> None:
    """Store API key in OS keychain."""
    _set_secret(f"{provider}_api_key", key)


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ProviderConfig:
    name: str
    model: str
    base_url: str
    api_key: str | None = None
    profile_dir: str = ""
    headless: bool = False
    browser_channel: str = ""
    site_url: str = ""
    auth_method: str = ""  # "oauth", "session_key", "cookie", or ""


@dataclass
class MemoryConfig:
    db_path: str = str(MEMORY_DB)
    max_episodic_results: int = 10
    max_semantic_results: int = 5
    importance_threshold: float = 0.3
    vector_memory: bool = True
    embedding_provider: str = "local"
    embedding_model: str = "nomic-embed-text"
    embedding_dimension: int = 768
    vector_similarity_top_k: int = 10


@dataclass
class SecurityConfig:
    threat_threshold: float = 0.7
    block_threshold: float = 0.9
    threat_verifier_model: str = ""
    threat_borderline_low: float = 0.35
    threat_borderline_high: float = 0.65
    max_content_chars: int = 8000
    max_skill_timeout_seconds: int = 30
    allow_shell_execution: bool = False
    output_filtering: bool = True
    output_pii_detection: bool = True
    output_prompt_leak_check: bool = True
    canary_tokens: bool = True
    pii_patterns: list[str] = field(default_factory=list)


@dataclass
class IdentityConfig:
    enabled: bool = True
    cross_channel: bool = True
    inject_in_prompt: bool = True
    notes_enabled: bool = True


@dataclass
class TracelineConfig:
    enabled: bool = True
    db_path: str = str(TRACES_DB)
    retention_days: int = 30
    export_otlp: bool = False
    otlp_endpoint: str = ""
    export_prometheus: bool = False
    metrics_port: int = 9090
    include_input: bool = True
    include_output: bool = True
    max_preview_chars: int = 500


@dataclass
class AuditConfig:
    enabled: bool = True
    jsonl_path: str = str(AUDIT_LOG)
    max_memory_entries: int = 200
    retention_days: int = 90
    siem_export: bool = False
    include_args: bool = True


@dataclass
class DesktopConfig:
    enabled: bool = False
    screenshot_on_action: bool = True
    action_delay_ms: int = 100


@dataclass
class VoiceConfig:
    enabled: bool = False
    provider: str = "edge-tts"
    voice: str = "en-US-AriaNeural"
    speed: float = 1.0
    output_format: str = "mp3"
    piper_binary: str = "piper"
    piper_model: str = ""
    auto_speak: bool = False
    max_tts_chars: int = 2000
    temp_dir: str = ""


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
    blocked_domains: list[str] = field(default_factory=lambda: ["localhost", "127.0.0.1", "169.254.169.254"])


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
class PolicyConfig:
    max_tool_calls_per_request: int = 10
    max_request_wall_seconds: float = 120.0
    # Tool allowlist. If empty, tools are allowed by name (legacy behavior).
    # If non-empty, any tool not in this list will be denied (recommended for production).
    allowed_tools: list[str] = field(default_factory=list)
    # Tools that are considered mutating (side-effectful). Used for idempotency.
    mutating_tools: list[str] = field(default_factory=lambda: [
        "write_file",
        "create_event",
        "delete_event",
    ])
    allowed_filesystem_roots: list[str] = field(default_factory=lambda: ["~/workspace"])
    deny_private_networks: bool = True
    deny_shell_execution: bool = True
    parallel_tool_execution: bool = True
    desktop_allowed_apps: list[str] = field(default_factory=list)
    desktop_blocked_regions: list[str] = field(default_factory=list)


@dataclass
class FederationConfig:
    """Federation protocol settings."""
    enabled: bool = True
    port: int = 8100
    bind_host: str = "127.0.0.1"
    seed_nodes: list[str] = field(default_factory=list)
    heartbeat_interval: int = 60
    node_name: str = ""
    a2a_enabled: bool = False
    a2a_auth_required: bool = True


@dataclass
class FeaturesConfig:
    """Feature flags for enabling/disabling subsystems (lite mode support)."""
    vector_memory: bool = True
    identity: bool = True
    vision: bool = False
    voice: bool = False
    browser: bool = False
    structured_output: bool = True
    streaming_responses: bool = False
    streaming_edit_interval: int = 20
    traceline: bool = True
    desktop: bool = False
    swarm: bool = True
    dashboard: bool = True
    evolution: bool = True
    reflective_reasoning: bool = True
    procedural_memory: bool = True
    semantic_memory: bool = True
    a2a_federation: bool = False

    @classmethod
    def lite(cls) -> "FeaturesConfig":
        """Minimal footprint — core reasoning only, no swarm/dashboard/evolution."""
        return cls(
            vector_memory=False,
            identity=False,
            vision=False,
            voice=False,
            browser=False,
            structured_output=False,
            streaming_responses=False,
            streaming_edit_interval=20,
            traceline=False,
            desktop=False,
            swarm=False,
            dashboard=False,
            evolution=False,
            reflective_reasoning=False,
            procedural_memory=False,
            semantic_memory=False,
            a2a_federation=False,
        )


@dataclass
class WorkspaceConfig:
    """Workspace settings for GitHub repo management and script execution."""
    repos_dir: str = "~/.neuralclaw/workspace/repos"
    max_repo_size_mb: int = 500
    allowed_git_hosts: list[str] = field(default_factory=lambda: ["github.com", "gitlab.com", "bitbucket.org"])
    max_clone_timeout_seconds: int = 120
    max_install_timeout_seconds: int = 300
    max_exec_timeout_seconds: int = 300


@dataclass
class ChannelConfig:
    name: str
    enabled: bool = False
    token: str | None = None
    trust_mode: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class NeuralClawConfig:
    name: str = "NeuralClaw"
    persona: str = ""  # Set from DEFAULT_CONFIG on load
    log_level: str = "INFO"
    telemetry_stdout: bool = True

    primary_provider: ProviderConfig | None = None
    fallback_providers: list[ProviderConfig] = field(default_factory=list)

    memory: MemoryConfig = field(default_factory=MemoryConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    identity: IdentityConfig = field(default_factory=IdentityConfig)
    traceline: TracelineConfig = field(default_factory=TracelineConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)
    desktop: DesktopConfig = field(default_factory=DesktopConfig)
    tts: VoiceConfig = field(default_factory=VoiceConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    google_workspace: GoogleWorkspaceConfig = field(default_factory=GoogleWorkspaceConfig)
    microsoft365: Microsoft365Config = field(default_factory=Microsoft365Config)
    features: FeaturesConfig = field(default_factory=FeaturesConfig)
    federation: FederationConfig = field(default_factory=FederationConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    apis: dict[str, dict[str, Any]] = field(default_factory=dict)
    channels: list[ChannelConfig] = field(default_factory=list)
    dashboard_port: int = 8080

    _raw: dict[str, Any] = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _build_provider(name: str, section: dict[str, Any]) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        model=section.get("model", "gpt-5.4"),
        base_url=section.get("base_url", ""),
        api_key=get_api_key(name),
        profile_dir=section.get("profile_dir", ""),
        headless=bool(section.get("headless", False)),
        browser_channel=section.get("browser_channel", ""),
        site_url=section.get("site_url", ""),
        auth_method=section.get("auth_method", ""),
    )


def load_config(path: Path | None = None) -> NeuralClawConfig:
    """Load configuration from TOML file, with defaults."""
    path = path or CONFIG_FILE
    raw: dict[str, Any] = {}

    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            raw = toml.load(f)

    # Merge with defaults
    merged = _deep_merge(DEFAULT_CONFIG, raw)

    general = merged.get("general", {})
    providers_section = merged.get("providers", {})
    mem_section = merged.get("memory", {})
    sec_section = merged.get("security", {})
    pol_section = merged.get("policy", {})
    id_section = merged.get("identity", {})
    trace_section = merged.get("traceline", {})
    audit_section = merged.get("audit", {})
    desktop_section = merged.get("desktop", {})
    tts_section = merged.get("tts", {})
    browser_section = merged.get("browser", {})
    google_section = merged.get("google_workspace", {})
    microsoft_section = merged.get("microsoft365", {})
    feat_section = merged.get("features", {})
    fed_section = merged.get("federation", {})
    ws_section = merged.get("workspace", {})
    apis_section = merged.get("apis", {})
    chan_section = merged.get("channels", {})

    # Build provider configs
    primary_name = providers_section.get("primary", "openai")
    primary = _build_provider(primary_name, providers_section.get(primary_name, {}))

    fallback_names = providers_section.get("fallback", [])
    fallbacks = [
        _build_provider(n, providers_section.get(n, {}))
        for n in fallback_names if n != primary_name
    ]

    # Build channel configs from TOML
    channels: list[ChannelConfig] = []
    for ch_name, ch_data in chan_section.items():
        if isinstance(ch_data, dict):
            token = (
                _get_secret(f"{ch_name}_api_key")
                or _get_secret(f"{ch_name}_token")
                or os.environ.get(f"NEURALCLAW_{ch_name.upper()}_TOKEN")
            )
            explicitly_enabled = ch_data.get("enabled", False)
            auto_enabled = bool(token)
            channels.append(ChannelConfig(
                name=ch_name,
                enabled=explicitly_enabled or auto_enabled,
                token=token,
                trust_mode=str(ch_data.get("trust_mode", "")),
                extra=ch_data,
            ))

    # Auto-detect keychain-only channels not in TOML
    _KNOWN_CHANNELS = {
        "slack": {"secret_key": "slack_bot", "extra_secrets": ["slack_app"]},
        "whatsapp": {"secret_key": "whatsapp"},
        "signal": {"secret_key": "signal"},
    }
    configured_names = {ch.name for ch in channels}
    for ch_name, ch_meta in _KNOWN_CHANNELS.items():
        if ch_name in configured_names:
            continue
        sk = ch_meta["secret_key"]
        token = (
            _get_secret(f"{sk}_api_key")
            or _get_secret(f"{sk}_token")
            or os.environ.get(f"NEURALCLAW_{sk.upper()}_TOKEN")
        )
        if token:
            extra: dict[str, Any] = {}
            for es in ch_meta.get("extra_secrets", []):
                ev = (
                    _get_secret(f"{es}_api_key")
                    or _get_secret(f"{es}_token")
                    or os.environ.get(f"NEURALCLAW_{es.upper()}_TOKEN")
                )
                if ev:
                    extra[es] = ev
            channels.append(ChannelConfig(
                name=ch_name, enabled=True, token=token, trust_mode="", extra=extra,
            ))

    config = NeuralClawConfig(
        name=general.get("name", "NeuralClaw"),
        persona=general.get("persona", DEFAULT_CONFIG["general"]["persona"]),
        log_level=general.get("log_level", "INFO"),
        telemetry_stdout=general.get("telemetry_stdout", True),
        primary_provider=primary,
        fallback_providers=fallbacks,
        memory=MemoryConfig(**_filter_fields(MemoryConfig, mem_section)),
        security=SecurityConfig(**_filter_fields(SecurityConfig, sec_section)),
        policy=PolicyConfig(**_filter_fields(PolicyConfig, pol_section)),
        identity=IdentityConfig(**_filter_fields(IdentityConfig, id_section)) if id_section else IdentityConfig(),
        traceline=TracelineConfig(**_filter_fields(TracelineConfig, trace_section)) if trace_section else TracelineConfig(),
        audit=AuditConfig(**_filter_fields(AuditConfig, audit_section)) if audit_section else AuditConfig(),
        desktop=DesktopConfig(**_filter_fields(DesktopConfig, desktop_section)) if desktop_section else DesktopConfig(),
        tts=VoiceConfig(**_filter_fields(VoiceConfig, tts_section)) if tts_section else VoiceConfig(),
        browser=BrowserConfig(**_filter_fields(BrowserConfig, browser_section)) if browser_section else BrowserConfig(),
        google_workspace=GoogleWorkspaceConfig(**_filter_fields(GoogleWorkspaceConfig, google_section)) if google_section else GoogleWorkspaceConfig(),
        microsoft365=Microsoft365Config(**_filter_fields(Microsoft365Config, microsoft_section)) if microsoft_section else Microsoft365Config(),
        features=FeaturesConfig(**_filter_fields(FeaturesConfig, feat_section)) if feat_section else FeaturesConfig(),
        federation=FederationConfig(**_filter_fields(FederationConfig, fed_section)) if fed_section else FederationConfig(),
        workspace=WorkspaceConfig(**_filter_fields(WorkspaceConfig, ws_section)) if ws_section else WorkspaceConfig(),
        apis=apis_section if isinstance(apis_section, dict) else {},
        channels=channels,
        _raw=merged,
    )

    if config.desktop.enabled:
        desktop_tools = [
            "desktop_screenshot",
            "desktop_click",
            "desktop_type",
            "desktop_hotkey",
            "desktop_get_clipboard",
            "desktop_set_clipboard",
            "desktop_run_app",
        ]
        for tool_name in desktop_tools:
            if tool_name not in config.policy.allowed_tools:
                config.policy.allowed_tools.append(tool_name)

    if config.tts.enabled:
        tts_tools = ["speak", "list_voices", "speak_and_play"]
        for tool_name in tts_tools:
            if tool_name not in config.policy.allowed_tools:
                config.policy.allowed_tools.append(tool_name)

    if config.browser.enabled:
        browser_tools = [
            "browser_navigate",
            "browser_screenshot",
            "browser_click",
            "browser_type",
            "browser_scroll",
            "browser_extract",
            "browser_execute_js",
            "browser_wait_for",
            "browser_act",
            "chrome_summarize",
            "chrome_translate",
            "chrome_prompt",
        ]
        for tool_name in browser_tools:
            if tool_name not in config.policy.allowed_tools:
                config.policy.allowed_tools.append(tool_name)

    if config.google_workspace.enabled:
        google_tools = [
            "gmail_search", "gmail_send", "gmail_get", "gmail_label", "gmail_draft",
            "gcal_list_events", "gcal_create_event", "gcal_update_event", "gcal_delete_event",
            "gdrive_search", "gdrive_read", "gdrive_upload",
            "gdocs_read", "gdocs_append", "gsheets_read", "gsheets_write",
            "gmeet_create",
        ]
        for tool_name in google_tools:
            if tool_name not in config.policy.allowed_tools:
                config.policy.allowed_tools.append(tool_name)
        for tool_name in [
            "gmail_send", "gcal_create_event", "gcal_update_event", "gcal_delete_event",
            "gdrive_upload", "gdocs_append", "gsheets_write", "gmeet_create",
        ]:
            if tool_name not in config.policy.mutating_tools:
                config.policy.mutating_tools.append(tool_name)

    if config.microsoft365.enabled:
        microsoft_tools = [
            "outlook_search", "outlook_send", "outlook_get",
            "ms_cal_list", "ms_cal_create", "ms_cal_delete",
            "teams_send", "teams_list_channels",
            "onedrive_search", "onedrive_read", "onedrive_upload",
            "sharepoint_search", "sharepoint_read",
        ]
        for tool_name in microsoft_tools:
            if tool_name not in config.policy.allowed_tools:
                config.policy.allowed_tools.append(tool_name)
        for tool_name in [
            "outlook_send", "ms_cal_create", "ms_cal_delete", "teams_send", "onedrive_upload",
        ]:
            if tool_name not in config.policy.mutating_tools:
                config.policy.mutating_tools.append(tool_name)

    return config


def ensure_dirs() -> None:
    """Create config / data / log directories if needed."""
    for d in (CONFIG_DIR, DATA_DIR, LOG_DIR, SESSION_DIR):
        d.mkdir(parents=True, exist_ok=True)


def save_default_config() -> Path:
    """Write default config.toml if it doesn't exist. Returns the path."""
    ensure_dirs()
    if not CONFIG_FILE.exists():
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            toml.dump(DEFAULT_CONFIG, f)
    return CONFIG_FILE


def update_config(updates: dict[str, Any], path: Path | None = None) -> Path:
    """Merge *updates* into the existing config.toml and write it back.

    Performs a recursive deep-merge so callers can pass partial dicts like
    ``{"providers": {"proxy": {"base_url": "http://..."}}}`` without
    clobbering other keys.  Returns the config file path.
    """
    path = path or CONFIG_FILE
    ensure_dirs()

    existing: dict[str, Any] = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            existing = toml.load(f)

    merged = _deep_merge(existing, updates)
    with open(path, "w", encoding="utf-8") as f:
        toml.dump(merged, f)

    return path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _filter_fields(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """Filter dict to only keys that are valid fields on the dataclass.

    Prevents TypeError crashes from unexpected keys in config.toml.
    """
    import dataclasses
    valid = {f.name for f in dataclasses.fields(cls)}
    return {k: v for k, v in data.items() if k in valid}


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

@dataclass
class ConfigValidationResult:
    """Result of config validation."""
    valid: bool
    errors: list[str]
    warnings: list[str]


def validate_config(config: NeuralClawConfig) -> ConfigValidationResult:
    """Validate a loaded config for common issues."""
    import re

    errors: list[str] = []
    warnings: list[str] = []

    # Provider checks
    keyless = {"local", "proxy", "chatgpt_app", "claude_app", "chatgpt_token", "claude_token"}
    if config.primary_provider:
        if config.primary_provider.name == "proxy" and not config.primary_provider.base_url:
            errors.append("Proxy provider requires a base_url in config.toml")
        elif config.primary_provider.name in {"chatgpt_app", "claude_app"} and not config.primary_provider.profile_dir:
            errors.append(
                f"Primary provider '{config.primary_provider.name}' requires a profile_dir. "
                f"Run: neuralclaw session setup {'chatgpt' if config.primary_provider.name == 'chatgpt_app' else 'claude'}"
            )
        elif config.primary_provider.name not in keyless and not config.primary_provider.api_key:
            errors.append(
                f"Primary provider '{config.primary_provider.name}' has no API key. "
                f"Run: neuralclaw init"
            )

    # Channel checks
    for ch in config.channels:
        if ch.enabled and not ch.token:
            warnings.append(
                f"Channel '{ch.name}' is enabled but has no token. "
                f"Run: neuralclaw channels setup"
            )

    # Security range checks
    if not (0.0 <= config.security.threat_threshold <= 1.0):
        errors.append(f"threat_threshold must be 0.0-1.0, got {config.security.threat_threshold}")
    if not (0.0 <= config.security.block_threshold <= 1.0):
        errors.append(f"block_threshold must be 0.0-1.0, got {config.security.block_threshold}")
    if config.memory.embedding_dimension <= 0:
        errors.append(
            f"embedding_dimension must be > 0, got {config.memory.embedding_dimension}"
        )
    if config.memory.vector_similarity_top_k <= 0:
        errors.append(
            "vector_similarity_top_k must be > 0, "
            f"got {config.memory.vector_similarity_top_k}"
        )
    if config.audit.max_memory_entries <= 0:
        errors.append(
            "audit.max_memory_entries must be > 0, "
            f"got {config.audit.max_memory_entries}"
        )
    if config.audit.retention_days < 0:
        errors.append(
            "audit.retention_days must be >= 0, "
            f"got {config.audit.retention_days}"
        )
    if config.desktop.action_delay_ms < 0:
        errors.append(
            "desktop.action_delay_ms must be >= 0, "
            f"got {config.desktop.action_delay_ms}"
        )
    if config.tts.max_tts_chars <= 0:
        errors.append(
            "tts.max_tts_chars must be > 0, "
            f"got {config.tts.max_tts_chars}"
        )
    if config.tts.speed <= 0:
        errors.append(
            "tts.speed must be > 0, "
            f"got {config.tts.speed}"
        )
    if config.browser.navigation_timeout <= 0:
        errors.append(
            "browser.navigation_timeout must be > 0, "
            f"got {config.browser.navigation_timeout}"
        )
    if config.browser.max_steps_per_task <= 0:
        errors.append(
            "browser.max_steps_per_task must be > 0, "
            f"got {config.browser.max_steps_per_task}"
        )
    if config.browser.viewport_width <= 0 or config.browser.viewport_height <= 0:
        errors.append(
            "browser viewport must be positive, "
            f"got {config.browser.viewport_width}x{config.browser.viewport_height}"
        )
    if config.google_workspace.response_body_limit <= 0:
        errors.append(
            "google_workspace.response_body_limit must be > 0, "
            f"got {config.google_workspace.response_body_limit}"
        )
    if config.google_workspace.max_email_results <= 0:
        errors.append(
            "google_workspace.max_email_results must be > 0, "
            f"got {config.google_workspace.max_email_results}"
        )
    if config.google_workspace.max_drive_results <= 0:
        errors.append(
            "google_workspace.max_drive_results must be > 0, "
            f"got {config.google_workspace.max_drive_results}"
        )
    if config.microsoft365.max_email_results <= 0:
        errors.append(
            "microsoft365.max_email_results must be > 0, "
            f"got {config.microsoft365.max_email_results}"
        )
    if config.microsoft365.max_file_results <= 0:
        errors.append(
            "microsoft365.max_file_results must be > 0, "
            f"got {config.microsoft365.max_file_results}"
        )
    for pattern in config.security.pii_patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            errors.append(f"Invalid security.pii_patterns regex '{pattern}': {exc}")
    for region in config.policy.desktop_blocked_regions:
        parts = [part.strip() for part in region.split(",")]
        if len(parts) != 4:
            errors.append(
                "policy.desktop_blocked_regions entries must be 'x1,y1,x2,y2', "
                f"got '{region}'"
            )
            continue
        try:
            [int(part) for part in parts]
        except ValueError:
            errors.append(
                "policy.desktop_blocked_regions entries must contain integers, "
                f"got '{region}'"
            )

    # Memory path check
    db_dir = Path(config.memory.db_path).parent
    if not db_dir.exists():
        warnings.append(f"Memory DB directory does not exist: {db_dir}")

    return ConfigValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Config backup / restore
# ---------------------------------------------------------------------------

def backup_config() -> Path | None:
    """Create a timestamped backup of config.toml."""
    import shutil
    import time
    if not CONFIG_FILE.exists():
        return None
    backup = CONFIG_DIR / f"config.toml.bak.{int(time.time())}"
    shutil.copy2(CONFIG_FILE, backup)
    return backup


def restore_config(backup_path: Path) -> bool:
    """Restore config.toml from a backup file."""
    import shutil
    if not backup_path.exists():
        return False
    shutil.copy2(backup_path, CONFIG_FILE)
    return True


def list_config_backups() -> list[Path]:
    """List all config.toml backups sorted by time (newest first)."""
    return sorted(
        CONFIG_DIR.glob("config.toml.bak.*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
