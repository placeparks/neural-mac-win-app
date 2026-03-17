"""
NeuralClaw Interactive Configurator — friendly menu-driven setup for all features.

Used by `neuralclaw config` CLI command. Non-tech users can configure everything
without touching config.toml.
"""

from __future__ import annotations

import os
import sys

from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from neuralclaw.config import (
    CONFIG_FILE,
    get_api_key,
    load_config,
    set_api_key,
    update_config,
)

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _header(title: str) -> None:
    console.print(f"\n[bold cyan]{'─' * 50}[/bold cyan]")
    console.print(f"[bold]{title}[/bold]")
    console.print(f"[bold cyan]{'─' * 50}[/bold cyan]\n")


def _pick(prompt: str, options: list[str], current: str | None = None) -> str:
    """Show numbered options and let user pick one."""
    for i, opt in enumerate(options, 1):
        marker = " [green]← current[/green]" if opt == current else ""
        console.print(f"  [cyan]{i}[/cyan]) {opt}{marker}")

    while True:
        choice = Prompt.ask(f"\n{prompt}", default="")
        if not choice.strip():
            return current or options[0]

        # Accept number or text
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1]

        # Fuzzy match by text
        for opt in options:
            if choice.lower() in opt.lower():
                return opt

        console.print(f"[red]Invalid choice. Enter 1-{len(options)}[/red]")


def _toggle(prompt: str, current: bool) -> bool:
    """Yes/no toggle with current value shown."""
    status = "[green]ON[/green]" if current else "[red]OFF[/red]"
    return Confirm.ask(f"{prompt} (currently {status})", default=current)


def _secret_input(prompt: str, current_set: bool = False) -> str | None:
    """Prompt for a secret value. Returns None to skip."""
    if current_set:
        console.print("  [dim]Currently set (hidden). Enter new value or press Enter to keep.[/dim]")
    val = Prompt.ask(f"  {prompt}", default="", show_default=False, password=True)
    return val.strip() if val.strip() else None


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------

def run_configurator() -> None:
    """Interactive configuration menu."""
    while True:
        _header("NeuralClaw Configuration")

        menu = [
            ("1", "Provider", "Switch AI model (OpenAI, Anthropic, local, etc.)"),
            ("2", "Channels", "Telegram, Discord, Slack, WhatsApp, Signal"),
            ("3", "Features", "Toggle features on/off"),
            ("4", "Memory", "Vector search, embeddings, identity"),
            ("5", "Security", "Threat thresholds, shell access, PII filtering"),
            ("6", "Voice & TTS", "Text-to-speech settings"),
            ("7", "Browser", "Web automation settings"),
            ("8", "Integrations", "Google Workspace, Microsoft 365"),
            ("9", "Advanced", "Federation, policy, workspace"),
            ("s", "Status", "Show current config"),
            ("q", "Quit", "Save & exit"),
        ]

        table = Table(show_header=False, box=None, padding=(0, 2))
        for key, name, desc in menu:
            table.add_row(f"[cyan]{key}[/cyan]", f"[bold]{name}[/bold]", f"[dim]{desc}[/dim]")
        console.print(table)

        choice = Prompt.ask("\nChoose", default="q").strip().lower()

        if choice in ("q", "quit", "exit"):
            console.print("[green]Configuration saved.[/green]\n")
            break
        elif choice == "1" or choice == "provider":
            _configure_provider()
        elif choice == "2" or choice == "channels":
            _configure_channels()
        elif choice == "3" or choice == "features":
            _configure_features()
        elif choice == "4" or choice == "memory":
            _configure_memory()
        elif choice == "5" or choice == "security":
            _configure_security()
        elif choice == "6" or choice == "voice":
            _configure_voice()
        elif choice == "7" or choice == "browser":
            _configure_browser()
        elif choice == "8" or choice == "integrations":
            _configure_integrations()
        elif choice == "9" or choice == "advanced":
            _configure_advanced()
        elif choice == "s" or choice == "status":
            _show_status()
        else:
            console.print("[red]Invalid choice.[/red]")


# ---------------------------------------------------------------------------
# 1. Provider
# ---------------------------------------------------------------------------

