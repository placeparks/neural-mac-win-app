"""
NeuralClaw CLI — Beautiful terminal interface.

Commands:
    neuralclaw init     Interactive setup wizard
    neuralclaw chat     Interactive terminal chat session
    neuralclaw gateway  Start the full agent with all configured channels
    neuralclaw status   Show current configuration and status
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.text import Text
from rich.markdown import Markdown
from rich.table import Table

from neuralclaw import __version__
from neuralclaw.config import (
    CONFIG_FILE,
    NeuralClawConfig,
    ensure_dirs,
    get_api_key,
    load_config,
    save_default_config,
    set_api_key,
)

import os

if sys.platform == "win32":
    # Force UTF-8 for Windows environments to support the ASCII art banner
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    os.environ["PYTHONIOENCODING"] = "utf-8"

console = Console()


# ---------------------------------------------------------------------------
# ASCII Art Banner
# ---------------------------------------------------------------------------

BANNER = """
[bold cyan]
 ███╗   ██╗███████╗██╗   ██╗██████╗  █████╗ ██╗      ██████╗██╗      █████╗ ██╗    ██╗
 ████╗  ██║██╔════╝██║   ██║██╔══██╗██╔══██╗██║     ██╔════╝██║     ██╔══██╗██║    ██║
 ██╔██╗ ██║█████╗  ██║   ██║██████╔╝███████║██║     ██║     ██║     ███████║██║ █╗ ██║
 ██║╚██╗██║██╔══╝  ██║   ██║██╔══██╗██╔══██║██║     ██║     ██║     ██╔══██║██║███╗██║
 ██║ ╚████║███████╗╚██████╔╝██║  ██║██║  ██║███████╗╚██████╗███████╗██║  ██║╚███╔███╔╝
 ╚═╝  ╚═══╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝
[/bold cyan]
[dim]The Self-Evolving Cognitive Agent Framework[/dim]
"""


# ---------------------------------------------------------------------------
# CLI Group
# ---------------------------------------------------------------------------

@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
)
@click.version_option(version=__version__)
def main() -> None:
    """NeuralClaw command line interface.

    Common flows:
      neuralclaw init
      neuralclaw session setup chatgpt
      neuralclaw session setup claude
      neuralclaw channels setup
      neuralclaw chat -p chatgpt_app
      neuralclaw gateway

    Base installation already includes the Python dependencies for all built-in
    providers and channels. Some integrations still require external runtimes,
    such as Playwright browsers, Node.js for WhatsApp, or signal-cli for Signal.
    """
    pass


# ---------------------------------------------------------------------------
# Config command — interactive configurator
# ---------------------------------------------------------------------------

@main.command()
@click.argument("section", required=False, default=None)
def config(section: str | None) -> None:
    """Interactive configuration — change any setting without editing files.

    \b
    Quick shortcuts:
        neuralclaw config               Full interactive menu
        neuralclaw config provider       Switch AI provider
        neuralclaw config channels       Set up messaging channels
        neuralclaw config features       Toggle features on/off
        neuralclaw config security       Security settings
        neuralclaw config voice          TTS / voice settings
        neuralclaw config browser        Browser automation
        neuralclaw config integrations   Google / Microsoft 365
        neuralclaw config advanced       Federation, policy, persona
    """
    console.print(BANNER)

    from neuralclaw.configurator import (
        run_configurator,
        _configure_provider,
        _configure_channels,
        _configure_features,
        _configure_memory,
        _configure_security,
        _configure_voice,
        _configure_browser,
        _configure_integrations,
        _configure_advanced,
        _show_status,
    )

    shortcuts = {
        "provider": _configure_provider,
        "channels": _configure_channels,
        "features": _configure_features,
        "memory": _configure_memory,
        "security": _configure_security,
        "voice": _configure_voice,
        "browser": _configure_browser,
        "integrations": _configure_integrations,
        "advanced": _configure_advanced,
        "status": _show_status,
    }

    if section:
        key = section.lower().strip()
        if key in shortcuts:
            shortcuts[key]()
        else:
            # Fuzzy match
            for k, fn in shortcuts.items():
                if key in k:
                    fn()
                    return
            console.print(f"[red]Unknown section '{section}'[/red]")
            console.print(f"[dim]Available: {', '.join(shortcuts.keys())}[/dim]")
    else:
        run_configurator()


# ---------------------------------------------------------------------------
# Init command
# ---------------------------------------------------------------------------

@main.command()
def init() -> None:
    """Interactive setup wizard — create config and set API keys."""
    console.print(BANNER)
    console.print(Panel("Welcome to NeuralClaw Setup", style="bold green"))

    ensure_dirs()
    config_path = save_default_config()
    console.print(f"\n✅ Config file: [cyan]{config_path}[/cyan]")

    # API key setup
    console.print("\n[bold]Configure LLM Provider[/bold]")
    console.print("NeuralClaw needs at least one LLM provider to function.\n")

    providers = [
        ("openai", "OpenAI (GPT-4o, GPT-4o-mini)"),
        ("anthropic", "Anthropic (Claude 3.5 Sonnet)"),
        ("openrouter", "OpenRouter (multi-model)"),
        ("chatgpt_app", "ChatGPT App (browser session)"),
        ("claude_app", "Claude App (browser session)"),
        ("proxy", "Proxy (Self-hosted ChatGPT/Claude reverse proxy)"),
        ("local", "Local (Ollama — no API key needed)"),
    ]

    for name, label in providers:
        existing = get_api_key(name)
        if existing:
            masked = existing[:8] + "..." + existing[-4:]
            console.print(f"  {label}: [green]configured[/green] ({masked})")
        else:
            if name in ("local", "proxy", "chatgpt_app", "claude_app"):
                if name == "local":
                    hint = "run [cyan]neuralclaw local setup[/cyan] to detect Ollama models"
                elif name == "proxy":
                    hint = "run [cyan]neuralclaw proxy setup[/cyan] to configure"
                else:
                    session_name = "chatgpt" if name == "chatgpt_app" else "claude"
                    hint = f"run [cyan]neuralclaw session setup {session_name}[/cyan] to configure"
                console.print(f"  {label}: [dim]{hint}[/dim]")
                continue

            key = Prompt.ask(
                f"  {label} API key (Enter to skip)",
                default="",
                show_default=False,
            )
            if key.strip():
                set_api_key(name, key.strip())
                console.print(f"    [green]✓ Saved to OS keychain[/green]")
            else:
                console.print(f"    [dim]skipped[/dim]")

    console.print(Panel(
        "[green]Setup complete![/green]\n\n"
        "  [cyan]neuralclaw config[/cyan]           Configure everything (interactive menu)\n"
        "  [cyan]neuralclaw config provider[/cyan]  Switch AI provider\n"
        "  [cyan]neuralclaw config channels[/cyan]  Set up messaging channels\n"
        "  [cyan]neuralclaw chat[/cyan]             Start interactive chat\n"
        "  [cyan]neuralclaw run[/cyan]              Start gateway (auto-restarts)\n"
        "  [cyan]neuralclaw doctor[/cyan]           Check system health",
        title="What's Next",
        style="bold",
    ))

    # Offer to jump into configurator
    if Confirm.ask("\nConfigure more settings now?", default=True):
        from neuralclaw.configurator import run_configurator
        run_configurator()


# ---------------------------------------------------------------------------
# Chat command
# ---------------------------------------------------------------------------

@main.command()
@click.option(
    "--provider",
    "-p",
    default=None,
    help=(
        "Provider override "
        "(openai, anthropic, openrouter, proxy, chatgpt_app, claude_app, local)"
    ),
)
@click.option("--dev", is_flag=True, default=False, help="Enable developer mode.")
def chat(provider: str | None, dev: bool) -> None:
    """Interactive terminal chat session with optional provider override."""
    console.print(BANNER)
    asyncio.run(_chat_loop(provider, dev_mode=dev))


async def _chat_loop(provider_override: str | None = None, dev_mode: bool = False) -> None:
    """Main interactive chat loop."""
    from neuralclaw.gateway import NeuralClawGateway

    config = load_config()
    gateway = NeuralClawGateway(
        config,
        provider_override=provider_override,
        dev_mode=dev_mode,
        config_path=str(CONFIG_FILE),
    )
    await gateway.initialize()

    provider_name = gateway._provider.name if gateway._provider else "none"
    console.print(Panel(
        f"Provider: [cyan]{provider_name}[/cyan] | "
        f"Skills: [cyan]{gateway._skills.count}[/cyan] | "
        f"Type [bold red]exit[/bold red] or [bold red]quit[/bold red] to stop",
        title="🧠 NeuralClaw Chat",
        style="bold cyan",
    ))
    console.print()

    while True:
        try:
            user_input = Prompt.ask("[bold green]You[/bold green]")
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input.strip():
            continue

        if user_input.strip().lower() in ("exit", "quit", "/quit", "/exit"):
            break

        console.print()  # Spacing

        try:
            response = await gateway.process_message(
                content=user_input,
                author_id="cli_user",
                author_name="User",
                channel_id="cli",
                channel_type_name="CLI",
            )

            console.print(Panel(
                Markdown(response),
                title="🧠 NeuralClaw",
                style="bold cyan",
                padding=(1, 2),
            ))
            console.print()

        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}\n")

    await gateway.stop()
    console.print("\n[dim]Goodbye! 👋[/dim]\n")


# ---------------------------------------------------------------------------
# Local command group
# ---------------------------------------------------------------------------

@main.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
)
def local() -> None:
    """Manage the local OpenAI-compatible provider, such as Ollama."""
    pass


@local.command("setup")
def local_setup() -> None:
    """Detect local Ollama models and save the selected model to config."""
    asyncio.run(_local_setup())


async def _local_setup() -> None:
    from neuralclaw.config import update_config

    console.print(BANNER)
    console.print(Panel("Local Provider Setup", style="bold cyan"))

    base_url = Prompt.ask("  Base URL", default="http://localhost:11434/v1").strip()
    tags_url = base_url.removesuffix("/v1") + "/api/tags"
    models = await _fetch_ollama_models(tags_url)
    recommended = "qwen3.5:2b"
    default_model = recommended if recommended in models else (models[0] if models else recommended)

    if models:
        console.print("\n[bold]Detected Ollama models[/bold]")
        for name in models:
            marker = " [green](recommended)[/green]" if name == default_model else ""
            console.print(f"  - [cyan]{name}[/cyan]{marker}")
    else:
        console.print(
            "\n[yellow]Could not query Ollama model tags.[/yellow]\n"
            "[dim]If Ollama is running, you can still enter the model name manually.[/dim]"
        )

    model = Prompt.ask("  Model", default=default_model).strip() or default_model

    update_config({
        "providers": {
            "local": {
                "model": model,
                "base_url": base_url,
            },
        },
    })
    console.print(f"\n[green]Saved[/green] local provider as [cyan]{model}[/cyan] at [cyan]{base_url}[/cyan]")

    set_primary = Prompt.ask("  Set local as your primary provider? (y/N)", default="n")
    if set_primary.lower() == "y":
        update_config({"providers": {"primary": "local"}})
        console.print("[green]Saved[/green] local set as primary provider")


@local.command("status")
def local_status() -> None:
    """Show the configured local model and currently available Ollama models."""
    asyncio.run(_local_status())


async def _local_status() -> None:
    config = load_config()
    raw = config._raw.get("providers", {}).get("local", {})
    base_url = raw.get("base_url", "http://localhost:11434/v1")
    model = raw.get("model", "qwen3.5:2b")
    tags_url = base_url.removesuffix("/v1") + "/api/tags"
    models = await _fetch_ollama_models(tags_url)

    table = Table(title="Local Provider", style="cyan")
    table.add_column("Setting", style="bold")
    table.add_column("Value")
    table.add_row("Base URL", base_url)
    table.add_row("Configured model", model)
    table.add_row("Ollama status", "[green]reachable[/green]" if models else "[yellow]not detected[/yellow]")
    table.add_row("Detected models", ", ".join(models) if models else "[dim]none[/dim]")
    console.print(table)
    console.print()


async def _fetch_ollama_models(tags_url: str) -> list[str]:
    import aiohttp

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(tags_url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
    except Exception:
        return []

    models = [item.get("name", "") for item in data.get("models", []) if item.get("name")]
    return sorted(models)


def _parse_since_value(value: str | None) -> float | None:
    """Parse durations like 7d, 12h, or 30m into a unix timestamp cutoff."""
    if not value:
        return None
    raw = value.strip().lower()
    if raw.endswith("d"):
        return time.time() - (float(raw[:-1]) * 86400)
    if raw.endswith("h"):
        return time.time() - (float(raw[:-1]) * 3600)
    if raw.endswith("m"):
        return time.time() - (float(raw[:-1]) * 60)
    return float(raw)


def _http_probe(url: str) -> tuple[str, str]:
    """Best-effort local HTTP probe for status surfaces."""
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            status = str(response.status)
            body = response.read(200).decode("utf-8", errors="replace").strip()
            return status, body[:120] or "ok"
    except Exception as exc:
        return "down", str(exc)


# ---------------------------------------------------------------------------
# Channels command group
# ---------------------------------------------------------------------------

@main.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
)
def channels() -> None:
    """Manage messaging channels.

    Use `setup` for first-run credentials, `list` to inspect configured
    integrations, `test` to validate connectivity, and `connect whatsapp` for
    QR-based WhatsApp pairing.
    """
    pass


@channels.command("setup")
def channels_setup() -> None:
    """Guided setup wizard for all messaging channels."""
    console.print(BANNER)
    console.print(Panel("Channel Configuration", style="bold cyan"))

    channel_defs = [
        ("telegram", "Telegram Bot", "Bot token from @BotFather"),
        ("discord", "Discord Bot", "Bot token from Discord Developer Portal"),
        ("slack_bot", "Slack Bot", "Bot User OAuth Token (xoxb-...)"),
        ("slack_app", "Slack App", "App-Level Token (xapp-...)"),
        ("whatsapp", "WhatsApp", "Run neuralclaw channels connect whatsapp to pair via QR"),
        ("signal", "Signal", "Phone number (+1234567890)"),
    ]

    console.print("\nConfigure which channels NeuralClaw should connect to.\n")

    for key, label, hint in channel_defs:
        existing = get_api_key(key)
        if existing:
            masked = existing[:6] + "..." + existing[-4:] if len(existing) > 10 else existing
            console.print(f"  {label}: [green]configured[/green] ({masked})")
            change = Prompt.ask(f"    Update? (y/N)", default="n")
            if change.lower() != "y":
                continue

        value = Prompt.ask(f"  {label} — {hint} (Enter to skip)", default="", show_default=False)
        if value.strip():
            set_api_key(key, value.strip())
            console.print(f"    [green]✓ Saved to OS keychain[/green]")
        else:
            console.print(f"    [dim]skipped[/dim]")

    console.print(Panel(
        "[green]Channel setup complete![/green]\n\n"
        "Run [cyan]neuralclaw gateway[/cyan] to start with all configured channels.",
        style="bold",
    ))


@channels.command("list")
def channels_list() -> None:
    """Show configured channels and their status."""
    table = Table(title="Channel Status", style="cyan")
    table.add_column("Channel", style="bold")
    table.add_column("Status")
    table.add_column("Token")

    channel_keys = [
        ("telegram", "Telegram"),
        ("discord", "Discord"),
        ("slack_bot", "Slack Bot"),
        ("slack_app", "Slack App"),
        ("whatsapp", "WhatsApp"),
        ("signal", "Signal"),
    ]

    for key, label in channel_keys:
        token = get_api_key(key)
        if token:
            masked = token[:6] + "..." + token[-4:] if len(token) > 10 else token
            table.add_row(label, "[green]✓ configured[/green]", masked)
        else:
            table.add_row(label, "[dim]not set[/dim]", "—")

    console.print(table)


@channels.command("test")
@click.argument("channel_name", required=False)
def channels_test(channel_name: str | None) -> None:
    """Test channel connectivity before going live."""
    asyncio.run(_test_channels(channel_name))


async def _test_channels(channel_name: str | None) -> None:
    config = load_config()
    from neuralclaw.gateway import NeuralClawGateway

    gw = NeuralClawGateway(config)
    targets = config.channels
    if channel_name:
        targets = [ch for ch in targets if ch.name == channel_name]
        if not targets:
            console.print(f"[red]Channel '{channel_name}' not found in config.[/red]")
            return

    table = Table(title="Channel Connectivity Test", style="cyan")
    table.add_column("Channel", style="bold")
    table.add_column("Status")
    table.add_column("Details")

    builders = {
        "telegram": gw._build_telegram_channel,
        "discord": gw._build_discord_channel,
        "slack": gw._build_slack_channel,
        "whatsapp": gw._build_whatsapp_channel,
        "signal": gw._build_signal_channel,
    }

    for ch in targets:
        if not ch.enabled or not ch.token:
            table.add_row(ch.name, "[dim]skipped[/dim]", "not enabled or no token")
            continue
        builder = builders.get(ch.name)
        if not builder:
            table.add_row(ch.name, "[dim]skipped[/dim]", "no builder")
            continue
        try:
            adapter = builder(ch)
            if adapter:
                ok, msg = await adapter.test_connection()
                if ok:
                    table.add_row(ch.name, "[green]OK[/green]", msg)
                else:
                    table.add_row(ch.name, "[red]FAIL[/red]", msg)
            else:
                table.add_row(ch.name, "[yellow]WARN[/yellow]", "Builder returned None")
        except Exception as e:
            table.add_row(ch.name, "[red]ERROR[/red]", str(e))

    console.print(table)


@channels.command("add")
@click.argument("channel_name")
def channels_add(channel_name: str) -> None:
    """Add and configure a channel interactively."""
    known = {
        "telegram": "Bot token from @BotFather",
        "discord": "Bot token from Discord Developer Portal",
        "slack_bot": "Bot User OAuth Token (xoxb-...)",
        "whatsapp": "Session ID or auth directory path",
        "signal": "Phone number (+1234567890)",
    }
    hint = known.get(channel_name, "Token or credential")
    value = Prompt.ask(f"  {channel_name} — {hint}", default="", show_default=False)
    if value.strip():
        set_api_key(channel_name, value.strip())
        console.print(f"  [green]✓[/green] Saved '{channel_name}' to keychain")
    else:
        console.print("  [dim]Cancelled — no value provided.[/dim]")


@channels.command("remove")
@click.argument("channel_name")
def channels_remove(channel_name: str) -> None:
    """Remove a channel's stored credentials."""
    from neuralclaw.config import _set_secret
    # Overwrite with empty to effectively remove
    _set_secret(f"{channel_name}_api_key", "")
    console.print(f"  [green]✓[/green] Removed '{channel_name}' credentials")


