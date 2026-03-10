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
MEMORY_DB = DATA_DIR / "memory.db"

DEFAULT_CONFIG: dict[str, Any] = {
    "general": {
        "name": "NeuralClaw",
        "persona": "You are NeuralClaw, a helpful and intelligent AI assistant.",
        "log_level": "INFO",
        "telemetry_stdout": True,
    },
    # Feature flags — disable to run in lite mode (lower RAM, faster boot)
    "features": {
        "swarm": True,           # Agent mesh, delegation, consensus
        "dashboard": True,       # Web dashboard on port 7474
        "evolution": True,       # Behavioral calibrator, distiller, synthesizer
        "reflective_reasoning": True,  # Multi-step planning (uses extra LLM calls)
        "procedural_memory": True,     # Trigger-pattern procedure matching
        "semantic_memory": True,       # Knowledge graph
    },
    "providers": {
        "primary": "openai",
        "fallback": ["openrouter", "local"],
        "openai": {
            "model": "gpt-4o",
            "base_url": "https://api.openai.com/v1",
        },
        "anthropic": {
            "model": "claude-sonnet-4-20250514",
            "base_url": "https://api.anthropic.com",
        },
        "openrouter": {
            "model": "anthropic/claude-sonnet-4-20250514",
            "base_url": "https://openrouter.ai/api/v1",
        },
        "local": {
            "model": "llama3",
            "base_url": "http://localhost:11434/v1",
        },
        "proxy": {
            "model": "gpt-4",
            "base_url": "",
        },
    },
    "memory": {
        "db_path": str(MEMORY_DB),
        "max_episodic_results": 10,
        "max_semantic_results": 5,
        "importance_threshold": 0.3,
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
        ],
        "mutating_tools": [
            "write_file",
            "create_event",
            "delete_event",
        ],
        "allowed_filesystem_roots": ["~/workspace"],
        "deny_private_networks": True,
        "deny_shell_execution": True,
    },
    "federation": {
        "enabled": True,
        "port": 8100,
        "bind_host": "127.0.0.1",
        "seed_nodes": [],
        "heartbeat_interval": 60,
        "node_name": "",
    },
    "channels": {
        "telegram": {"enabled": False},
        "discord": {"enabled": False},
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


@dataclass
class MemoryConfig:
    db_path: str = str(MEMORY_DB)
    max_episodic_results: int = 10
    max_semantic_results: int = 5
    importance_threshold: float = 0.3


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


@dataclass
class FederationConfig:
    """Federation protocol settings."""
    enabled: bool = True
    port: int = 8100
    bind_host: str = "127.0.0.1"
    seed_nodes: list[str] = field(default_factory=list)
    heartbeat_interval: int = 60
    node_name: str = ""


@dataclass
class FeaturesConfig:
    """Feature flags for enabling/disabling subsystems (lite mode support)."""
    swarm: bool = True
    dashboard: bool = True
    evolution: bool = True
    reflective_reasoning: bool = True
    procedural_memory: bool = True
    semantic_memory: bool = True

    @classmethod
    def lite(cls) -> "FeaturesConfig":
        """Minimal footprint — core reasoning only, no swarm/dashboard/evolution."""
        return cls(
            swarm=False,
            dashboard=False,
            evolution=False,
            reflective_reasoning=False,
            procedural_memory=False,
            semantic_memory=False,
        )


@dataclass
class ChannelConfig:
    name: str
    enabled: bool = False
    token: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class NeuralClawConfig:
    name: str = "NeuralClaw"
    persona: str = "You are NeuralClaw, a helpful and intelligent AI assistant."
    log_level: str = "INFO"
    telemetry_stdout: bool = True

    primary_provider: ProviderConfig | None = None
    fallback_providers: list[ProviderConfig] = field(default_factory=list)

    memory: MemoryConfig = field(default_factory=MemoryConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    features: FeaturesConfig = field(default_factory=FeaturesConfig)
    federation: FederationConfig = field(default_factory=FederationConfig)
    channels: list[ChannelConfig] = field(default_factory=list)
    dashboard_port: int = 8080

    _raw: dict[str, Any] = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _build_provider(name: str, section: dict[str, Any]) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        model=section.get("model", "gpt-4o"),
        base_url=section.get("base_url", ""),
        api_key=get_api_key(name),
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
    feat_section = merged.get("features", {})
    fed_section = merged.get("federation", {})
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
                name=ch_name, enabled=True, token=token, extra=extra,
            ))

    return NeuralClawConfig(
        name=general.get("name", "NeuralClaw"),
        persona=general.get("persona", DEFAULT_CONFIG["general"]["persona"]),
        log_level=general.get("log_level", "INFO"),
        telemetry_stdout=general.get("telemetry_stdout", True),
        primary_provider=primary,
        fallback_providers=fallbacks,
        memory=MemoryConfig(**_filter_fields(MemoryConfig, mem_section)),
        security=SecurityConfig(**_filter_fields(SecurityConfig, sec_section)),
        policy=PolicyConfig(**_filter_fields(PolicyConfig, pol_section)),
        features=FeaturesConfig(**_filter_fields(FeaturesConfig, feat_section)) if feat_section else FeaturesConfig(),
        federation=FederationConfig(**_filter_fields(FederationConfig, fed_section)) if fed_section else FederationConfig(),
        channels=channels,
        _raw=merged,
    )


def ensure_dirs() -> None:
    """Create config / data / log directories if needed."""
    for d in (CONFIG_DIR, DATA_DIR, LOG_DIR):
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
    errors: list[str] = []
    warnings: list[str] = []

    # Provider checks
    keyless = {"local", "proxy"}
    if config.primary_provider:
        if config.primary_provider.name == "proxy" and not config.primary_provider.base_url:
            errors.append("Proxy provider requires a base_url in config.toml")
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