def _configure_provider() -> None:
    _header("AI Provider Setup")

    config = load_config()
    current_primary = config.primary_provider.name if config.primary_provider else "none"

    console.print(f"Current primary provider: [bold]{current_primary}[/bold]\n")

    providers = {
        "openai": {
            "label": "OpenAI (GPT-5.4, GPT-4.1, o3/o4 reasoning)",
            "needs_key": True,
            "models": [
                # GPT-5 series (latest, Mar 2026)
                "gpt-5.4",              # Flagship — 1.05M ctx, 128K out, best reasoning
                "gpt-5.4-mini",         # Fast + cheap variant
                "gpt-5.4-nano",         # Cheapest GPT-5.4-class
                "gpt-5.4-pro",          # Extra compute for hard problems
                "gpt-5.3-codex",        # Best agentic coding model
                "gpt-5.2",              # Previous GPT-5, still solid
                "gpt-5.2-pro",          # Pro variant
                "gpt-5.2-codex",        # Code-focused
                "gpt-5",               # Original GPT-5 (Aug 2025), 400K ctx
                "gpt-5-mini",           # Compact GPT-5
                "gpt-5-nano",           # Lightweight GPT-5
                # O-series reasoning
                "o4-mini",              # Fast reasoning (Apr 2025)
                "o3",                   # Reasoning flagship (Apr 2025)
                "o3-pro",               # Pro reasoning, extra compute
                "o3-mini",              # Reasoning mini (Jan 2025)
                "o1",                   # Reasoning (Dec 2024)
                "o1-pro",               # Reasoning pro tier
                # GPT-4 series (legacy but still available)
                "gpt-4.1",             # 1M ctx, great instruction following (Apr 2025)
                "gpt-4.1-mini",         # Fast + cheap (Apr 2025)
                "gpt-4.1-nano",         # Cheapest (Apr 2025)
                "gpt-4o",              # Previous flagship
                "gpt-4o-mini",         # Previous mini
                "gpt-4-turbo",          # Legacy turbo
            ],
            "default_model": "gpt-5.4",
        },
        "anthropic": {
            "label": "Anthropic (Claude Opus 4.6, Sonnet 4.6, Haiku 4.5)",
            "needs_key": True,
            "models": [
                # Latest (Feb 2026)
                "claude-opus-4-6",               # Most intelligent, 1M ctx, 128K out
                "claude-sonnet-4-6",             # Best speed+intelligence, 1M ctx, 64K out
                # Current (Oct-Nov 2025)
                "claude-haiku-4-5-20251001",     # Fastest + cheapest, 200K ctx, 64K out
                "claude-opus-4-5-20251101",      # Previous opus, 200K ctx
                "claude-sonnet-4-5-20250929",    # Previous sonnet, 1M ctx
                # Legacy (still available)
                "claude-opus-4-1-20250805",      # Opus 4.1, 200K ctx
                "claude-sonnet-4-20250514",      # Sonnet 4.0, 1M ctx
                "claude-opus-4-20250514",        # Opus 4.0, 200K ctx
            ],
            "default_model": "claude-sonnet-4-6",
        },
        "openrouter": {
            "label": "OpenRouter (access 300+ models with one key)",
            "needs_key": True,
            "models": [
                "anthropic/claude-opus-4-6",
                "anthropic/claude-sonnet-4-6",
                "anthropic/claude-haiku-4-5-20251001",
                "openai/gpt-5.4",
                "openai/gpt-5.4-mini",
                "openai/gpt-5.3-codex",
                "openai/o3",
                "openai/o4-mini",
                "openai/gpt-4.1",
                "google/gemini-2.5-pro-preview",
                "google/gemini-2.5-flash-preview",
                "google/gemini-2.0-flash-001",
                "meta-llama/llama-4-maverick",
                "meta-llama/llama-4-scout",
                "deepseek/deepseek-r1",
                "deepseek/deepseek-v3-0324",
                "mistralai/mistral-large-latest",
                "qwen/qwen3-235b-a22b",
            ],
            "default_model": "anthropic/claude-sonnet-4-6",
        },
        "local": {
            "label": "Local / Ollama (free, runs on your machine)",
            "needs_key": False,
            "models": [
                "qwen3:8b",             # Best local quality/speed
                "qwen3:4b",             # Lighter
                "qwen3.5:2b",           # Ultra-light
                "llama3.3:70b",         # Best open-weight (needs 48GB+)
                "llama3.1:8b",          # Good balance
                "gemma3:12b",           # Google's latest open
                "gemma3:4b",            # Lighter Google
                "mistral:7b",           # Classic
                "deepseek-r1:8b",       # Reasoning model
                "phi-4:14b",            # Microsoft
            ],
            "default_model": "qwen3:8b",
        },
        "proxy": {
            "label": "Custom proxy (self-hosted OpenAI-compatible API)",
            "needs_key": True,
            "models": [],
            "default_model": "gpt-5.4",
        },
    }

    console.print("[bold]Available providers:[/bold]\n")
    provider_names = list(providers.keys())
    selected = _pick("Select provider", provider_names, current=current_primary)

    pinfo = providers[selected]
    updates: dict = {"providers": {"primary": selected}}

    # API key
    if pinfo["needs_key"]:
        existing_key = get_api_key(selected)
        if existing_key:
            masked = existing_key[:8] + "..." + existing_key[-4:]
            console.print(f"\n  API key: [green]{masked}[/green]")
            if Confirm.ask("  Change API key?", default=False):
                new_key = _secret_input("New API key")
                if new_key:
                    set_api_key(selected, new_key)
                    console.print("  [green]Key saved to OS keychain.[/green]")
        else:
            console.print(f"\n  [yellow]No API key set for {selected}.[/yellow]")
            new_key = _secret_input("Enter API key")
            if new_key:
                set_api_key(selected, new_key)
                console.print("  [green]Key saved to OS keychain.[/green]")
            else:
                console.print("  [red]Warning: No key set. Provider won't work without it.[/red]")

    # Model selection
    if pinfo["models"]:
        console.print("\n[bold]Model:[/bold]")
        current_model_cfg = getattr(config, '_raw', {}).get('providers', {}).get(selected, {}).get('model', pinfo['default_model'])
        model = _pick("Choose model (or type custom)", pinfo["models"], current=current_model_cfg)
        updates["providers"][selected] = {"model": model}
    elif selected == "proxy":
        console.print("\n[bold]Proxy setup:[/bold]")
        raw = config._raw.get("providers", {}).get("proxy", {})
        base_url = Prompt.ask("  Base URL", default=raw.get("base_url", "http://localhost:8080/v1"))
        model = Prompt.ask("  Model name", default=raw.get("model", "gpt-4"))
        updates["providers"]["proxy"] = {"base_url": base_url, "model": model}

    # Fallback
    console.print("\n[bold]Fallback providers[/bold] (used if primary fails):")
    other_providers = [p for p in provider_names if p != selected]
    console.print(f"  Available: {', '.join(other_providers)}")
    current_fallback = config._raw.get("providers", {}).get("fallback", [])
    fallback_str = Prompt.ask(
        "  Fallback order (comma-separated, or Enter to keep)",
        default=",".join(current_fallback) if current_fallback else "",
        show_default=True,
    )
    if fallback_str.strip():
        updates["providers"]["fallback"] = [f.strip() for f in fallback_str.split(",") if f.strip()]

    update_config(updates)
    console.print(f"\n[green]Provider set to [bold]{selected}[/bold].[/green]")

    # If switching away from local, verify key works
    if pinfo["needs_key"] and get_api_key(selected):
        console.print("[dim]Tip: Run 'neuralclaw doctor' to verify connectivity.[/dim]")