@channels.command("connect")
@click.argument("channel_name")
def channels_connect(channel_name: str) -> None:
    """Interactive pairing for channels that need it (e.g. WhatsApp QR)."""
    if channel_name != "whatsapp":
        console.print(
            f"[dim]'{channel_name}' doesn't need interactive pairing.[/dim]\n"
            f"[dim]Use [cyan]neuralclaw channels add {channel_name}[/cyan] instead.[/dim]"
        )
        return
    asyncio.run(_connect_whatsapp())


async def _connect_whatsapp() -> None:
    """Interactive WhatsApp QR pairing flow."""

    from neuralclaw.channels.whatsapp_baileys import (
        BaileysWhatsAppAdapter,
        ensure_baileys_installed,
        render_qr_terminal,
    )
    from neuralclaw.config import update_config

    console.print(Panel(
        "[bold]WhatsApp QR Pairing[/bold]\n\n"
        "This will start the WhatsApp bridge and display a QR code.\n"
        "Open WhatsApp on your phone → Linked Devices → Link a Device\n"
        "Then scan the QR code shown below.",
        style="bold cyan",
    ))

    # ── Auto-install bridge dependencies ─────────────────────────────
    try:
        console.print("[dim]Checking bridge dependencies...[/dim]")
        ensure_baileys_installed()
        console.print("[green]✓[/green] Bridge dependencies ready\n")
    except RuntimeError as e:
        console.print(f"[bold red]{e}[/bold red]\n")
        return

    # ── Auth directory ───────────────────────────────────────────────
    default_auth = str(Path.home() / ".neuralclaw" / "whatsapp_auth")
    auth_dir = Prompt.ask(
        "  Auth directory",
        default=default_auth,
    )

    # Ensure auth dir exists
    Path(auth_dir).mkdir(parents=True, exist_ok=True)

    qr_received = asyncio.Event()

    def on_qr(data: str) -> None:
        qr_received.set()
        render_qr_terminal(data, console)

    adapter = BaileysWhatsAppAdapter(auth_dir=auth_dir, on_qr=on_qr)

    console.print("\n[dim]Starting WhatsApp bridge...[/dim]")

    try:
        await adapter.start()

        # Give bridge a moment to start — then check if it already crashed
        await asyncio.sleep(1)
        if adapter._process and adapter._process.returncode is not None:
            stderr = ""
            if adapter._process.stderr:
                stderr = (await adapter._process.stderr.read()).decode(errors="replace")
            console.print(
                f"[bold red]WhatsApp bridge crashed on startup.[/bold red]\n"
                f"[dim]{stderr[:500] if stderr else 'No error output.'}[/dim]\n"
            )
            return

        # Wait for connection (timeout 120s)
        console.print("[dim]Waiting for QR code...[/dim]\n")
        try:
            await asyncio.wait_for(adapter._connected.wait(), timeout=120)
        except asyncio.TimeoutError:
            # Check if bridge died during wait
            stderr = ""
            if adapter._process and adapter._process.returncode is not None:
                if adapter._process.stderr:
                    stderr = (await adapter._process.stderr.read()).decode(errors="replace")
            if stderr:
                console.print(
                    f"[bold red]WhatsApp bridge crashed.[/bold red]\n"
                    f"[dim]{stderr[:500]}[/dim]\n"
                )
            else:
                console.print(
                    "\n[yellow]Timed out waiting for connection.[/yellow]\n"
                    "[dim]Run this command again to get a new QR code.[/dim]\n"
                )
            return

        # Check if we got a fatal error instead of a real connection
        if adapter._fatal:
            console.print(
                f"\n[bold red]WhatsApp bridge failed:[/bold red] {adapter._fatal_message}\n"
                "[dim]Check your network connection and Node.js version (>= 18).[/dim]\n"
                "[dim]If this persists, try deleting the auth directory and re-pairing.[/dim]\n"
            )
            return

        # Connected!
        console.print("\n[bold green]Connected to WhatsApp![/bold green]\n")

        # Save auth dir to keychain
        set_api_key("whatsapp", auth_dir)

        # Enable channel in config
        update_config({"channels": {"whatsapp": {"enabled": True}}})

        console.print(f"  [green]✓[/green] Auth saved to keychain")
        console.print(f"  [green]✓[/green] WhatsApp enabled in config")
        console.print(
            "\n[dim]Run [cyan]neuralclaw gateway[/cyan] to start receiving messages.[/dim]\n"
        )

    finally:
        await adapter.stop()


# ---------------------------------------------------------------------------
# Proxy command group
# ---------------------------------------------------------------------------

@main.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
)
def proxy() -> None:
    """Configure an OpenAI-compatible proxy provider.

    This path is useful for self-hosted relays, normalized session bridges, or
    gateways such as LiteLLM, one-api, or similar OpenAI-compatible endpoints.
    """
    pass


@proxy.command("setup")
def proxy_setup() -> None:
    """Guided setup for connecting a reverse proxy (ChatGPT/Claude sessions)."""
    asyncio.run(_proxy_setup())


