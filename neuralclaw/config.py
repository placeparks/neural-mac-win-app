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

from neuralclaw.skills.paths import resolve_user_skills_dir

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP_NAME = "neuralclaw"


def _resolve_config_dir() -> Path:
    override = os.environ.get("NEURALCLAW_HOME") or os.environ.get("NEURALCLAW_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / f".{APP_NAME}"


CONFIG_DIR = _resolve_config_dir()
CONFIG_FILE = CONFIG_DIR / "config.toml"
DATA_DIR = CONFIG_DIR / "data"
LOG_DIR = CONFIG_DIR / "logs"
SESSION_DIR = CONFIG_DIR / "sessions"
MEMORY_DB = DATA_DIR / "memory.db"
TRACES_DB = DATA_DIR / "traces.db"
AUDIT_LOG = LOG_DIR / "audit.jsonl"
CHANNEL_BINDINGS_FILE = DATA_DIR / "channel_bindings.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "dashboard_host": "127.0.0.1",
    "dashboard_port": 8080,
    "general": {
        "name": "NeuralClaw",
        "persona": "You are NeuralClaw, a self-evolving cognitive AI agent with persistent memory and tool use capabilities.",
        "log_level": "INFO",
        "log_file": str(LOG_DIR / "neuralclaw.log"),
        "log_stdout": True,
        "log_max_bytes": 10485760,
        "log_backups": 5,
        "telemetry_stdout": True,
        "dev_mode": False,
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
        "database_bi": True,           # Database connectors + natural-language BI
        "clipboard_intel": True,       # Clipboard monitoring + entity extraction
        "kpi_monitor": True,           # KPI monitoring agents with alerting
        "scheduler": True,             # Cron-based scheduling + webhook ingestion
        "context_aware": True,         # Active-window context suggestions
        "digest": True,                # Email/chat digest summarization
        "offline_fallback": True,      # Auto-fallback to local models when offline
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
        "google": {
            "model": "gemini-2.5-pro",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        },
        "xai": {
            "model": "grok-3-beta",
            "base_url": "https://api.x.ai/v1",
        },
        "venice": {
            "model": "venice-large",
            "base_url": "https://api.venice.ai/api/v1",
        },
        "mistral": {
            "model": "mistral-large-latest",
            "base_url": "https://api.mistral.ai/v1",
        },
        "minimax": {
            "model": "MiniMax-M1",
            "base_url": "https://api.minimax.chat/v1",
        },
        "vercel": {
            "model": "openai/gpt-5.4",
            "base_url": "https://ai-gateway.vercel.sh/v1",
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
        "episodic_retention_days": 90,
        "semantic_retention_days": 180,
        "procedural_retention_days": 365,
        "vector_retention_days": 90,
        "identity_retention_days": 365,
        "retention_cleanup_interval_seconds": 300,
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
        "full_machine_access": True,
        "autonomous_execution": False,
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
        "max_tool_calls_per_request": 25,
        # Wall-clock budget for an entire reasoning request, including any
        # tool-use loop iterations. Local 26B+ thinking models routinely
        # spend 100+ seconds on the reasoning channel before issuing a
        # tool call, so 120s deny-walled most multi-step tasks. 600s gives
        # local profiles enough room without changing the cloud feel.
        "max_request_wall_seconds": 600.0,
        "allowed_tools": [
            # Built-in tools (safe defaults; unknown tools are denied)
            "web_search",
            "fetch_url",
            "build_app",
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
            "github_list_pull_requests",
            "github_get_pull_request",
            "github_list_issues",
            "github_get_issue",
            "github_get_ci_status",
            "github_comment_issue",
            # Repo execution
            "run_repo_script",
            "run_repo_command",
            # API client
            "api_request",
            "save_api_config",
            "list_api_configs",
            # Package management
            "pip_install",
        ],
        "mutating_tools": [
            "build_app",
            "write_file",
            "create_event",
            "delete_event",
            "github_comment_issue",
            "clone_repo",
            "install_repo_deps",
            "remove_repo",
            "save_api_config",
        ],
        "allowed_filesystem_roots": [
            "~/workspace",
            "~/.neuralclaw/workspace/repos",
            "~/projects",
        ],
        "deny_private_networks": True,
        "deny_shell_execution": True,
        "parallel_tool_execution": True,
        "user_requests_per_minute": 20,
        "user_requests_per_hour": 200,
        "channel_sends_per_second": 1.0,
        "channel_sends_per_minute": 20,
        "max_concurrent_requests": 10,
        "security_block_cooldown_seconds": 300,
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
        "apps_dir": "~/projects",
        "max_repo_size_mb": 500,
        "allowed_git_hosts": ["github.com", "gitlab.com", "bitbucket.org"],
        "max_clone_timeout_seconds": 120,
        "max_install_timeout_seconds": 300,
        "max_exec_timeout_seconds": 300,
    },
    "forge": {
        "model": "claude-sonnet-4-20250514",
        "user_skills_dir": "",
        "hot_reload": True,
        "sandbox_timeout": 15,
        "provider_request_timeout_seconds": 300,
        "provider_max_retries": 0,
        "provider_circuit_timeout_seconds": 20,
        "provider_slow_call_threshold_ms": 240000,
        "max_tools_per_skill": 10,
        "allow_network_skills": True,
        "allow_filesystem_skills": False,
        "require_use_case": False,
    },
    "rag": {
        "enabled": True,
        "db_path": str(DATA_DIR / "knowledge.db"),
        "chunk_size": 1024,
        "overlap": 128,
        "retrieval_top_k": 5,
        "max_doc_size_mb": 50,
        "auto_index_paths": [str(Path.home() / "projects")],
    },
    "workflow": {
        "enabled": True,
        "db_path": str(DATA_DIR / "workflows.db"),
        "max_concurrent_workflows": 5,
        "max_steps_per_workflow": 50,
        "step_timeout_seconds": 120,
    },
    "database_bi": {
        "enabled": True,
        "max_result_rows": 500,
        "max_chart_rows": 5000,
        "read_only_default": True,
        "allowed_drivers": ["sqlite", "postgres", "postgresql", "mysql", "mongodb", "clickhouse"],
        "saved_connections": {},  # name -> {driver, dsn, schema, read_only}
    },
    "mcp_server": {
        "enabled": False,
        "port": 3001,
        "bind_host": "127.0.0.1",
        "auth_token": "",
        "expose_tools": True,
        "expose_resources": True,
        "expose_prompts": True,
    },
    "model_roles": {
        "enabled": False,
        "primary": "qwen3.5:35b",
        "fast": "qwen3.5:9b",
        "micro": "qwen3.5:4b",
        "embed": "",   # auto-detected from Ollama at startup
        "base_url": "http://localhost:11434/v1",
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
        "whatsapp": {
            "enabled": False,
            "trust_mode": "",
            "allow_self_chat": True,
            "allow_contact_chats": False,
        },
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


def clear_secret(key: str) -> None:
    """Remove a secret from OS keychain and local fallback store."""
    try:
        import keyring as kr
        try:
            kr.delete_password(APP_NAME, key)
        except Exception:
            pass
    except Exception:
        pass

    try:
        secrets_file = CONFIG_DIR / ".secrets.toml"
        if not secrets_file.exists():
            return
        with open(secrets_file, "r", encoding="utf-8") as f:
            secrets = toml.load(f)
        if key in secrets:
            del secrets[key]
            with open(secrets_file, "w", encoding="utf-8") as f:
                toml.dump(secrets, f)
            try:
                secrets_file.chmod(0o600)
            except Exception:
                pass
    except Exception as e:
        print(f"Failed to clear secret locally: {e}")


def get_api_key(provider: str) -> str | None:
    """Get API key. Checks env vars first (fast, no I/O), then OS keychain."""
    env_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "google": "GOOGLE_API_KEY",
        "xai": "XAI_API_KEY",
        "venice": "VENICE_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "minimax": "MINIMAX_API_KEY",
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


def delete_api_key(provider: str) -> None:
    """Delete API key from OS keychain/local fallback."""
    clear_secret(f"{provider}_api_key")


def get_dashboard_auth_token() -> str | None:
    """Get the dashboard auth token from env or secret storage."""
    env_val = os.environ.get("NEURALCLAW_DASHBOARD_AUTH_TOKEN")
    if env_val:
        return env_val
    return _get_secret("dashboard_auth_token")


def set_dashboard_auth_token(token: str) -> None:
    """Persist the dashboard auth token in secret storage."""
    _set_secret("dashboard_auth_token", token)


def delete_dashboard_auth_token() -> None:
    """Remove the dashboard auth token from secret storage."""
    clear_secret("dashboard_auth_token")


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
    episodic_retention_days: int = 90
    semantic_retention_days: int = 180
    procedural_retention_days: int = 365
    vector_retention_days: int = 90
    identity_retention_days: int = 365
    retention_cleanup_interval_seconds: int = 300


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
    full_machine_access: bool = True  # When True, agent can execute code and access filesystem on the local machine
    autonomous_execution: bool = False


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
    max_tool_calls_per_request: int = 25
    max_request_wall_seconds: float = 600.0
    # Tool allowlist. If empty, tools are allowed by name (legacy behavior).
    # If non-empty, any tool not in this list will be denied (recommended for production).
    allowed_tools: list[str] = field(default_factory=list)
    # Tools that are considered mutating (side-effectful). Used for idempotency.
    mutating_tools: list[str] = field(default_factory=lambda: [
        "build_app",
        "write_file",
        "create_event",
        "delete_event",
    ])
    allowed_filesystem_roots: list[str] = field(
        default_factory=lambda: [
            "~/workspace",
            "~/.neuralclaw/workspace/repos",
            "~/projects",
        ]
    )
    deny_private_networks: bool = True
    deny_shell_execution: bool = True
    parallel_tool_execution: bool = True
    user_requests_per_minute: int = 20
    user_requests_per_hour: int = 200
    channel_sends_per_second: float = 1.0
    channel_sends_per_minute: int = 20
    max_concurrent_requests: int = 10
    security_block_cooldown_seconds: int = 300
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
    database_bi: bool = True
    clipboard_intel: bool = True
    kpi_monitor: bool = True
    scheduler: bool = True
    context_aware: bool = True
    digest: bool = True
    offline_fallback: bool = True
    skill_forge: bool = True
    rag: bool = True
    workflow_engine: bool = True
    mcp_server: bool = False

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
            database_bi=False,
            clipboard_intel=False,
            kpi_monitor=False,
            scheduler=False,
            context_aware=False,
            digest=False,
            offline_fallback=True,  # Keep offline fallback even in lite mode
            skill_forge=False,
            rag=False,
            workflow_engine=False,
            mcp_server=False,
        )


@dataclass
class ModelRolesConfig:
    """Role-based model routing — deterministic model selection by call-site role.

    Roles:
        primary — deep reasoning, vision, complex agent tasks, user-facing final answers
        fast    — tool call execution, skill dispatch, multi-step loops
        micro   — intent classification, routing, quick yes/no ops
        embed   — embeddings for Nexus Memory, RAG, semantic search
    """
    primary: str = "qwen3.5:35b"
    fast: str = "qwen3.5:9b"
    micro: str = "qwen3.5:4b"
    embed: str = ""  # empty = auto-detect from Ollama at startup
    base_url: str = "http://localhost:11434/v1"
    enabled: bool = False

    def get_model(self, role: str) -> str:
        """Get model name for a given role, falling back to primary."""
        return getattr(self, role, self.primary)


@dataclass
class ForgeConfig:
    """SkillForge configuration for proactive skill synthesis."""
    model: str = "claude-sonnet-4-20250514"
    user_skills_dir: str = ""
    hot_reload: bool = True
    sandbox_timeout: int = 15
    provider_request_timeout_seconds: int = 300
    provider_max_retries: int = 0
    provider_circuit_timeout_seconds: int = 20
    provider_slow_call_threshold_ms: int = 240000
    max_tools_per_skill: int = 10
    allow_network_skills: bool = True
    allow_filesystem_skills: bool = False
    require_use_case: bool = False


@dataclass
class RAGConfig:
    """RAG / Knowledge Base configuration."""
    enabled: bool = True
    db_path: str = str(DATA_DIR / "knowledge.db")
    chunk_size: int = 1024
    overlap: int = 128
    retrieval_top_k: int = 5
    max_doc_size_mb: int = 50
    auto_index_paths: list[str] = field(default_factory=lambda: [str(Path.home() / "projects")])


@dataclass
class WorkflowConfig:
    """Workflow engine configuration."""
    enabled: bool = True
    db_path: str = str(DATA_DIR / "workflows.db")
    max_concurrent_workflows: int = 5
    max_steps_per_workflow: int = 50
    step_timeout_seconds: int = 120


@dataclass
class DatabaseBIConfig:
    """Database BI skill configuration."""
    enabled: bool = True
    max_result_rows: int = 500
    max_chart_rows: int = 5000
    read_only_default: bool = True
    workspace_provider: str = "primary"
    workspace_model: str = ""
    workspace_base_url: str = ""
    workspace_allow_fallback: bool = False
    allowed_drivers: list[str] = field(default_factory=lambda: [
        "sqlite", "postgres", "postgresql", "mysql", "mongodb", "clickhouse",
    ])
    saved_connections: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class MCPServerConfig:
    """MCP Server configuration."""
    enabled: bool = False
    port: int = 3001
    bind_host: str = "127.0.0.1"
    auth_token: str = ""
    expose_tools: bool = True
    expose_resources: bool = True
    expose_prompts: bool = True


@dataclass
class WorkspaceConfig:
    """Workspace settings for GitHub repo management and script execution."""
    repos_dir: str = "~/.neuralclaw/workspace/repos"
    apps_dir: str = "~/projects"
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
    log_file: str = str(LOG_DIR / "neuralclaw.log")
    log_stdout: bool = True
    log_max_bytes: int = 10485760
    log_backups: int = 5
    telemetry_stdout: bool = True
    dev_mode: bool = False

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
    forge: ForgeConfig = field(default_factory=ForgeConfig)
    rag: RAGConfig = field(default_factory=RAGConfig)
    workflow: WorkflowConfig = field(default_factory=WorkflowConfig)
    database_bi: DatabaseBIConfig = field(default_factory=DatabaseBIConfig)
    mcp_server: MCPServerConfig = field(default_factory=MCPServerConfig)
    model_roles: ModelRolesConfig = field(default_factory=ModelRolesConfig)
    apis: dict[str, dict[str, Any]] = field(default_factory=dict)
    channels: list[ChannelConfig] = field(default_factory=list)
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8080
    dashboard_auth_token: str | None = None

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
    forge_section = merged.get("forge", {})
    rag_section = merged.get("rag", {})
    wf_section = merged.get("workflow", {})
    dbi_section = merged.get("database_bi", {})
    mcp_section = merged.get("mcp_server", {})
    roles_section = merged.get("model_roles", {})
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
            if ch_name == "whatsapp" and not token:
                token = str(ch_data.get("auth_dir", "") or "").strip() or None
            # Respect explicit enabled=false; only auto-enable when key is absent
            has_explicit_enabled = "enabled" in ch_data
            enabled = ch_data.get("enabled", False) if has_explicit_enabled else bool(token)
            channels.append(ChannelConfig(
                name=ch_name,
                enabled=enabled,
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

    # Auto-detect desktop sidecar mode: if running as a PyInstaller-frozen
    # binary (the Tauri desktop sidecar), auto-enable the desktop config so
    # the agent has full local-machine access without manual TOML edits.
    import sys as _sys
    if getattr(_sys, "frozen", False):
        desktop_section.setdefault("enabled", True)
        desktop_section.setdefault("full_machine_access", True)

    config = NeuralClawConfig(
        name=general.get("name", "NeuralClaw"),
        persona=general.get("persona", DEFAULT_CONFIG["general"]["persona"]),
        log_level=general.get("log_level", "INFO"),
        log_file=str(general.get("log_file", str(LOG_DIR / "neuralclaw.log")) or ""),
        log_stdout=bool(general.get("log_stdout", general.get("telemetry_stdout", True))),
        log_max_bytes=int(general.get("log_max_bytes", 10485760) or 10485760),
        log_backups=int(general.get("log_backups", 5) or 5),
        telemetry_stdout=general.get("telemetry_stdout", True),
        dev_mode=bool(general.get("dev_mode", False)),
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
        forge=ForgeConfig(**_filter_fields(ForgeConfig, forge_section)) if forge_section else ForgeConfig(),
        rag=RAGConfig(**_filter_fields(RAGConfig, rag_section)) if rag_section else RAGConfig(),
        workflow=WorkflowConfig(**_filter_fields(WorkflowConfig, wf_section)) if wf_section else WorkflowConfig(),
        database_bi=DatabaseBIConfig(**_filter_fields(DatabaseBIConfig, dbi_section)) if dbi_section else DatabaseBIConfig(),
        mcp_server=MCPServerConfig(**_filter_fields(MCPServerConfig, mcp_section)) if mcp_section else MCPServerConfig(),
        model_roles=ModelRolesConfig(**_filter_fields(ModelRolesConfig, roles_section)) if roles_section else ModelRolesConfig(),
        apis=apis_section if isinstance(apis_section, dict) else {},
        channels=channels,
        dashboard_host=str(merged.get("dashboard_host", "127.0.0.1") or "127.0.0.1"),
        dashboard_port=int(merged.get("dashboard_port", 8080) or 8080),
        dashboard_auth_token=get_dashboard_auth_token(),
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

        # -- Desktop full-machine-access reconciliation --
        # When running as a desktop app on the user's own machine the agent
        # must be able to execute code and read/write files freely.
        if config.desktop.full_machine_access:
            config.policy.deny_shell_execution = False
            config.security.allow_shell_execution = True

            # Ensure code-execution tools are in the allowlist
            exec_tools = [
                "execute_python", "code_exec", "shell_exec",
                "run_repo_script", "run_repo_command",
            ]
            for tool_name in exec_tools:
                if tool_name not in config.policy.allowed_tools:
                    config.policy.allowed_tools.append(tool_name)

            # Expand filesystem roots to cover common user directories so the
            # sandbox and policy engine don't block local file operations.
            home = str(Path.home())
            desktop_roots = [
                home,
                str(Path.home() / "Desktop"),
                str(Path.home() / "Documents"),
                str(Path.home() / "Downloads"),
                str(Path.home() / "Projects"),
                str(Path.home() / ".neuralclaw"),
            ]
            for root in desktop_roots:
                if root not in config.policy.allowed_filesystem_roots:
                    config.policy.allowed_filesystem_roots.append(root)

            # Auto-enable model_roles in desktop mode so the embed model is
            # properly isolated and auto-detected from the running Ollama server.
            if not config.model_roles.enabled:
                config.model_roles.enabled = True

            # If model_roles URL still points at localhost, pull it from the
            # local provider config which the user may have set correctly.
            _localhost_prefixes = ("http://localhost", "http://127.0.0.1")
            if any(config.model_roles.base_url.startswith(p) for p in _localhost_prefixes):
                _local_provider_url = ""
                for _provider_cfg in [config.primary_provider] + list(config.fallback_providers):
                    if getattr(_provider_cfg, "type", "") in ("local", "ollama") or "11434" in getattr(_provider_cfg, "base_url", ""):
                        _local_provider_url = getattr(_provider_cfg, "base_url", "")
                        break
                if _local_provider_url and not any(_local_provider_url.startswith(p) for p in _localhost_prefixes):
                    config.model_roles.base_url = _local_provider_url

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

    if config.features.skill_forge:
        for tool_name in ["forge_skill", "scout_skill"]:
            if tool_name not in config.policy.allowed_tools:
                config.policy.allowed_tools.append(tool_name)

    apps_root = str(Path(config.workspace.apps_dir).expanduser())
    if apps_root and apps_root not in config.policy.allowed_filesystem_roots:
        config.policy.allowed_filesystem_roots.append(apps_root)
    skills_root = str(resolve_user_skills_dir(config.forge.user_skills_dir))
    if skills_root and skills_root not in config.policy.allowed_filesystem_roots:
        config.policy.allowed_filesystem_roots.append(skills_root)
    config_root = str(CONFIG_DIR.expanduser())
    if config_root and config_root not in config.policy.allowed_filesystem_roots:
        config.policy.allowed_filesystem_roots.append(config_root)
    if "build_app" not in config.policy.allowed_tools:
        config.policy.allowed_tools.append("build_app")
    if "build_app" not in config.policy.mutating_tools:
        config.policy.mutating_tools.append("build_app")

    if config.features.rag:
        rag_tools = ["kb_ingest", "kb_ingest_text", "kb_search", "kb_list", "kb_delete"]
        for tool_name in rag_tools:
            if tool_name not in config.policy.allowed_tools:
                config.policy.allowed_tools.append(tool_name)
        for tool_name in ["kb_ingest", "kb_ingest_text", "kb_delete"]:
            if tool_name not in config.policy.mutating_tools:
                config.policy.mutating_tools.append(tool_name)

    if config.features.workflow_engine:
        wf_tools = [
            "create_workflow", "run_workflow", "pause_workflow",
            "resume_workflow", "workflow_status", "list_workflows", "delete_workflow",
        ]
        for tool_name in wf_tools:
            if tool_name not in config.policy.allowed_tools:
                config.policy.allowed_tools.append(tool_name)
        for tool_name in ["create_workflow", "run_workflow", "pause_workflow",
                          "resume_workflow", "delete_workflow"]:
            if tool_name not in config.policy.mutating_tools:
                config.policy.mutating_tools.append(tool_name)

    if config.features.database_bi:
        db_tools = [
            "db_connect", "db_disconnect", "db_list_connections",
            "db_list_tables", "db_describe_table", "db_query",
            "db_natural_query", "db_chart", "db_explain_data",
        ]
        for tool_name in db_tools:
            if tool_name not in config.policy.allowed_tools:
                config.policy.allowed_tools.append(tool_name)
        for tool_name in ["db_connect", "db_disconnect"]:
            if tool_name not in config.policy.mutating_tools:
                config.policy.mutating_tools.append(tool_name)

    if config.features.clipboard_intel:
        clip_tools = ["clipboard_watch", "clipboard_history", "clipboard_analyze", "clipboard_smart_paste"]
        for tool_name in clip_tools:
            if tool_name not in config.policy.allowed_tools:
                config.policy.allowed_tools.append(tool_name)

    if config.features.kpi_monitor:
        kpi_tools = ["kpi_create_monitor", "kpi_list_monitors", "kpi_remove_monitor", "kpi_check_now", "kpi_history"]
        for tool_name in kpi_tools:
            if tool_name not in config.policy.allowed_tools:
                config.policy.allowed_tools.append(tool_name)
        for tool_name in ["kpi_create_monitor", "kpi_remove_monitor"]:
            if tool_name not in config.policy.mutating_tools:
                config.policy.mutating_tools.append(tool_name)

    if config.features.scheduler:
        sched_tools = [
            "schedule_create", "schedule_list", "schedule_remove",
            "schedule_pause", "schedule_resume",
            "webhook_register", "webhook_list", "webhook_remove",
        ]
        for tool_name in sched_tools:
            if tool_name not in config.policy.allowed_tools:
                config.policy.allowed_tools.append(tool_name)
        for tool_name in ["schedule_create", "schedule_remove", "webhook_register", "webhook_remove"]:
            if tool_name not in config.policy.mutating_tools:
                config.policy.mutating_tools.append(tool_name)

    if config.features.context_aware:
        ctx_tools = ["context_detect", "context_suggest", "context_quick_action"]
        for tool_name in ctx_tools:
            if tool_name not in config.policy.allowed_tools:
                config.policy.allowed_tools.append(tool_name)

    if config.features.digest:
        digest_tools = ["digest_create", "digest_morning_briefing", "digest_summarize_thread", "digest_compare"]
        for tool_name in digest_tools:
            if tool_name not in config.policy.allowed_tools:
                config.policy.allowed_tools.append(tool_name)

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

    if str(config.log_level).upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        errors.append(
            f"log_level must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL; got {config.log_level}"
        )
    if config.log_max_bytes <= 0:
        errors.append(f"log_max_bytes must be > 0, got {config.log_max_bytes}")
    if config.log_backups < 0:
        errors.append(f"log_backups must be >= 0, got {config.log_backups}")

    # Provider checks
    keyless = {"local", "proxy", "chatgpt_app", "claude_app", "chatgpt_token", "claude_token", "meta"}
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
        effective_token = ch.token
        if ch.name == "whatsapp" and not effective_token:
            effective_token = str(ch.extra.get("auth_dir", "") or "").strip() or None
        if ch.enabled and not effective_token:
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
    if config.policy.user_requests_per_minute <= 0:
        errors.append(
            "policy.user_requests_per_minute must be > 0, "
            f"got {config.policy.user_requests_per_minute}"
        )
    if config.policy.user_requests_per_hour <= 0:
        errors.append(
            "policy.user_requests_per_hour must be > 0, "
            f"got {config.policy.user_requests_per_hour}"
        )
    if config.policy.channel_sends_per_second <= 0:
        errors.append(
            "policy.channel_sends_per_second must be > 0, "
            f"got {config.policy.channel_sends_per_second}"
        )
    if config.policy.max_concurrent_requests <= 0:
        errors.append(
            "policy.max_concurrent_requests must be > 0, "
            f"got {config.policy.max_concurrent_requests}"
        )
    if config.policy.security_block_cooldown_seconds < 0:
        errors.append(
            "policy.security_block_cooldown_seconds must be >= 0, "
            f"got {config.policy.security_block_cooldown_seconds}"
        )
    if not str(config.workspace.apps_dir).strip():
        errors.append("workspace.apps_dir must not be empty")
    if not str(config.dashboard_host).strip():
        errors.append("dashboard_host must not be empty")
    if config.dashboard_port <= 0 or config.dashboard_port > 65535:
        errors.append(
            f"dashboard_port must be between 1 and 65535, got {config.dashboard_port}"
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