# ---------------------------------------------------------------------------
# 2. Channels
# ---------------------------------------------------------------------------

def _configure_channels() -> None:
    _header("Channel Setup")

    config = load_config()

    channels = {
        "telegram": {
            "label": "Telegram Bot",
            "secret_key": "telegram",
            "secret_label": "Bot token (from @BotFather)",
            "extra_hint": "Create a bot at https://t.me/BotFather",
        },
        "discord": {
            "label": "Discord Bot",
            "secret_key": "discord",
            "secret_label": "Bot token (from Discord Developer Portal)",
            "extra_hint": "Create at https://discord.com/developers/applications",
        },
        "slack": {
            "label": "Slack Bot",
            "secret_key": "slack",
            "secret_label": "Bot token (xoxb-...)",
            "extra_hint": "Create at https://api.slack.com/apps",
        },
        "whatsapp": {
            "label": "WhatsApp (via Baileys)",
            "secret_key": None,
            "secret_label": None,
            "extra_hint": "QR code pairing — no token needed",
        },
        "signal": {
            "label": "Signal (via signal-cli)",
            "secret_key": None,
            "secret_label": None,
            "extra_hint": "Requires signal-cli installed",
        },
    }

    while True:
        console.print("[bold]Channels:[/bold]\n")
        ch_names = list(channels.keys())
        for i, ch_name in enumerate(ch_names, 1):
            ch_info = channels[ch_name]
            # Check current status
            ch_cfg = None
            for c in config.channels:
                if c.name == ch_name:
                    ch_cfg = c
                    break
            enabled = ch_cfg.enabled if ch_cfg else False
            status = "[green]enabled[/green]" if enabled else "[dim]disabled[/dim]"
            console.print(f"  [cyan]{i}[/cyan]) {ch_info['label']}  {status}")

        console.print("  [cyan]b[/cyan]) Back to main menu")

        choice = Prompt.ask("\nConfigure channel", default="b").strip().lower()
        if choice in ("b", "back", ""):
            break

        idx = None
        if choice.isdigit() and 1 <= int(choice) <= len(ch_names):
            idx = int(choice) - 1
        else:
            for i, name in enumerate(ch_names):
                if choice in name:
                    idx = i
                    break

        if idx is None:
            console.print("[red]Invalid choice.[/red]")
            continue

        ch_name = ch_names[idx]
        ch_info = channels[ch_name]
        _configure_single_channel(ch_name, ch_info, config)
        config = load_config()  # reload