async def _proxy_setup() -> None:
    from neuralclaw.config import update_config

    console.print(BANNER)
    console.print(Panel(
        "[bold]Reverse Proxy Setup[/bold]\n\n"
        "A reverse proxy lets you route NeuralClaw through your own\n"
        "ChatGPT Plus, Claude Pro, or any OpenAI-compatible endpoint.\n\n"
        "[dim]Supported proxies:[/dim]\n"
        "  one-api / new-api    Multi-provider gateway\n"
        "  chatgpt-to-api       ChatGPT session → OpenAI API\n"
        "  LobeChat             Self-hosted AI gateway\n"
        "  Any OpenAI-compatible endpoint (LiteLLM, vLLM, etc.)",
        style="bold cyan",
    ))

    # 1. Base URL
    console.print("\n[bold]Step 1: Proxy URL[/bold]")
    console.print("[dim]The /v1 endpoint of your proxy (e.g. http://localhost:3040/v1)[/dim]\n")
    base_url = Prompt.ask("  Base URL", default="")
    if not base_url.strip():
        console.print("[dim]Cancelled — no URL provided.[/dim]")
        return
    base_url = base_url.strip()

    # 2. Model
    console.print("\n[bold]Step 2: Model[/bold]")
    console.print("[dim]The model name your proxy serves (depends on your proxy config)[/dim]\n")
    model = Prompt.ask("  Model name", default="gpt-4")

    # 3. API key (optional)
    console.print("\n[bold]Step 3: API Key (optional)[/bold]")
    console.print("[dim]Some proxies require an auth token. Leave empty if not needed.[/dim]\n")
    api_key = Prompt.ask("  API key (Enter to skip)", default="", show_default=False)

    # 4. Connectivity test
    console.print("\n[dim]Testing connectivity...[/dim]")
    from neuralclaw.providers.proxy import ProxyProvider
    test_provider = ProxyProvider(base_url=base_url, model=model, api_key=api_key.strip())

    reachable = await test_provider.is_available()
    if reachable:
        console.print("[bold green]  Connected![/bold green] Proxy is reachable.\n")
    else:
        console.print("[yellow]  Could not reach proxy.[/yellow]")
        save_anyway = Prompt.ask("  Save configuration anyway? (y/N)", default="n")
        if save_anyway.lower() != "y":
            console.print("[dim]Cancelled.[/dim]")
            return
        console.print()

    # 5. Save to config.toml
    update_config({
        "providers": {
            "proxy": {
                "model": model,
                "base_url": base_url,
            },
        },
    })
    console.print(f"  [green]✓[/green] Saved proxy config to config.toml")

    # 6. Save API key to keychain
    if api_key.strip():
        set_api_key("proxy", api_key.strip())
        console.print(f"  [green]✓[/green] API key saved to keychain")

    # 7. Set as primary?
    set_primary = Prompt.ask(
        "\n  Set proxy as your primary provider? (y/N)",
        default="n",
    )
    if set_primary.lower() == "y":
        update_config({"providers": {"primary": "proxy"}})
        console.print(f"  [green]✓[/green] Proxy set as primary provider")

    console.print(Panel(
        "[green]Proxy configured![/green]\n\n"
        "  [cyan]neuralclaw proxy status[/cyan]  Check proxy status\n"
        "  [cyan]neuralclaw chat -p proxy[/cyan]  Chat using proxy\n"
        "  [cyan]neuralclaw gateway[/cyan]        Start with all channels",
        title="What's Next",
        style="bold",
    ))


@proxy.command("status")
def proxy_status() -> None:
    """Show current proxy configuration and connectivity."""
    asyncio.run(_proxy_status())


async def _proxy_status() -> None:
    config = load_config()

    table = Table(title="Proxy Configuration", style="cyan")
    table.add_column("Setting", style="bold")
    table.add_column("Value")

    # Find proxy provider config
    proxy_cfg = None
    if config.primary_provider and config.primary_provider.name == "proxy":
        proxy_cfg = config.primary_provider
    else:
        for fb in config.fallback_providers:
            if fb.name == "proxy":
                proxy_cfg = fb
                break

    if not proxy_cfg:
        # Load from raw config
        raw_proxy = config._raw.get("providers", {}).get("proxy", {})
        base_url = raw_proxy.get("base_url", "")
        model = raw_proxy.get("model", "gpt-4")
    else:
        base_url = proxy_cfg.base_url
        model = proxy_cfg.model

    api_key = get_api_key("proxy")
    is_primary = config.primary_provider and config.primary_provider.name == "proxy"

    table.add_row("Base URL", base_url or "[dim]not configured[/dim]")
    table.add_row("Model", model)
    table.add_row("API Key", (api_key[:8] + "..." + api_key[-4:]) if api_key else "[dim]not set[/dim]")
    table.add_row("Primary Provider", "[green]yes[/green]" if is_primary else "[dim]no[/dim]")

    # Connectivity check
    if base_url:
        from neuralclaw.providers.proxy import ProxyProvider
        test_provider = ProxyProvider(base_url=base_url, model=model, api_key=api_key or "")
        reachable = await test_provider.is_available()
        table.add_row("Status", "[green]reachable[/green]" if reachable else "[red]unreachable[/red]")
    else:
        table.add_row("Status", "[dim]no base_url configured[/dim]")

    console.print(table)

    if not base_url:
        console.print("\n[dim]Run [cyan]neuralclaw proxy setup[/cyan] to configure.[/dim]")
    console.print()


# ---------------------------------------------------------------------------
# Session command group
# ---------------------------------------------------------------------------

@main.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
)
def session() -> None:
    """Manage direct ChatGPT and Claude browser sessions.

    Run `session setup <provider>` once to create the managed profile, then use
    `session status`, `session diagnose`, `session open`, or `session repair`
    when needed.
    """
    pass


@session.command("setup")
@click.argument("provider_name", type=click.Choice(["chatgpt", "claude"]))
def session_setup(provider_name: str) -> None:
    """Set up a managed browser session."""
    asyncio.run(_session_setup(provider_name))


async def _session_setup(provider_name: str) -> None:
    from neuralclaw.config import SESSION_DIR, update_config

    provider_key = "chatgpt_app" if provider_name == "chatgpt" else "claude_app"
    default_profile = str(SESSION_DIR / provider_name)
    default_url = "https://chatgpt.com/" if provider_name == "chatgpt" else "https://claude.ai/chats"

    console.print(BANNER)
    console.print(Panel(
        f"[bold]{provider_name.title()} App Session Setup[/bold]\n\n"
        "This uses a managed persistent browser profile.\n"
        "You will log in once and NeuralClaw will reuse that local profile.\n\n"
        "[dim]Use headed mode for first login.[/dim]\n"
        "[dim]Recommended browser channel for ChatGPT: chrome[/dim]",
        style="bold cyan",
    ))

    profile_dir = Prompt.ask("  Profile directory", default=default_profile).strip()
    model = Prompt.ask("  Preferred model", default="auto").strip() or "auto"
    headless = Prompt.ask("  Run headless by default? (y/N)", default="n").strip().lower() == "y"
    browser_channel = Prompt.ask(
        "  Browser channel (optional: chrome, msedge, or blank for Playwright Chromium)",
        default="",
        show_default=False,
    ).strip()

    update_config({
        "providers": {
            provider_key: {
                "model": model,
                "profile_dir": profile_dir,
                "headless": headless,
                "browser_channel": browser_channel,
                "site_url": default_url,
            },
        },
    })

    runtime = _build_session_runtime(provider_key)
    await runtime.login()
    console.print("\n[dim]Complete the login/subscription flow in the opened browser, then return here.[/dim]")
    Prompt.ask("  Press Enter after login", default="", show_default=False)
    health = await runtime.health()
    await runtime.close()

    if health.logged_in:
        console.print(f"  [green]✓[/green] {provider_name.title()} session is ready")
    else:
        console.print(f"  [yellow]⚠[/yellow] Session saved but not fully ready: {health.message}")
        if health.recommendation:
            console.print(f"  [dim]{health.recommendation}[/dim]")

    if not health.logged_in:
        return
    set_primary = Prompt.ask(f"  Set {provider_key} as primary provider? (y/N)", default="n")
    if set_primary.lower() == "y":
        update_config({"providers": {"primary": provider_key}})
        console.print(f"  [green]✓[/green] {provider_key} set as primary provider")


@session.command("status")
def session_status() -> None:
    """Show managed session health."""
    asyncio.run(_session_status())


async def _session_status() -> None:
    from neuralclaw.session.auth import AuthManager

    config = load_config()
    table = Table(title="App Session Status", style="cyan")
    table.add_column("Provider", style="bold")
    table.add_column("Profile")
    table.add_column("Status")
    table.add_column("Token Auth")
    table.add_column("Details")

    for provider_key in ("chatgpt_app", "claude_app"):
        raw = config._raw.get("providers", {}).get(provider_key, {})
        profile_dir = raw.get("profile_dir", "")

        # Token auth status
        token_provider = "chatgpt" if "chatgpt" in provider_key else "claude"
        token_health = AuthManager(token_provider).health_check()
        if token_health.get("has_token") and token_health.get("valid"):
            token_col = f"[green]{token_health['token_type']}[/green]"
        elif token_health.get("has_token"):
            token_col = "[red]expired[/red]"
        else:
            token_col = "[dim]none[/dim]"

        if not profile_dir:
            table.add_row(provider_key, "[dim]not configured[/dim]", "[dim]n/a[/dim]", token_col, "")
            continue
        runtime = _build_session_runtime(provider_key)
        health = await runtime.health()
        await runtime.close()
        if health.state == "auth_rejected":
            status = "[red]auth rejected[/red]"
        elif health.state == "challenge":
            status = "[yellow]challenge[/yellow]"
        elif health.logged_in:
            status = "[green]ready[/green]"
        else:
            status = "[yellow]login required[/yellow]"
        table.add_row(provider_key, profile_dir, status, token_col, health.message)
    console.print(table)
    console.print("[dim]Use `neuralclaw session auth <provider>` for token-based auth.[/dim]")
    console.print("[dim]Use `neuralclaw session diagnose <provider>` for detailed guidance.[/dim]")
    console.print()


@session.command("login")
@click.argument("provider_name", type=click.Choice(["chatgpt", "claude"]))
def session_login(provider_name: str) -> None:
    """Reopen the managed browser profile for login."""
    asyncio.run(_session_login(provider_name))


async def _session_login(provider_name: str) -> None:
    provider_key = "chatgpt_app" if provider_name == "chatgpt" else "claude_app"
    runtime = _build_session_runtime(provider_key)
    await runtime.login()
    console.print(f"[green]Opened {provider_name} session profile.[/green]")


@session.command("repair")
@click.argument("provider_name", type=click.Choice(["chatgpt", "claude"]))
def session_repair(provider_name: str) -> None:
    """Restart the managed browser runtime for a session."""
    asyncio.run(_session_repair(provider_name))


async def _session_repair(provider_name: str) -> None:
    provider_key = "chatgpt_app" if provider_name == "chatgpt" else "claude_app"
    runtime = _build_session_runtime(provider_key)
    await runtime.repair()
    health = await runtime.health()
    await runtime.close()
    console.print(f"[green]Repair complete:[/green] {health.message}")
    if health.recommendation:
        console.print(f"[dim]{health.recommendation}[/dim]")


@session.command("open")
@click.argument("provider_name", type=click.Choice(["chatgpt", "claude"]))
def session_open(provider_name: str) -> None:
    """Open the managed profile for manual login/bootstrap and then diagnose it."""
    asyncio.run(_session_open(provider_name))


async def _session_open(provider_name: str) -> None:
    provider_key = "chatgpt_app" if provider_name == "chatgpt" else "claude_app"
    runtime = _build_session_runtime(provider_key)
    await runtime.login()
    console.print(
        "[dim]Complete login or any upstream verification in the opened browser, "
        "then return here.[/dim]"
    )
    Prompt.ask("  Press Enter when the provider looks ready", default="", show_default=False)
    health = await runtime.health()
    await runtime.close()
    _print_session_health(provider_name, health)