def _configure_single_channel(ch_name: str, ch_info: dict, config) -> None:
    _header(ch_info["label"])

    console.print(f"  [dim]{ch_info['extra_hint']}[/dim]\n")

    ch_cfg = None
    for c in config.channels:
        if c.name == ch_name:
            ch_cfg = c
            break
    currently_enabled = ch_cfg.enabled if ch_cfg else False

    enabled = _toggle("Enable this channel?", currently_enabled)
    updates = {"channels": {ch_name: {"enabled": enabled}}}

    if enabled and ch_info.get("secret_key"):
        existing = get_api_key(ch_info["secret_key"])
        if existing:
            masked = existing[:8] + "..." + existing[-4:]
            console.print(f"\n  Token: [green]{masked}[/green]")
            if Confirm.ask("  Change token?", default=False):
                new_token = _secret_input(ch_info["secret_label"])
                if new_token:
                    set_api_key(ch_info["secret_key"], new_token)
                    console.print("  [green]Token saved.[/green]")
        else:
            console.print("\n  [yellow]No token set.[/yellow]")
            new_token = _secret_input(ch_info["secret_label"])
            if new_token:
                set_api_key(ch_info["secret_key"], new_token)
                console.print("  [green]Token saved.[/green]")
            elif enabled:
                console.print("  [red]Warning: Channel enabled but no token set![/red]")

    if enabled:
        trust_mode = _pick(
            "Trust mode",
            ["auto", "allowlist", "open"],
            current=ch_cfg.trust_mode if ch_cfg else "auto",
        )
        updates["channels"][ch_name]["trust_mode"] = trust_mode

        # Discord extras
        if ch_name == "discord":
            voice = _toggle("Enable voice responses?", ch_cfg.voice_responses if hasattr(ch_cfg, 'voice_responses') else False)
            updates["channels"]["discord"]["voice_responses"] = voice

    update_config(updates)
    status = "[green]enabled[/green]" if enabled else "[red]disabled[/red]"
    console.print(f"\n{ch_info['label']}: {status}")


# ---------------------------------------------------------------------------
# 3. Features
# ---------------------------------------------------------------------------