@session.command("diagnose")
@click.argument("provider_name", type=click.Choice(["chatgpt", "claude"]))
def session_diagnose(provider_name: str) -> None:
    """Inspect the managed session and explain common failure states."""
    asyncio.run(_session_diagnose(provider_name))


async def _session_diagnose(provider_name: str) -> None:
    provider_key = "chatgpt_app" if provider_name == "chatgpt" else "claude_app"
    runtime = _build_session_runtime(provider_key)
    health = await runtime.health()
    await runtime.close()
    _print_session_health(provider_name, health)


def _print_session_health(provider_name: str, health) -> None:
    console.print(Panel(
        f"[bold]{provider_name.title()} Session[/bold]\n\n"
        f"State: [cyan]{health.state}[/cyan]\n"
        f"Message: {health.message}\n"
        f"Recommendation: {health.recommendation or 'none'}",
        style="bold cyan",
    ))


@session.command("auth")
@click.argument("provider_name", type=click.Choice(["chatgpt", "claude", "google", "microsoft"]))
@click.option("--stealth", is_flag=True, help="Use stealth mode (URL pasting) instead of opening a local browser.")
def session_auth(provider_name: str, stealth: bool) -> None:
    """Set up token-based authentication (managed cookie or session key)."""
    asyncio.run(_session_auth(provider_name, stealth))


async def _session_auth(provider_name: str, stealth: bool = False) -> None:
    from neuralclaw.config import SESSION_DIR, update_config
    from neuralclaw.session.auth import (
        AuthManager,
        ChatGPTAuthFlow,
        ClaudeAuthFlow,
        redact_token,
    )

    console.print(BANNER)
    config = load_config()

    if provider_name in {"google", "microsoft"}:
        from neuralclaw.config import _set_secret

        is_google = provider_name == "google"
        title = "Google Workspace" if is_google else "Microsoft 365"
        console.print(Panel(
            f"[bold]{title} Token Setup[/bold]\n\n"
            "Paste an OAuth access token or refresh token from your existing auth flow.\n"
            "NeuralClaw stores it in the local keychain and enables the matching skill config.",
            style="bold cyan",
        ))
        access_token = Prompt.ask("  Access token (Enter to skip)", default="", show_default=False).strip()
        refresh_token = Prompt.ask("  Refresh token (Enter to skip)", default="", show_default=False).strip()
        if not access_token and not refresh_token:
            console.print("  [dim]No credential provided.[/dim]")
            return
        if is_google:
            if access_token:
                _set_secret("google_oauth_access", access_token)
            if refresh_token:
                _set_secret("google_oauth_refresh", refresh_token)
            update_config({"google_workspace": {"enabled": True}})
        else:
            if access_token:
                _set_secret("microsoft365_oauth_access", access_token)
            if refresh_token:
                _set_secret("microsoft_oauth_refresh", refresh_token)
            update_config({"microsoft365": {"enabled": True}})
        console.print(f"  [green]✓[/green] Stored {title} credentials")
        return

    if provider_name == "chatgpt":
        provider_cfg = config._raw.get("providers", {}).get("chatgpt_token", {})
        profile_dir = provider_cfg.get("profile_dir") or str(SESSION_DIR / "chatgpt")
        console.print(Panel(
            "[bold]ChatGPT Token Authentication[/bold]\n\n"
            "[cyan]Option 1:[/cyan] Managed browser login — opens the managed profile for\n"
            "  manual ChatGPT login, then extracts the session cookie. [green](Recommended)[/green]\n\n"
            "[cyan]Option 2:[/cyan] Cookie extraction — extracts session cookie from an\n"
            "  existing managed browser profile. Requires prior browser login.\n\n"
            "[cyan]Option 3:[/cyan] Skip — use an OpenAI API key instead.",
            style="bold cyan",
        ))

        choice = Prompt.ask(
            "  Choose auth method",
            choices=["1", "2", "3"],
            default="1",
        )

        auth = AuthManager("chatgpt")

        if choice == "1":
            if stealth:
                console.print("\n  [dim]Initiating stealth OAuth flow (URL pasting)...[/dim]")
                try:
                    flow = ChatGPTAuthFlow()
                    cred = await flow.oauth_flow(stealth=True)
                    auth.save_credential(cred)
                    ttl = int(cred.expires_at - __import__('time').time()) if cred.expires_at > 0 else 0
                    console.print(f"  [green]✓[/green] Session token saved (expires in {ttl}s)")
                    console.print(f"  [dim]Token: {redact_token(cred.access_token)}[/dim]")
                except Exception as e:
                    console.print(f"  [red]✗[/red] Stealth OAuth failed: {e}")
                    return
            else:
                console.print("\n  [dim]Opening managed browser for ChatGPT login...[/dim]")
                console.print("  [dim]If Cloudflare appears, complete it in the browser and keep this window open.[/dim]")
                try:
                    flow = ChatGPTAuthFlow()
                    seen_states: set[str] = set()

                    def _status_update(state: str, message: str, recommendation: str) -> None:
                        if state in seen_states:
                            return
                        seen_states.add(state)
                        if state == "challenge":
                            console.print("  [yellow]Cloudflare challenge detected.[/yellow]")
                            console.print("  [dim]Tick the checkbox or finish the challenge in the opened browser. NeuralClaw will keep waiting.[/dim]")
                        elif state == "login_required":
                            console.print("  [dim]Waiting for ChatGPT login in the managed browser...[/dim]")
                        elif state == "ready":
                            console.print("  [green]Session looks ready. Capturing the cookie...[/green]")
                        elif recommendation:
                            console.print(f"  [dim]{message}. {recommendation}[/dim]")

                    cred = await flow.guided_browser_login_with_status(profile_dir, _status_update)
                    auth.save_credential(cred)
                    ttl = int(cred.expires_at - __import__('time').time()) if cred.expires_at > 0 else 0
                    console.print(f"  [green]✓[/green] Session cookie saved (expires in {ttl}s)")
                    console.print(f"  [dim]Token: {redact_token(cred.access_token)}[/dim]")
                except Exception as e:
                    console.print(f"  [red]✗[/red] ChatGPT login failed: {e}")
                    console.print("  [dim]Trying managed-profile cookie recovery...[/dim]")
                    try:
                        flow = ChatGPTAuthFlow()
                        cred = await flow.extract_cookie_from_profile(profile_dir)
                        auth.save_credential(cred)
                        console.print("  [green]✓[/green] Recovered ChatGPT session cookie from profile")
                        console.print(f"  [dim]Token: {redact_token(cred.access_token)}[/dim]")
                    except Exception:
                        console.print("  [dim]Try option 2 (cookie extraction) or 3 (API key).[/dim]")
                        return

        elif choice == "2":
            console.print(f"\n  [dim]Extracting cookie from profile: {profile_dir}[/dim]")
            try:
                flow = ChatGPTAuthFlow()
                cred = await flow.extract_cookie_from_profile(profile_dir)
                auth.save_credential(cred)
                console.print(f"  [green]✓[/green] Session cookie saved")
                console.print(f"  [dim]Token: {redact_token(cred.access_token)}[/dim]")
            except Exception as e:
                console.print(f"  [red]✗[/red] Cookie extraction failed: {e}")
                console.print("  [dim]Run `neuralclaw session login chatgpt` first, then retry.[/dim]")
                return
        else:
            console.print("  [dim]Skipped. Run `neuralclaw init` to set an OpenAI API key.[/dim]")
            return

        health = auth.health_check()
        _print_token_health(health)

        set_primary = Prompt.ask("  Set chatgpt_token as primary provider? (y/N)", default="n")
        if set_primary.lower() == "y":
            update_config({"providers": {"primary": "chatgpt_token"}})
            console.print("  [green]✓[/green] chatgpt_token set as primary provider")

    else:  # claude
        provider_cfg = config._raw.get("providers", {}).get("claude_token", {})
        profile_dir = provider_cfg.get("profile_dir") or str(SESSION_DIR / "claude")

        if stealth:
            console.print("\n[Stealth Auth] Claude session key extraction")
            console.print("Anthropic does not offer OAuth. To authenticate, you must manually provide a sessionKey.")
            console.print("1. Open https://claude.ai in your browser and log in.")
            console.print("2. Open Developer Tools (F12) -> Application -> Cookies.")
            console.print("3. Copy the value of the [bold]sessionKey[/bold] cookie.")
            try:
                session_key = Prompt.ask("\n  Paste your Claude sessionKey here").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[red]✗[/red] cancelled.")
                return
            
            if not session_key:
                console.print("  [red]✗[/red] No session key provided.")
                return
            
            from neuralclaw.session.auth import TokenCredential
            cred = TokenCredential(
                access_token=session_key,
                expires_at=__import__("time").time() + 86400 * 30,
                token_type="session_key",
                provider="claude"
            )
            auth = AuthManager("claude")
            auth.save_credential(cred)
            console.print("\n  [green]✓[/green] Session key saved")
            console.print(f"  [dim]Token: {redact_token(cred.access_token)}[/dim]")
            health = auth.health_check()
            _print_token_health(health)
            return

        console.print(Panel(
            "[bold]Claude Token Authentication[/bold]\n\n"
            "Anthropic does not offer OAuth for consumer accounts.\n"
            "NeuralClaw extracts the session key from a browser login.\n\n"
            "[cyan]Option 1:[/cyan] Extract session key — opens a browser for one-time login,\n"
            "  then extracts the session key automatically.\n\n"
            "[cyan]Option 2:[/cyan] Skip — use an Anthropic API key instead.",
            style="bold cyan",
        ))

        choice = Prompt.ask(
            "  Choose auth method",
            choices=["1", "2"],
            default="1",
        )

        auth = AuthManager("claude")

        if choice == "1":
            console.print("\n  [dim]Opening browser for login...[/dim]")
            try:
                flow = ClaudeAuthFlow()
                cred = await flow.guided_browser_login(profile_dir)
                auth.save_credential(cred)
                days_left = max(0, int((cred.expires_at - __import__("time").time()) / 86400))
                console.print(f"  [green]✓[/green] Session key saved (~{days_left} days until expiry)")
                console.print(f"  [dim]Token: {redact_token(cred.access_token)}[/dim]")
            except Exception as e:
                console.print(f"  [red]✗[/red] Session key extraction failed: {e}")
                return
        else:
            console.print("  [dim]Skipped. Run `neuralclaw init` to set an Anthropic API key.[/dim]")
            return

        health = auth.health_check()
        _print_token_health(health)

        set_primary = Prompt.ask("  Set claude_token as primary provider? (y/N)", default="n")
        if set_primary.lower() == "y":
            update_config({"providers": {"primary": "claude_token"}})
            console.print("  [green]✓[/green] claude_token set as primary provider")

    console.print()


@session.command("refresh")
@click.argument("provider_name", type=click.Choice(["chatgpt", "claude"]))
def session_refresh(provider_name: str) -> None:
    """Force-refresh a token credential."""
    asyncio.run(_session_refresh(provider_name))


async def _session_refresh(provider_name: str) -> None:
    from neuralclaw.config import SESSION_DIR
    from neuralclaw.session.auth import AuthManager, redact_token

    auth = AuthManager(provider_name)
    health = auth.health_check()
    config = load_config()
    provider_cfg = config._raw.get("providers", {}).get(f"{provider_name}_token", {})
    profile_dir = provider_cfg.get("profile_dir") or str(SESSION_DIR / provider_name)

    try:
        new_cred = await auth.force_refresh(profile_dir)
        console.print(f"[green]✓[/green] Token refreshed: {redact_token(new_cred.access_token)}")
    except Exception as e:
        console.print(f"[red]✗[/red] Refresh failed: {e}")
        console.print(f"[dim]Run `neuralclaw session auth {provider_name}` to re-authenticate.[/dim]")


def _print_token_health(health: dict) -> None:
    """Print token health info."""
    status = "[green]valid[/green]" if health.get("valid") else "[red]invalid[/red]"
    token_type = health.get("token_type", "unknown")
    ttl = health.get("ttl_seconds")
    if ttl is not None:
        if ttl > 86400:
            ttl_str = f"{int(ttl / 86400)} days"
        elif ttl > 3600:
            ttl_str = f"{int(ttl / 3600)} hours"
        else:
            ttl_str = f"{int(ttl)} seconds"
    else:
        ttl_str = "unknown"

    console.print(f"\n  Token status: {status}")
    console.print(f"  Type: {token_type}")
    console.print(f"  Time to expiry: {ttl_str}")
    if health.get("needs_refresh"):
        console.print("  [yellow]⚠ Refresh recommended[/yellow]")


def _build_session_runtime(provider_key: str):
    from neuralclaw.session.runtime import ManagedBrowserSession, SessionRuntimeConfig

    config = load_config()
    raw = config._raw.get("providers", {}).get(provider_key, {})
    site_url = raw.get("site_url") or ("https://chatgpt.com/" if provider_key == "chatgpt_app" else "https://claude.ai/chats")
    profile_dir = raw.get("profile_dir") or str(Path.home() / ".neuralclaw" / "sessions" / provider_key.replace("_app", ""))
    return ManagedBrowserSession(SessionRuntimeConfig(
        provider=provider_key,
        profile_dir=profile_dir,
        site_url=site_url,
        model=raw.get("model", "auto"),
        headless=bool(raw.get("headless", False)),
        browser_channel=raw.get("browser_channel", ""),
    ))


# ---------------------------------------------------------------------------
# Doctor / Repair commands
# ---------------------------------------------------------------------------

@main.command()
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option("--fix", is_flag=True, help="Apply repairable fixes before reporting.")
def doctor(json_output: bool, fix: bool) -> None:
    """Diagnose all subsystems — config, providers, channels, memory, bus."""
    console.print(BANNER)
    console.print(Panel(f"NeuralClaw Doctor v{__version__}", style="bold cyan"))

    import platform as _platform
    import shutil as _shutil
    from pathlib import Path as _Path

    try:
        config = load_config()
    except Exception:
        config = None

    from neuralclaw.health import HealthChecker, CheckStatus, RepairEngine
    from neuralclaw.service import service_status

    fixes: list[str] = []
    if fix:
        engine = RepairEngine(config)
        fixes = engine.run_all()
        try:
            config = load_config()
        except Exception:
            config = None

    checker = HealthChecker(config)
    report = checker.run_all()

    system_checks: list[dict[str, str]] = []
    disk_target = _Path.home() / ".neuralclaw"
    disk = _shutil.disk_usage(disk_target if disk_target.exists() else _Path.home())
    system_checks.append({"name": "Python", "status": "OK", "message": sys.version.split()[0]})
    system_checks.append({"name": "Platform", "status": "OK", "message": f"{_platform.system()} ({_platform.machine() or 'unknown'})"})
    system_checks.append({"name": "Disk", "status": "OK", "message": f"{disk.free // (1024**3)} GB free at {disk_target}"})
    system_checks.append({
        "name": "sqlite-vec",
        "status": "OK" if config and config.memory.vector_memory else "WARN",
        "message": "Vector memory enabled" if config and config.memory.vector_memory else "Vector memory disabled",
    })

    section_map: dict[str, list] = {
        "system": system_checks,
        "config": [c for c in report.checks if c.name.startswith("Config") or c.name == "Config dir"],
        "providers": [c for c in report.checks if c.name.startswith("Provider")],
        "memory": [c for c in report.checks if "Memory DB" in c.name or c.name == "Data dir"],
        "channels": [c for c in report.checks if c.name.startswith("Channel")],
        "security": [
            {"name": "Threat screener", "status": "OK", "message": "Initialized" if config else "Config unavailable"},
            {"name": "Output filter", "status": "OK" if config and config.security.output_filtering else "WARN", "message": "Enabled" if config and config.security.output_filtering else "Disabled"},
            {"name": "Canary tokens", "status": "OK" if config and config.security.canary_tokens else "WARN", "message": "Active" if config and config.security.canary_tokens else "Disabled"},
            {"name": "Audit logging", "status": "OK" if config and config.audit.enabled else "WARN", "message": "Active" if config and config.audit.enabled else "Disabled"},
        ],
        "services": [
            {"name": "Service", "status": "OK" if service_status() == "running" else "WARN", "message": service_status()}
        ],
    }

    if json_output:
        import json
        data = {
            "healthy": report.healthy,
            "ok": report.ok_count,
            "warnings": report.warn_count,
            "failures": report.fail_count,
            "fixes": fixes,
            "sections": section_map,
            "checks": [
                {"name": c.name, "status": c.status.name, "message": c.message, "repairable": c.repairable}
                for c in report.checks
            ],
        }
        console.print_json(json.dumps(data))
        return

    status_style = {
        CheckStatus.OK: "[green]OK[/green]",
        CheckStatus.WARN: "[yellow]WARN[/yellow]",
        CheckStatus.FAIL: "[red]FAIL[/red]",
        CheckStatus.SKIP: "[dim]SKIP[/dim]",
    }
    icon_map = {"OK": "✓", "WARN": "⚠", "FAIL": "✗", "SKIP": "·"}

    def _render_section(title: str, items: list) -> None:
        console.print(f"\n[bold]{title}[/bold]")
        for item in items:
            if isinstance(item, dict):
                status = item["status"]
                style = {"OK": "green", "WARN": "yellow", "FAIL": "red", "SKIP": "dim"}.get(status, "dim")
                console.print(f"  [{style}]{icon_map.get(status, '·')}[/{style}] {item['name']} — {item['message']}")
            else:
                console.print(
                    f"  {status_style[item.status]} {item.name} — {item.message}"
                    + (f"\n    [dim]→ {item.repair_action}[/dim]" if item.repairable and item.repair_action else "")
                )

    for title, items in [
        ("System", section_map["system"]),
        ("Config", section_map["config"]),
        ("Providers", section_map["providers"]),
        ("Memory", section_map["memory"]),
        ("Channels", section_map["channels"]),
        ("Security", section_map["security"]),
        ("Services", section_map["services"]),
    ]:
        _render_section(title, items)

    if fixes:
        console.print("\n[bold]Auto-fix[/bold]")
        for item in fixes:
            console.print(f"  [green]✓[/green] {item}")

    summary_style = "green" if report.healthy else "red"
    console.print(
        f"\n[bold {summary_style}]Summary:[/bold {summary_style}] "
        f"{report.warn_count} warnings, {report.fail_count} errors"
    )


@main.command()
@click.option("--dry-run", is_flag=True, help="Show what would be fixed without changing anything")
@click.option("--backup/--no-backup", default=True, help="Backup config before repair")
def repair(dry_run: bool, backup: bool) -> None:
    """Fix common issues — corrupt DBs, stale auth, broken config."""
    console.print(BANNER)
    console.print(Panel("NeuralClaw Repair", style="bold yellow"))

    try:
        config = load_config()
    except Exception:
        config = None

    if dry_run:
        from neuralclaw.health import HealthChecker
        checker = HealthChecker(config)
        report = checker.run_all()
        console.print("\n[dim]Dry run — no changes will be made.[/dim]")
        for check in report.repairable:
            console.print(f"  Would fix: [bold]{check.name}[/bold] — {check.repair_action}")
        if not report.repairable:
            console.print("  [green]Nothing to repair.[/green]")
        console.print()
        return

    if backup:
        from neuralclaw.config import backup_config
        bp = backup_config()
        if bp:
            console.print(f"  [green]Backed up config to {bp}[/green]")

    from neuralclaw.health import RepairEngine
    engine = RepairEngine(config)
    fixes = engine.run_all()

    if fixes:
        console.print("\n[bold]Repairs performed:[/bold]")
        for fix in fixes:
            console.print(f"  [green]✓[/green] {fix}")
    else:
        console.print("\n[green]Nothing to repair — system is healthy.[/green]")

    console.print("\n[dim]Run [cyan]neuralclaw doctor[/cyan] to verify.[/dim]\n")


# ---------------------------------------------------------------------------
# Gateway command
# ---------------------------------------------------------------------------

@main.command()
@click.option("--federation-port", default=None, type=int, help="Override federation port.")
@click.option("--dashboard-port", default=None, type=int, help="Override dashboard port.")
@click.option("--web-port", default=None, type=int, help="Override web chat port.")
@click.option("--name", default=None, help="Override node name.")
@click.option("--seed", default=None, help="Seed node to join (e.g. http://localhost:8100).")
@click.option("--dev", is_flag=True, default=False, help="Enable developer mode with hot config reload.")
@click.option("--watchdog", is_flag=True, default=False, help="Auto-restart on crash (keeps gateway alive forever).")
@click.option("--max-restarts", default=0, type=int, help="Max restarts before giving up (0=unlimited, default=0).")
@click.option("--restart-delay", default=5, type=int, help="Seconds to wait before restart (default=5).")
def gateway(federation_port, dashboard_port, web_port, name, seed, dev, watchdog, max_restarts, restart_delay) -> None:
    """Start the full agent with all configured channels.

    Use --watchdog to keep the gateway running forever with automatic crash recovery.
    """
    console.print(BANNER)

    if watchdog:
        _run_watchdog(
            federation_port=federation_port,
            dashboard_port=dashboard_port,
            web_port=web_port,
            node_name=name,
            seed_node=seed,
            dev_mode=dev,
            max_restarts=max_restarts,
            restart_delay=restart_delay,
        )
    else:
        asyncio.run(_run_gateway(
            federation_port=federation_port,
            dashboard_port=dashboard_port,
            web_port=web_port,
            node_name=name,
            seed_node=seed,
            dev_mode=dev,
        ))


def _run_watchdog(
    federation_port: int | None = None,
    dashboard_port: int | None = None,
    web_port: int | None = None,
    node_name: str | None = None,
    seed_node: str | None = None,
    dev_mode: bool = False,
    max_restarts: int = 0,
    restart_delay: int = 5,
) -> None:
    """Watchdog loop — delegates to service.run_gateway_blocking() for a single
    implementation of the crash-recovery loop.  CLI overrides are applied by
    wrapping _run_gateway() so the shared loop still picks them up."""
    from neuralclaw.service import run_gateway_blocking

    console.print(Panel(
        f"[bold green]Watchdog mode active[/bold green]\n"
        f"Max restarts: {'unlimited' if max_restarts == 0 else max_restarts}  |  "
        f"Restart delay: {restart_delay}s",
        title="Gateway Watchdog",
        style="green",
    ))

    # Monkey-patch the gateway builder so CLI overrides (ports, name, seed) are
    # honoured by the shared watchdog in service.py.
    import neuralclaw.service as _svc
    _original = _svc._run_gateway_async

    async def _patched() -> None:
        await _run_gateway(
            federation_port=federation_port,
            dashboard_port=dashboard_port,
            web_port=web_port,
            node_name=node_name,
            seed_node=seed_node,
            dev_mode=dev_mode,
        )

    _svc._run_gateway_async = _patched  # type: ignore[assignment]
    try:
        run_gateway_blocking(watchdog=True, max_restarts=max_restarts)
    finally:
        _svc._run_gateway_async = _original  # type: ignore[assignment]


async def _run_gateway(
    federation_port: int | None = None,
    dashboard_port: int | None = None,
    web_port: int | None = None,
    node_name: str | None = None,
    seed_node: str | None = None,
    dev_mode: bool = False,
) -> None:
    """Run the full gateway with channels."""
    from neuralclaw.gateway import NeuralClawGateway

    config = load_config()

    # Apply CLI overrides
    if federation_port is not None:
        config.federation.port = federation_port
    if dashboard_port is not None:
        config.dashboard_port = dashboard_port
    if node_name is not None:
        config.federation.node_name = node_name
    if seed_node is not None:
        if seed_node not in config.federation.seed_nodes:
            config.federation.seed_nodes.append(seed_node)

    gw = NeuralClawGateway(config, dev_mode=dev_mode, config_path=str(CONFIG_FILE))
    gw.build_channels(web_port=web_port or 8081)

    try:
        await gw.run_forever()
    except KeyboardInterrupt:
        await gw.stop()