def _configure_features() -> None:
    _header("Feature Toggles")

    config = load_config()
    feat = config.features

    features = [
        ("vector_memory", "Vector Memory", "Semantic similarity search (finds related memories)", feat.vector_memory),
        ("identity", "User Identity", "Remember who users are across sessions/channels", feat.identity),
        ("vision", "Vision", "Understand images sent in chat", feat.vision),
        ("voice", "Voice / TTS", "Text-to-speech output", feat.voice),
        ("browser", "Browser Control", "Automate web browsing tasks", feat.browser),
        ("desktop", "Desktop Control", "Control mouse/keyboard (advanced)", feat.desktop),
        ("structured_output", "Structured Output", "Enforce JSON schemas on responses", feat.structured_output),
        ("streaming_responses", "Streaming", "Stream responses token-by-token", feat.streaming_responses),
        ("traceline", "Traceline", "Full reasoning trace logging", feat.traceline),
        ("evolution", "Self-Evolution", "Learn and improve from interactions", feat.evolution),
        ("reflective_reasoning", "Deep Thinking", "Multi-step planning (uses more tokens)", feat.reflective_reasoning),
        ("swarm", "Swarm / Agents", "Multi-agent collaboration", feat.swarm),
        ("dashboard", "Web Dashboard", "Admin dashboard on port 7474", feat.dashboard),
        ("a2a_federation", "A2A Federation", "Agent-to-Agent protocol", feat.a2a_federation),
    ]

    console.print("[bold]Toggle features on/off:[/bold]\n")

    # Show current state
    for i, (key, label, desc, current) in enumerate(features, 1):
        status = "[green]ON [/green]" if current else "[red]OFF[/red]"
        console.print(f"  [cyan]{i:2d}[/cyan]) {status}  [bold]{label}[/bold] — [dim]{desc}[/dim]")

    console.print("\n  [cyan] a[/cyan]) Turn all ON")
    console.print("  [cyan] m[/cyan]) Minimal mode (only essentials)")
    console.print("  [cyan] b[/cyan]) Back")

    while True:
        choice = Prompt.ask("\nToggle (number, 'a' for all, 'm' for minimal, 'b' to go back)", default="b").strip().lower()

        if choice in ("b", "back", ""):
            break

        if choice == "a":
            updates = {"features": {f[0]: True for f in features}}
            update_config(updates)
            console.print("[green]All features enabled.[/green]")
            break

        if choice == "m":
            minimal_on = {"vector_memory", "identity", "structured_output", "traceline", "evolution"}
            updates = {"features": {f[0]: (f[0] in minimal_on) for f in features}}
            update_config(updates)
            console.print("[green]Minimal mode: core features only.[/green]")
            break

        if choice.isdigit() and 1 <= int(choice) <= len(features):
            idx = int(choice) - 1
            key, label, desc, current = features[idx]
            new_val = not current
            update_config({"features": {key: new_val}})
            features[idx] = (key, label, desc, new_val)
            status = "[green]ON [/green]" if new_val else "[red]OFF[/red]"
            console.print(f"  {label}: {status}")

            # Special hints
            if key == "desktop" and new_val:
                console.print("  [yellow]Warning: Desktop control can move your mouse and type keys![/yellow]")
            elif key == "browser" and new_val:
                console.print("  [dim]Tip: Configure browser settings with option 7 from main menu.[/dim]")
            elif key == "voice" and new_val:
                console.print("  [dim]Tip: Configure TTS settings with option 6 from main menu.[/dim]")
            continue

        console.print("[red]Invalid choice.[/red]")


# ---------------------------------------------------------------------------
# 4. Memory
# ---------------------------------------------------------------------------

def _configure_memory() -> None:
    _header("Memory Settings")

    config = load_config()
    raw = config._raw.get("memory", {})

    console.print("[bold]Embedding provider[/bold] (for vector similarity search):\n")
    providers = ["local", "openai"]
    current = raw.get("embedding_provider", "local")
    provider = _pick("Embedding provider", providers, current=current)

    updates: dict = {"memory": {"embedding_provider": provider}}

    if provider == "local":
        console.print("\n  [dim]Uses Ollama running locally. Make sure Ollama is installed.[/dim]")
        model = Prompt.ask("  Embedding model", default=raw.get("embedding_model", "nomic-embed-text"))
        dim = IntPrompt.ask("  Embedding dimension", default=raw.get("embedding_dimension", 768))
        updates["memory"]["embedding_model"] = model
        updates["memory"]["embedding_dimension"] = dim
    elif provider == "openai":
        console.print("\n  [dim]Uses OpenAI API. Make sure your OpenAI key is set.[/dim]")
        model = Prompt.ask("  Embedding model", default="text-embedding-3-small")
        dim = IntPrompt.ask("  Embedding dimension", default=1536)
        updates["memory"]["embedding_model"] = model
        updates["memory"]["embedding_dimension"] = dim

    top_k = IntPrompt.ask("\nMax similar results to retrieve", default=raw.get("vector_similarity_top_k", 10))
    updates["memory"]["vector_similarity_top_k"] = top_k

    # Identity settings
    console.print("\n[bold]User Identity:[/bold]")
    id_raw = config._raw.get("identity", {})
    cross = _toggle("Link users across channels (same person on Telegram + Discord)?", id_raw.get("cross_channel", True))
    inject = _toggle("Show user info in prompts (helps personalization)?", id_raw.get("inject_in_prompt", True))
    updates["identity"] = {"cross_channel": cross, "inject_in_prompt": inject}

    update_config(updates)
    console.print("\n[green]Memory settings saved.[/green]")