# ---------------------------------------------------------------------------
# Run command — one-step "just launch it"
# ---------------------------------------------------------------------------

@main.command()
@click.option("--web-port", default=None, type=int, help="Override web chat port.")
@click.option("--no-watchdog", is_flag=True, default=False, help="Disable auto-restart.")
def run(web_port, no_watchdog) -> None:
    """One-step launch — init if needed, then start gateway with watchdog.

    This is the simplest way to start NeuralClaw:

        neuralclaw run

    It will create a config if none exists, then start the gateway
    with automatic crash recovery (watchdog) enabled by default.
    """
    console.print(BANNER)

    # Auto-init if no config
    try:
        load_config()
        console.print("[green]Config found.[/green]")
    except Exception:
        console.print("[yellow]No config found — running first-time setup...[/yellow]\n")
        ensure_dirs()
        save_default_config()
        console.print("[green]Default config created. Edit ~/.neuralclaw/config.toml to customize.[/green]\n")

    # Doctor quick-check
    try:
        from neuralclaw.health import HealthChecker
        config = load_config()
        checker = HealthChecker(config)
        report = checker.run_all()
        if report.healthy:
            console.print("[green]Health check: all OK[/green]\n")
        else:
            console.print(f"[yellow]Health check: {report.fail_count} issue(s) — run 'neuralclaw doctor' for details[/yellow]\n")
    except Exception:
        pass

    if no_watchdog:
        asyncio.run(_run_gateway(web_port=web_port))
    else:
        _run_watchdog(
            web_port=web_port,
            max_restarts=0,
            restart_delay=5,
        )


# ---------------------------------------------------------------------------
# Status command
# ---------------------------------------------------------------------------

@main.command()
def status() -> None:
    """Show current configuration and status."""
    console.print(BANNER)

    config = load_config()
    from neuralclaw.service import service_status

    table = Table(title="NeuralClaw Configuration", style="cyan")
    table.add_column("Setting", style="bold")
    table.add_column("Value")

    table.add_row("Config File", str(CONFIG_FILE))
    table.add_row("Name", config.name)
    table.add_row("Log Level", config.log_level)
    table.add_row("Service", service_status())

    # Providers
    providers = ["openai", "anthropic", "openrouter", "chatgpt_app", "claude_app", "proxy", "local"]
    for p in providers:
        key = get_api_key(p)
        status_str = "[green]✓ configured[/green]" if key else "[dim]not set[/dim]"
        if p in ("local", "proxy", "chatgpt_app", "claude_app"):
            if p in ("chatgpt_app", "claude_app"):
                profile = config._raw.get("providers", {}).get(p, {}).get("profile_dir", "")
                status_str = "[green]session configured[/green]" if profile else "[dim]not configured[/dim]"
            else:
                status_str = "[dim]no key needed[/dim]"
        table.add_row(f"Provider: {p}", status_str)

    table.add_row("Primary Provider", config.primary_provider.name if config.primary_provider else "none")

    # Channels (unified — all channels now in config.channels)
    for ch in config.channels:
        trust_mode = ch.trust_mode or "auto"
        ch_status = f"[green]enabled[/green] ({trust_mode})" if ch.enabled else f"[dim]disabled[/dim] ({trust_mode})"
        table.add_row(f"Channel: {ch.name}", ch_status)

    # Security
    table.add_row("Threat Threshold", str(config.security.threat_threshold))
    table.add_row("Block Threshold", str(config.security.block_threshold))
    table.add_row("Shell Execution", "allowed" if config.security.allow_shell_execution else "denied")

    console.print(table)
    live_table = Table(title="Runtime Endpoints", style="green")
    live_table.add_column("Endpoint", style="bold")
    live_table.add_column("Status")
    live_table.add_column("Details")
    for route in ("health", "ready", "metrics"):
        status_code, detail = _http_probe(f"http://127.0.0.1:{config.dashboard_port}/{route}")
        live_table.add_row(route, status_code, detail)
    console.print(live_table)
    console.print()


# ---------------------------------------------------------------------------
# Audit command group
# ---------------------------------------------------------------------------

@main.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
)
def audit() -> None:
    """Inspect tool audit logs and forensic replay data."""
    pass


@audit.command("list")
@click.option("--tool", default=None, help="Filter by tool name.")
@click.option("--user", "user_id", default=None, help="Filter by canonical user id.")
@click.option("--since", default=None, help="Only include records newer than e.g. 7d, 12h, 30m.")
@click.option("--denied", is_flag=True, help="Show denied actions only.")
@click.option("--limit", default=20, type=int, show_default=True, help="Maximum records to show.")
def audit_list(tool: str | None, user_id: str | None, since: str | None, denied: bool, limit: int) -> None:
    """List recent audit records."""
    asyncio.run(_audit_list(tool=tool, user_id=user_id, since=since, denied=denied, limit=limit))


async def _audit_list(tool: str | None, user_id: str | None, since: str | None, denied: bool, limit: int) -> None:
    from neuralclaw.cortex.action.audit import AuditLogger

    config = load_config()
    logger = AuditLogger(config=config.audit)
    await logger.initialize()
    records = await logger.search(
        tool=tool,
        user_id=user_id,
        since=_parse_since_value(since),
        denied_only=denied,
        limit=limit,
    )

    table = Table(title="Audit Records", style="cyan")
    table.add_column("Time", style="bold")
    table.add_column("Request")
    table.add_column("Tool")
    table.add_column("User")
    table.add_column("Decision")
    table.add_column("Preview")

    for record in records:
        decision = "[green]allow[/green]" if record.allowed else "[red]deny[/red]"
        preview = record.denied_reason or record.result_preview or record.args_preview
        table.add_row(
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.timestamp)),
            record.request_id or "—",
            record.skill_name or "—",
            record.user_id or "—",
            decision,
            preview[:80],
        )

    if records:
        console.print(table)
    else:
        console.print("[dim]No audit records matched the filters.[/dim]")


@audit.command("show")
@click.argument("request_id")
def audit_show(request_id: str) -> None:
    """Show the full action sequence for a request id."""
    asyncio.run(_audit_show(request_id))


async def _audit_show(request_id: str) -> None:
    from neuralclaw.cortex.action.audit import AuditLogger

    config = load_config()
    logger = AuditLogger(config=config.audit)
    await logger.initialize()
    records = await logger.get_trace_actions(request_id)

    if not records:
        console.print(f"[dim]No audit records found for request {request_id}.[/dim]")
        return

    table = Table(title=f"Audit Trace {request_id}", style="cyan")
    table.add_column("Time", style="bold")
    table.add_column("Tool")
    table.add_column("Decision")
    table.add_column("Args")
    table.add_column("Result")

    for record in records:
        table.add_row(
            time.strftime("%H:%M:%S", time.localtime(record.timestamp)),
            record.skill_name or "—",
            "allow" if record.allowed else f"deny: {record.denied_reason}",
            record.args_preview[:60] or "—",
            record.result_preview[:60] or "—",
        )

    console.print(table)


@audit.command("export")
@click.option(
    "--format",
    "export_format",
    default="jsonl",
    type=click.Choice(["jsonl", "csv", "cef"], case_sensitive=False),
    show_default=True,
    help="Export format.",
)
@click.option("--since", default=None, help="Only include records newer than e.g. 7d, 12h, 30m.")
@click.option("--output", default=None, help="Destination file. Defaults to audit-export.<format>.")
def audit_export(export_format: str, since: str | None, output: str | None) -> None:
    """Export audit records for offline review or SIEM ingestion."""
    asyncio.run(_audit_export(export_format=export_format, since=since, output=output))


async def _audit_export(export_format: str, since: str | None, output: str | None) -> None:
    from neuralclaw.cortex.action.audit import AuditLogger

    config = load_config()
    logger = AuditLogger(config=config.audit)
    await logger.initialize()
    out = Path(output) if output else Path.cwd() / f"audit-export.{export_format.lower()}"
    count = await logger.export(
        str(out),
        format=export_format,
        since=_parse_since_value(since),
    )
    console.print(f"[green]Exported[/green] {count} audit records to [cyan]{out}[/cyan]")


@audit.command("stats")
def audit_stats() -> None:
    """Show audit denial and usage statistics."""
    asyncio.run(_audit_stats())


async def _audit_stats() -> None:
    from neuralclaw.cortex.action.audit import AuditLogger

    config = load_config()
    logger = AuditLogger(config=config.audit)
    await logger.initialize()
    stats = await logger.stats()

    table = Table(title="Audit Stats", style="cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Total records", str(stats["total_records"]))
    table.add_row("Denied records", str(stats["denied_records"]))
    table.add_row("Denial rate", f"{stats['denial_rate']:.1%}")
    table.add_row("Top tools", ", ".join(f"{name} ({count})" for name, count in stats["top_tools"]) or "—")
    table.add_row("Top users", ", ".join(f"{name} ({count})" for name, count in stats["top_users"]) or "—")
    console.print(table)


# ---------------------------------------------------------------------------
# Memory command group
# ---------------------------------------------------------------------------

@main.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
)
def memory() -> None:
    """Inspect and maintain memory stores."""
    pass


@memory.command("prune")
@click.option("--keep-days", default=30, type=int, show_default=True, help="Retain this many days of episodic memory.")
def memory_prune(keep_days: int) -> None:
    """Prune old episodic memory entries."""
    asyncio.run(_memory_prune(keep_days))


async def _memory_prune(keep_days: int) -> None:
    from neuralclaw.cortex.memory.episodic import EpisodicMemory

    config = load_config()
    memory = EpisodicMemory(config.memory.db_path)
    await memory.initialize()
    deleted = await memory.prune(keep_days=keep_days)
    await memory.close()
    console.print(f"[green]Pruned[/green] {deleted} episodic memories older than {keep_days} days.")


# ---------------------------------------------------------------------------
# Traces command group
# ---------------------------------------------------------------------------

@main.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
)
def traces() -> None:
    """Inspect and maintain reasoning traces."""
    pass


@traces.command("list")
@click.option("--since", default=None, help="Only include traces newer than e.g. 7d, 12h, 30m.")
@click.option("--limit", default=20, type=int, show_default=True, help="Maximum traces to show.")
def traces_list(since: str | None, limit: int) -> None:
    """List recent traces."""
    asyncio.run(_traces_list(since=since, limit=limit))


async def _traces_list(since: str | None, limit: int) -> None:
    from neuralclaw.bus.neural_bus import NeuralBus
    from neuralclaw.cortex.observability.traceline import Traceline

    config = load_config()
    traceline = Traceline(config.traceline.db_path, NeuralBus(), config=config.traceline)
    await traceline.initialize()
    try:
        results = await traceline.query_traces(since=_parse_since_value(since), limit=limit)
    finally:
        await traceline.close()

    table = Table(title="Recent Traces", style="cyan")
    table.add_column("Time", style="bold")
    table.add_column("Trace")
    table.add_column("User")
    table.add_column("Path")
    table.add_column("Threat")
    table.add_column("Preview")
    for trace in results:
        table.add_row(
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(trace.timestamp)),
            trace.trace_id,
            trace.user_id or "—",
            trace.reasoning_path or "—",
            f"{trace.threat_score:.2f}",
            (trace.output_preview or trace.input_preview or "—")[:80],
        )
    console.print(table if results else "[dim]No traces matched the filters.[/dim]")


@traces.command("prune")
@click.option("--keep-days", default=14, type=int, show_default=True, help="Retain this many days of traces.")
def traces_prune(keep_days: int) -> None:
    """Prune old reasoning traces."""
    asyncio.run(_traces_prune(keep_days))


async def _traces_prune(keep_days: int) -> None:
    from neuralclaw.bus.neural_bus import NeuralBus
    from neuralclaw.cortex.observability.traceline import Traceline

    config = load_config()
    traceline = Traceline(config.traceline.db_path, NeuralBus(), config=config.traceline)
    await traceline.initialize()
    try:
        deleted = await traceline.prune(keep_days=keep_days)
    finally:
        await traceline.close()
    console.print(f"[green]Pruned[/green] {deleted} traces older than {keep_days} days.")


# ---------------------------------------------------------------------------
# Provider command group
# ---------------------------------------------------------------------------

@main.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
)
def provider() -> None:
    """Inspect and control provider runtime state."""
    pass


@provider.command("reset-circuit")
@click.option("--name", required=True, help="Provider name to reset.")
@click.option("--port", default=8080, type=int, show_default=True, help="Gateway dashboard port.")
def provider_reset_circuit(name: str, port: int) -> None:
    """Reset a live provider circuit breaker via the local dashboard API."""
    url = f"http://127.0.0.1:{port}/api/provider/reset-circuit"
    body = json.dumps({"name": name}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        console.print(f"[red]Failed to reach the running gateway:[/red] {exc}")
        return

    if payload.get("ok"):
        console.print(f"[green]Reset circuit[/green] for provider [cyan]{name}[/cyan].")
    else:
        console.print(f"[red]Circuit reset failed:[/red] {payload.get('error', 'unknown error')}")


# ---------------------------------------------------------------------------
# Dashboard command
# ---------------------------------------------------------------------------

@main.command()
@click.option("--port", default=8080, help="Dashboard port")
def dashboard(port: int) -> None:
    """Launch the NeuralClaw web dashboard."""
    console.print(BANNER)
    console.print("[bold green]Starting NeuralClaw Dashboard...[/bold green]\n")
    asyncio.run(_run_dashboard(port))


async def _run_dashboard(port: int) -> None:
    from neuralclaw.dashboard import Dashboard
    dash = Dashboard(port=port)
    await dash.start()
    console.print(f"[bold]Dashboard running at[/bold] [cyan]http://localhost:{port}[/cyan]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        await dash.stop()


# ---------------------------------------------------------------------------
# Swarm command group
# ---------------------------------------------------------------------------

@main.group()
def swarm() -> None:
    """Manage swarm agents and delegations."""
    pass


@swarm.command("status")
def swarm_status() -> None:
    """Show active swarm agents and mesh status."""
    console.print(BANNER)

    from neuralclaw.swarm.mesh import AgentMesh
    mesh = AgentMesh()
    status_info = mesh.get_mesh_status()

    table = Table(title="Swarm Mesh Status", style="cyan")
    table.add_column("Property", style="bold")
    table.add_column("Value")

    table.add_row("Total Agents", str(status_info["total_agents"]))
    table.add_row("Online Agents", str(status_info["online_agents"]))
    table.add_row("Total Messages", str(status_info["total_messages"]))

    console.print(table)

    if status_info["agents"]:
        agent_table = Table(title="Registered Agents", style="green")
        agent_table.add_column("Name", style="bold")
        agent_table.add_column("Status")
        agent_table.add_column("Capabilities")
        agent_table.add_column("Active Tasks")
        agent_table.add_column("Endpoint")

        for a in status_info["agents"]:
            agent_table.add_row(
                a["name"],
                a["status"],
                ", ".join(a["capabilities"]),
                str(a["active_tasks"]),
                a["endpoint"],
            )
        console.print(agent_table)
    else:
        console.print("\n[dim]No agents registered on the mesh.[/dim]")
        console.print("[dim]Agents are registered when the gateway runs.[/dim]")
    console.print()


@swarm.command("spawn")
@click.argument("name")
@click.option("--capabilities", "-c", default="general", help="Comma-separated capabilities.")
@click.option("--description", "-d", default="", help="Agent description.")
@click.option("--endpoint", "-e", default=None, help="Remote agent endpoint URL.")
def swarm_spawn(name: str, capabilities: str, description: str, endpoint: str | None) -> None:
    """Spawn a new agent on the swarm mesh.

    For remote agents, provide --endpoint to register a proxy.

    \b
    Examples:
        neuralclaw swarm spawn researcher -c "search,analysis"
        neuralclaw swarm spawn remote-agent -e http://peer:8100
    """
    caps = [c.strip() for c in capabilities.split(",") if c.strip()]
    desc = description or f"Agent '{name}' with capabilities: {', '.join(caps)}"

    console.print(Panel(f"[bold]Spawn Agent: {name}[/bold]", border_style="green"))
    console.print(f"  Name: [bold]{name}[/bold]")
    console.print(f"  Description: {desc}")
    console.print(f"  Capabilities: {caps}")

    if endpoint:
        console.print(f"  Endpoint: [cyan]{endpoint}[/cyan]")
        console.print(f"  Type: [cyan]remote[/cyan]")
    else:
        console.print(f"  Type: [cyan]local[/cyan]")

    console.print("\n[dim]Agents are spawned at runtime via the gateway.[/dim]")
    console.print("[dim]Use the Python API: gateway.spawner.spawn_local(...)[/dim]")
    console.print()


# ---------------------------------------------------------------------------
# Migrate from OpenClaw
# ---------------------------------------------------------------------------


@main.command()
@click.option("--source", default=None, help="Path to OpenClaw directory (auto-detected if omitted)")
@click.option("--dry-run", is_flag=True, help="Scan only — don't migrate anything")
def migrate(source: str | None, dry_run: bool) -> None:
    """Migrate from OpenClaw / Clawdbot / Moltbot to NeuralClaw."""
    from neuralclaw.migrate import OpenClawMigrator

    console.print(Panel(
        "[bold]OpenClaw → NeuralClaw Migration Tool[/bold]\n"
        "[dim]Imports your config, channel tokens, and memories[/dim]",
        border_style="blue",
    ))

    migrator = OpenClawMigrator(source)

    if not migrator.found:
        console.print("\n[yellow]No OpenClaw installation found.[/yellow]")
        console.print("[dim]Searched: ~/.openclaw, ~/clawd, ~/.clawdbot, ~/.moltbot[/dim]")
        if not source:
            console.print("\n[dim]Tip: Use --source /path/to/openclaw to specify manually[/dim]")
        return

    console.print(f"\n[green]✓[/green] Found OpenClaw at: [bold]{migrator.source_path}[/bold]\n")

    # Scan
    scan = migrator.scan()
    scan_table = Table(show_header=False, box=None, padding=(0, 2))
    scan_table.add_row("Config:", "[green]found[/green]" if scan["config_exists"] else "[red]not found[/red]")
    scan_table.add_row("Memory files:", str(scan["memory_files"]))
    scan_table.add_row("Channels:", ", ".join(scan.get("channels", [])) or "none")
    scan_table.add_row("Providers:", ", ".join(scan.get("providers", [])) or "none")
    console.print(scan_table)

    if dry_run:
        console.print("\n[dim]Dry run complete — no changes made.[/dim]")
        return

    console.print("\n[bold]Migrating...[/bold]\n")
    report = migrator.run_full_migration()

    # Report
    result_table = Table(show_header=False, box=None, padding=(0, 2))
    result_table.add_row("Config migrated:", "[green]✓[/green]" if report.config_migrated else "[red]✗[/red]")
    result_table.add_row("Memories imported:", str(report.memories_imported))
    result_table.add_row("Channels:", ", ".join(report.channels_migrated) or "none")
    result_table.add_row("API keys detected:", ", ".join(report.api_keys_migrated) or "none")
    console.print(result_table)

    if report.warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        for w in report.warnings:
            console.print(f"  [yellow]⚠[/yellow] {w}")

    if report.errors:
        console.print("\n[red]Errors:[/red]")
        for e in report.errors:
            console.print(f"  [red]✗[/red] {e}")

    if report.api_keys_migrated:
        console.print("\n[dim]Note: API keys were detected but not copied (security).")
        console.print("Run `neuralclaw init` to securely store them in your keychain.[/dim]")

    console.print("\n[green]Migration complete![/green]\n")


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------


@main.command()
@click.option("--category", default=None, help="Run a specific category (perception, memory, security, reasoning, latency)")
@click.option("--export", is_flag=True, help="Export results to JSON")
def benchmark(category: str | None, export: bool) -> None:
    """Run the NeuralClaw benchmark suite."""
    import asyncio
    from neuralclaw.benchmark import BenchmarkSuite

    console.print(Panel(
        "[bold]NeuralClaw Benchmark Suite[/bold]\n"
        "[dim]Measuring perception, memory, security, reasoning, and latency[/dim]",
        border_style="cyan",
    ))

    suite = BenchmarkSuite()

    with console.status("[bold cyan]Running benchmarks...[/bold cyan]"):
        if category:
            result = asyncio.run(suite.run_category(category))
            report = suite._report
            report.results = [result]
        else:
            report = asyncio.run(suite.run_all())

    # Display results
    results_table = Table(title="Benchmark Results", show_lines=True)
    results_table.add_column("Benchmark", style="bold")
    results_table.add_column("Score", justify="center")
    results_table.add_column("Pass/Total", justify="center")
    results_table.add_column("Avg Latency", justify="right")
    results_table.add_column("Time", justify="right")

    for r in report.results:
        score_color = "green" if r.score >= 0.8 else "yellow" if r.score >= 0.5 else "red"
        results_table.add_row(
            r.name,
            f"[{score_color}]{r.score:.0%}[/{score_color}]",
            f"{r.passed}/{r.total}",
            f"{r.latency_ms:.1f}ms",
            f"{r.elapsed_seconds:.1f}s",
        )

    console.print(results_table)

    overall_color = "green" if report.overall_score >= 0.8 else "yellow" if report.overall_score >= 0.5 else "red"
    console.print(f"\n[bold]Overall Score:[/bold] [{overall_color}]{report.overall_score:.0%}[/{overall_color}]")
    console.print(f"[dim]Total time: {report.total_elapsed_seconds:.1f}s[/dim]\n")

    if export:
        path = suite.export_json()
        console.print(f"[green]✓[/green] Results exported to: [bold]{path}[/bold]\n")


# ---------------------------------------------------------------------------
# Federation
# ---------------------------------------------------------------------------


@main.command()
@click.option("--port", default=8100, help="Federation port to query.")
def federation(port: int) -> None:
    """Show federation status and connected nodes."""
    console.print(Panel(
        "[bold]NeuralClaw Federation[/bold]\n"
        "[dim]Cross-network agent discovery and communication[/dim]",
        border_style="blue",
    ))

    # Try to query a running federation server
    import json
    import urllib.request
    try:
        url = f"http://127.0.0.1:{port}/federation/status"
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read())

        status_table = Table(title="Federation Status", style="cyan")
        status_table.add_column("Property", style="bold")
        status_table.add_column("Value")
        status_table.add_row("Total Nodes", str(data.get("total_nodes", 0)))
        status_table.add_row("Online Nodes", str(data.get("online_nodes", 0)))
        status_table.add_row("Blacklisted", str(data.get("blacklisted", 0)))
        console.print(status_table)

        nodes = data.get("nodes", [])
        if nodes:
            node_table = Table(title="Connected Nodes", style="green")
            node_table.add_column("Name", style="bold")
            node_table.add_column("Status")
            node_table.add_column("Trust")
            node_table.add_column("Capabilities")
            node_table.add_column("Endpoint")

            for n in nodes:
                trust = n.get("trust", 0.0)
                trust_color = "green" if trust >= 0.7 else "yellow" if trust >= 0.4 else "red"
                node_table.add_row(
                    n.get("name", "?"),
                    n.get("status", "?"),
                    f"[{trust_color}]{trust:.2f}[/{trust_color}]",
                    ", ".join(n.get("capabilities", [])) or "none",
                    n.get("endpoint", "?"),
                )
            console.print(node_table)
        else:
            console.print("\n[dim]No nodes connected.[/dim]")

    except Exception:
        console.print(f"\n[dim]Federation server not running on port {port}.[/dim]")
        console.print("[dim]Start the gateway first: neuralclaw gateway[/dim]")
        # Fall back to protocol info
        info_table = Table(show_header=False, box=None, padding=(0, 2))
        info_table.add_row("Protocol:", "HTTP/JSON")
        info_table.add_row("Discovery:", "/federation/discover")
        info_table.add_row("Messaging:", "/federation/message")
        info_table.add_row("Heartbeat:", "/federation/heartbeat")
        info_table.add_row("Status:", "/federation/status")
        console.print(info_table)
    console.print()


# ---------------------------------------------------------------------------
# Test command
# ---------------------------------------------------------------------------

@main.command(name="test")
@click.argument("feature", required=False, default=None)
@click.option("--verbose", "-v", is_flag=True, default=False, help="Verbose output.")
@click.option("--coverage", is_flag=True, default=False, help="Run with coverage report.")
def run_tests(feature: str | None, verbose: bool, coverage: bool) -> None:
    """Run tests — all or by feature name.

    \b
    Examples:
        neuralclaw test                  Run all tests
        neuralclaw test vector           Run vector memory tests
        neuralclaw test browser          Run browser cortex tests
        neuralclaw test identity         Run identity store tests
        neuralclaw test --coverage       Run all with coverage

    \b
    Available features:
        vector, identity, browser, vision, tts, google, microsoft,
        parallel, streaming, structured, a2a, traceline, output_filter,
        audit, desktop, perception, memory, config, sandbox, ssrf,
        auth, health, federation, gateway, proxy, token
    """
    import subprocess

    console.print(BANNER)

    # Resolve project root (where tests/ lives)
    project_root = Path(__file__).resolve().parent.parent
    tests_dir = project_root / "tests"

    if not tests_dir.exists():
        console.print("[red]Tests directory not found.[/red]")
        console.print(f"[dim]Expected at: {tests_dir}[/dim]")
        return

    # Map friendly names to test files
    FEATURE_MAP = {
        "vector": "test_vector_memory.py",
        "identity": "test_identity.py",
        "browser": "test_browser.py",
        "vision": "test_vision.py",
        "tts": "test_tts.py",
        "google": "test_google_workspace.py",
        "microsoft": "test_microsoft365.py",
        "parallel": "test_parallel_tools.py",
        "streaming": "test_streaming.py",
        "structured": "test_structured.py",
        "a2a": "test_a2a.py",
        "traceline": "test_traceline.py",
        "output_filter": "test_output_filter.py",
        "audit": "test_audit_replay.py",
        "desktop": "test_desktop.py",
        "perception": "test_perception.py",
        "memory": "test_memory.py",
        "config": "test_config_validation.py",
        "sandbox": "test_sandbox_policy.py",
        "ssrf": "test_ssrf.py",
        "auth": "test_auth.py",
        "health": "test_health.py",
        "federation": "test_federation_spawn.py",
        "gateway": "test_session_and_gateway.py",
        "proxy": "test_proxy_provider.py",
        "token": "test_token_providers.py",
    }

    cmd = [sys.executable, "-m", "pytest"]

    if feature:
        # Fuzzy match
        feature_lower = feature.lower().strip()
        if feature_lower in FEATURE_MAP:
            test_file = tests_dir / FEATURE_MAP[feature_lower]
            cmd.append(str(test_file))
            console.print(f"Running: [cyan]{FEATURE_MAP[feature_lower]}[/cyan]\n")
        else:
            # Try direct file match
            direct = tests_dir / f"test_{feature_lower}.py"
            if direct.exists():
                cmd.append(str(direct))
                console.print(f"Running: [cyan]test_{feature_lower}.py[/cyan]\n")
            else:
                console.print(f"[red]Unknown feature '{feature}'[/red]")
                console.print(f"[dim]Available: {', '.join(sorted(FEATURE_MAP.keys()))}[/dim]")
                return
    else:
        cmd.append(str(tests_dir))
        console.print("Running: [cyan]all tests[/cyan]\n")

    if verbose:
        cmd.append("-v")
    else:
        cmd.append("-v")  # always verbose for nice output

    if coverage:
        cmd.extend(["--cov=neuralclaw", "--cov-report=term-missing"])

    try:
        result = subprocess.run(cmd, cwd=str(project_root))
        sys.exit(result.returncode)
    except FileNotFoundError:
        console.print("[red]pytest not found. Install dev dependencies:[/red]")
        console.print("[cyan]  pip install -e '.[dev]'[/cyan]")


# ---------------------------------------------------------------------------
# Service management
# ---------------------------------------------------------------------------

@main.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
)
def service() -> None:
    """Manage NeuralClaw Windows service (requires admin)."""
    pass