# ---------------------------------------------------------------------------
# 5. Security
# ---------------------------------------------------------------------------

def _configure_security() -> None:
    _header("Security Settings")

    config = load_config()
    sec = config._raw.get("security", {})

    console.print("[bold]Threat Detection:[/bold]\n")
    console.print("  Messages above the threat threshold trigger extra verification.")
    console.print("  Messages above the block threshold are blocked entirely.\n")

    threat = Prompt.ask("  Threat threshold (0.0-1.0)", default=str(sec.get("threat_threshold", 0.7)))
    block = Prompt.ask("  Block threshold (0.0-1.0)", default=str(sec.get("block_threshold", 0.9)))

    shell = _toggle("Allow shell/code execution?", sec.get("allow_shell_execution", False))
    pii = _toggle("Detect & redact PII in outputs (emails, phone numbers)?", sec.get("output_pii_detection", True))
    output_filter = _toggle("Enable output security filtering?", sec.get("output_filtering", True))

    updates = {
        "security": {
            "threat_threshold": float(threat),
            "block_threshold": float(block),
            "allow_shell_execution": shell,
            "output_pii_detection": pii,
            "output_filtering": output_filter,
        }
    }

    update_config(updates)
    console.print("\n[green]Security settings saved.[/green]")

    if shell:
        console.print("[yellow]Warning: Shell execution enabled. The bot can run commands on your machine.[/yellow]")


# ---------------------------------------------------------------------------
# 6. Voice / TTS
# ---------------------------------------------------------------------------

def _configure_voice() -> None:
    _header("Voice & TTS Settings")

    config = load_config()
    tts = config._raw.get("tts", {})

    enabled = _toggle("Enable text-to-speech?", tts.get("enabled", False))
    updates: dict = {"tts": {"enabled": enabled}, "features": {"voice": enabled}}

    if enabled:
        console.print("\n[bold]TTS Provider:[/bold]\n")
        providers = ["edge-tts", "openai", "elevenlabs", "piper"]
        console.print("  [dim]edge-tts: Free, Microsoft voices, good quality[/dim]")
        console.print("  [dim]openai: Paid, best quality[/dim]")
        console.print("  [dim]elevenlabs: Paid, voice cloning[/dim]")
        console.print("  [dim]piper: Free, local, offline[/dim]\n")

        provider = _pick("TTS provider", providers, current=tts.get("provider", "edge-tts"))
        updates["tts"]["provider"] = provider

        if provider == "openai":
            if not get_api_key("openai"):
                console.print("  [yellow]OpenAI API key needed for TTS.[/yellow]")
        elif provider == "elevenlabs":
            key = _secret_input("ElevenLabs API key")
            if key:
                set_api_key("elevenlabs", key)

        # Voice selection
        voice_defaults = {
            "edge-tts": ["en-US-AriaNeural", "en-US-GuyNeural", "en-GB-SoniaNeural", "en-AU-NatashaNeural"],
            "openai": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
            "elevenlabs": ["rachel", "domi", "bella", "antoni"],
            "piper": ["en_US-lessac-medium"],
        }
        voices = voice_defaults.get(provider, ["default"])
        voice = _pick("Voice", voices, current=tts.get("voice", voices[0]))
        updates["tts"]["voice"] = voice

        speed = Prompt.ask("  Speed (0.5=slow, 1.0=normal, 2.0=fast)", default=str(tts.get("speed", 1.0)))
        updates["tts"]["speed"] = float(speed)

        auto = _toggle("Auto-speak all responses?", tts.get("auto_speak", False))
        updates["tts"]["auto_speak"] = auto

    update_config(updates)
    console.print("\n[green]Voice settings saved.[/green]")


# ---------------------------------------------------------------------------
# 7. Browser
# ---------------------------------------------------------------------------