@service.command(name="install")
def service_install() -> None:
    """Install the managed NeuralClaw service."""
    console.print(BANNER)
    from neuralclaw.service import install_service

    ok, message = install_service()
    console.print(f"\n[{'green' if ok else 'red'}]{message}[/{'green' if ok else 'red'}]")


@service.command(name="uninstall")
def service_uninstall() -> None:
    """Remove the managed NeuralClaw service."""
    from neuralclaw.service import uninstall_service

    ok, message = uninstall_service()
    console.print(f"[{'green' if ok else 'red'}]{message}[/{'green' if ok else 'red'}]")


@service.command(name="start")
def service_start() -> None:
    """Start the managed service."""
    from neuralclaw.service import start_service

    ok, message = start_service()
    console.print(f"[{'green' if ok else 'red'}]{message}[/{'green' if ok else 'red'}]")


@service.command(name="stop")
def service_stop() -> None:
    """Stop the managed service."""
    from neuralclaw.service import stop_service

    ok, message = stop_service()
    console.print(f"[{'green' if ok else 'red'}]{message}[/{'green' if ok else 'red'}]")


@service.command(name="restart")
def service_restart() -> None:
    """Restart the managed service."""
    from neuralclaw.service import restart_service

    ok, message = restart_service()
    console.print(f"[{'green' if ok else 'red'}]{message}[/{'green' if ok else 'red'}]")


@service.command(name="status")
def service_status_cmd() -> None:
    """Check the service status."""
    from neuralclaw.service import service_status
    s = service_status()
    style = {"running": "green", "installed": "cyan", "stopped": "red", "not_installed": "yellow"}.get(s, "dim")
    console.print(f"Service: [{style}]{s}[/{style}]")


@service.command(name="logs")
@click.option("--lines", "-n", default=100, help="Number of lines to show.")
@click.option("--follow", "-f", is_flag=True, help="Follow the service logs.")
def service_logs_cmd(lines: int, follow: bool) -> None:
    """View service logs."""
    from neuralclaw.service import service_logs

    result = service_logs(lines=lines, follow=follow)
    if result is None:
        logs.callback(lines=lines, follow=follow)


@service.command(name="pm2")
def service_pm2_cmd() -> None:
    """Write a PM2 ecosystem file for non-systemd environments."""
    from neuralclaw.service import write_pm2_config

    path = write_pm2_config()
    console.print(f"[green]Wrote PM2 config to[/green] [cyan]{path}[/cyan]")


# ---------------------------------------------------------------------------
# Startup (Task Scheduler — no admin needed)
# ---------------------------------------------------------------------------

@main.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
)
def startup() -> None:
    """Auto-start NeuralClaw on login (no admin needed)."""
    pass


@startup.command(name="install")
def startup_install() -> None:
    """Add NeuralClaw to Windows startup (runs on every login)."""
    console.print(BANNER)
    from neuralclaw.service import install_startup
    install_startup()


@startup.command(name="uninstall")
def startup_uninstall() -> None:
    """Remove NeuralClaw from startup."""
    from neuralclaw.service import uninstall_startup
    uninstall_startup()


# ---------------------------------------------------------------------------
# Daemon (background process — cross-platform)
# ---------------------------------------------------------------------------

@main.command()
def daemon() -> None:
    """Run gateway as a background process (cross-platform).

    \b
    Starts the gateway detached from the terminal.
    It keeps running after you close the terminal.
    Use 'neuralclaw stop' to stop it.
    """
    console.print(BANNER)
    from neuralclaw.service import start_daemon, _is_running, _read_pid

    existing = _read_pid()
    if existing and _is_running(existing):
        console.print(f"[yellow]Gateway already running (PID {existing})[/yellow]")
        console.print("[dim]Use 'neuralclaw stop' to stop, or 'neuralclaw restart' to restart.[/dim]")
        return

    console.print("[dim]Starting gateway in background...[/dim]")
    pid = start_daemon()
    time.sleep(2)

    if _is_running(pid):
        console.print(f"\n[bold green]Gateway running in background (PID {pid})[/bold green]")
        console.print("[dim]It will keep running after you close this terminal.[/dim]")
        console.print()
        console.print("  [cyan]neuralclaw stop[/cyan]      Stop the gateway")
        console.print("  [cyan]neuralclaw restart[/cyan]   Restart the gateway")
        console.print("  [cyan]neuralclaw logs[/cyan]      View gateway logs")
        console.print("  [cyan]neuralclaw alive[/cyan]     Check if running")
    else:
        console.print("[red]Gateway failed to start. Check logs:[/red]")
        console.print(f"[dim]  {Path.home() / '.neuralclaw' / 'gateway.log'}[/dim]")


@main.command(name="stop")
def stop_cmd() -> None:
    """Stop the background gateway."""
    from neuralclaw.service import stop_daemon, _is_running, _read_pid

    pid = _read_pid()
    if not pid or not _is_running(pid):
        console.print("[dim]Gateway is not running.[/dim]")
        return

    console.print(f"[dim]Stopping gateway (PID {pid})...[/dim]")
    stop_daemon()
    console.print("[green]Gateway stopped.[/green]")


@main.command()
def restart() -> None:
    """Restart the background gateway."""
    from neuralclaw.service import stop_daemon, start_daemon, _is_running

    console.print("[dim]Restarting gateway...[/dim]")
    stop_daemon()
    time.sleep(2)
    pid = start_daemon()
    time.sleep(2)

    if _is_running(pid):
        console.print(f"[bold green]Gateway restarted (PID {pid})[/bold green]")
    else:
        console.print("[red]Gateway failed to restart. Check logs.[/red]")


@main.command()
def alive() -> None:
    """Check if the gateway is running."""
    from neuralclaw.service import _read_pid, _is_running, _read_status

    pid = _read_pid()
    status = _read_status()
    running = pid and _is_running(pid)

    if running:
        console.print(f"[bold green]Gateway is running[/bold green] (PID {pid})")
        restarts = status.get("restarts", "0")
        if restarts != "0":
            console.print(f"[dim]Restarts: {restarts}[/dim]")
    else:
        console.print("[red]Gateway is not running.[/red]")
        if status.get("status") == "crashed":
            console.print(f"[dim]Last error: {status.get('error', 'unknown')}[/dim]")
        console.print("[dim]Start with: neuralclaw daemon[/dim]")


@main.command()
@click.option("--lines", "-n", default=50, help="Number of lines to show.")
@click.option("--follow", "-f", is_flag=True, help="Follow log output (like tail -f).")
def logs(lines: int, follow: bool) -> None:
    """View gateway logs."""
    log_file = Path.home() / ".neuralclaw" / "gateway.log"

    if not log_file.exists():
        console.print("[dim]No logs yet. Start the gateway first.[/dim]")
        return

    if follow and sys.platform != "win32":
        os.execvp("tail", ["tail", "-f", "-n", str(lines), str(log_file)])
    else:
        # Read last N lines
        all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in all_lines[-lines:]:
            # Colorize log levels
            if "[ERROR]" in line:
                console.print(f"[red]{line}[/red]")
            elif "[WARNING]" in line:
                console.print(f"[yellow]{line}[/yellow]")
            elif "[INFO]" in line:
                console.print(line)
            else:
                console.print(f"[dim]{line}[/dim]")

        if follow:
            console.print(f"\n[dim]--follow not supported on Windows. Showing last {lines} lines.[/dim]")


@main.command()
def tray() -> None:
    """Launch system tray icon (starts gateway automatically).

    \b
    Right-click the tray icon to:
      - Start / Stop / Restart the gateway
      - View status and logs
      - Quit
    """
    console.print(BANNER)
    console.print("[dim]Launching system tray...[/dim]")
    from neuralclaw.service import run_tray
    run_tray()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