def _configure_browser() -> None:
    _header("Browser Automation Settings")

    config = load_config()
    br = config._raw.get("browser", {})

    enabled = _toggle("Enable browser control?", br.get("enabled", False))
    updates: dict = {"browser": {"enabled": enabled}, "features": {"browser": enabled}}

    if enabled:
        headless = _toggle("Run headless (no visible browser window)?", br.get("headless", True))
        updates["browser"]["headless"] = headless

        allow_js = _toggle("Allow JavaScript execution?", br.get("allow_js_execution", False))
        updates["browser"]["allow_js_execution"] = allow_js

        chrome_ai = _toggle("Enable Chrome AI (on-device summarization/translation)?", br.get("chrome_ai_enabled", False))
        updates["browser"]["chrome_ai_enabled"] = chrome_ai

        max_steps = IntPrompt.ask("Max steps per browsing task", default=br.get("max_steps_per_task", 20))
        updates["browser"]["max_steps_per_task"] = max_steps

        console.print("\n[bold]Domain restrictions:[/bold]")
        console.print(f"  Currently blocked: {', '.join(br.get('blocked_domains', []))}")
        console.print("  [dim]Internal IPs are always blocked for security.[/dim]")

    update_config(updates)
    console.print("\n[green]Browser settings saved.[/green]")


# ---------------------------------------------------------------------------
# 8. Integrations
# ---------------------------------------------------------------------------

def _configure_integrations() -> None:
    _header("External Integrations")

    while True:
        console.print("  [cyan]1[/cyan]) Google Workspace (Gmail, Calendar, Drive, Docs, Sheets)")
        console.print("  [cyan]2[/cyan]) Microsoft 365 (Outlook, Teams, OneDrive)")
        console.print("  [cyan]b[/cyan]) Back")

        choice = Prompt.ask("\nConfigure", default="b").strip().lower()

        if choice in ("b", "back", ""):
            break
        elif choice == "1":
            _configure_google()
        elif choice == "2":
            _configure_microsoft()


def _configure_google() -> None:
    _header("Google Workspace")

    config = load_config()
    gw = config._raw.get("google_workspace", {})

    console.print("  [dim]Requires a Google Cloud project with APIs enabled.[/dim]")
    console.print("  [dim]Guide: https://developers.google.com/workspace/guides/create-project[/dim]\n")

    enabled = _toggle("Enable Google Workspace?", gw.get("enabled", False))
    updates: dict = {"google_workspace": {"enabled": enabled}}

    if enabled:
        # OAuth token
        existing = get_api_key("google_workspace")
        if existing:
            console.print("  [green]OAuth credentials configured.[/green]")
        else:
            console.print("  [yellow]No OAuth credentials set.[/yellow]")
            cred = _secret_input("Paste OAuth client JSON (or path to credentials.json)")
            if cred:
                set_api_key("google_workspace", cred)

    update_config(updates)
    console.print("\n[green]Google Workspace settings saved.[/green]")


def _configure_microsoft() -> None:
    _header("Microsoft 365")

    config = load_config()
    ms = config._raw.get("microsoft365", {})

    console.print("  [dim]Requires an Azure AD app registration.[/dim]")
    console.print("  [dim]Guide: https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app[/dim]\n")

    enabled = _toggle("Enable Microsoft 365?", ms.get("enabled", False))
    updates: dict = {"microsoft365": {"enabled": enabled}}

    if enabled:
        tenant = Prompt.ask("  Azure Tenant ID", default=ms.get("tenant_id", ""))
        updates["microsoft365"]["tenant_id"] = tenant

        existing = get_api_key("microsoft365")
        if existing:
            console.print("  [green]Client secret configured.[/green]")
        else:
            secret = _secret_input("Client secret")
            if secret:
                set_api_key("microsoft365", secret)

    update_config(updates)
    console.print("\n[green]Microsoft 365 settings saved.[/green]")


# ---------------------------------------------------------------------------
# 9. Advanced
# ---------------------------------------------------------------------------

def _configure_advanced() -> None:
    _header("Advanced Settings")

    while True:
        console.print("  [cyan]1[/cyan]) Federation & swarm networking")
        console.print("  [cyan]2[/cyan]) Policy & rate limits")
        console.print("  [cyan]3[/cyan]) Persona & name")
        console.print("  [cyan]4[/cyan]) Open config.toml in editor")
        console.print("  [cyan]b[/cyan]) Back")

        choice = Prompt.ask("\nConfigure", default="b").strip().lower()

        if choice in ("b", "back", ""):
            break
        elif choice == "1":
            _configure_federation()
        elif choice == "2":
            _configure_policy()
        elif choice == "3":
            _configure_persona()
        elif choice == "4":
            _open_config()


def _configure_federation() -> None:
    _header("Federation & Swarm")

    config = load_config()
    fed = config._raw.get("federation", {})

    enabled = _toggle("Enable federation (connect to other NeuralClaw instances)?", fed.get("enabled", True))
    updates: dict = {"federation": {"enabled": enabled}}

    if enabled:
        port = IntPrompt.ask("  Federation port", default=fed.get("port", 8100))
        updates["federation"]["port"] = port

        name = Prompt.ask("  Node name", default=fed.get("node_name", ""))
        if name:
            updates["federation"]["node_name"] = name

        a2a = _toggle("Enable A2A protocol (Agent-to-Agent)?", fed.get("a2a_enabled", False))
        updates["federation"]["a2a_enabled"] = a2a
        updates["features"] = {"a2a_federation": a2a}

    update_config(updates)
    console.print("\n[green]Federation settings saved.[/green]")


def _configure_policy() -> None:
    _header("Policy & Rate Limits")

    config = load_config()
    pol = config._raw.get("policy", {})

    max_tools = IntPrompt.ask("Max tool calls per request", default=pol.get("max_tool_calls_per_request", 10))
    max_time = IntPrompt.ask("Max request time (seconds)", default=int(pol.get("max_request_wall_seconds", 120)))
    parallel = _toggle("Allow parallel tool execution?", pol.get("parallel_tool_execution", True))

    updates = {
        "policy": {
            "max_tool_calls_per_request": max_tools,
            "max_request_wall_seconds": float(max_time),
            "parallel_tool_execution": parallel,
        }
    }

    update_config(updates)
    console.print("\n[green]Policy settings saved.[/green]")


def _configure_persona() -> None:
    _header("Persona & Name")

    config = load_config()
    gen = config._raw.get("general", {})

    name = Prompt.ask("Bot name", default=gen.get("name", "NeuralClaw"))
    persona = Prompt.ask(
        "Persona (system prompt)",
        default=gen.get("persona", "You are NeuralClaw, a helpful and intelligent AI assistant."),
    )

    update_config({"general": {"name": name, "persona": persona}})
    console.print(f"\n[green]Bot is now named [bold]{name}[/bold].[/green]")


def _open_config() -> None:
    """Open config.toml in the system default editor."""
    import subprocess

    path = str(CONFIG_FILE)
    console.print(f"[dim]Opening {path}...[/dim]")

    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        editor = os.environ.get("EDITOR", "nano")
        subprocess.run([editor, path])


# ---------------------------------------------------------------------------
# Status view
# ---------------------------------------------------------------------------

def _show_status() -> None:
    _header("Current Configuration")

    config = load_config()
    feat = config.features
    raw = config._raw

    # Provider
    primary = raw.get("providers", {}).get("primary", "none")
    model = raw.get("providers", {}).get(primary, {}).get("model", "?")
    has_key = bool(get_api_key(primary)) if primary not in ("local", "proxy") else True
    key_status = "[green]key set[/green]" if has_key else "[red]no key![/red]"
    console.print(f"  Provider:  [bold]{primary}[/bold] ({model}) {key_status}")

    # Channels
    enabled_channels = [c.name for c in config.channels if c.enabled]
    if enabled_channels:
        console.print(f"  Channels:  [green]{', '.join(enabled_channels)}[/green]")
    else:
        console.print("  Channels:  [dim]none enabled[/dim]")

    # Features
    console.print("\n  [bold]Features:[/bold]")
    feature_list = [
        ("Vector Memory", feat.vector_memory),
        ("User Identity", feat.identity),
        ("Vision", feat.vision),
        ("Voice/TTS", feat.voice),
        ("Browser", feat.browser),
        ("Desktop", feat.desktop),
        ("Structured Output", feat.structured_output),
        ("Streaming", feat.streaming_responses),
        ("Traceline", feat.traceline),
        ("Evolution", feat.evolution),
        ("Deep Thinking", feat.reflective_reasoning),
        ("Swarm", feat.swarm),
        ("Dashboard", feat.dashboard),
        ("A2A Federation", feat.a2a_federation),
    ]

    on_features = [name for name, val in feature_list if val]
    off_features = [name for name, val in feature_list if not val]

    if on_features:
        console.print(f"    [green]ON:[/green]  {', '.join(on_features)}")
    if off_features:
        console.print(f"    [dim]OFF: {', '.join(off_features)}[/dim]")

    # Security
    sec = raw.get("security", {})
    console.print(f"\n  Security:  threat={sec.get('threat_threshold', 0.7)} block={sec.get('block_threshold', 0.9)} shell={'[red]allowed[/red]' if sec.get('allow_shell_execution') else '[green]denied[/green]'}")

    console.print()
