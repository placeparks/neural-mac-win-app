"""
WhatsApp Channel Adapter — WhatsApp via Baileys (no Chromium).

Uses a Node.js subprocess running @whiskeysockets/baileys to bridge
WhatsApp messages to NeuralClaw.  Unlike the legacy whatsapp-web.js
adapter this does NOT require Puppeteer or Chromium, making it
suitable for lean Docker containers and CI environments.

Reference implementation: QRTrackingWhatsAppAdapter from neural-runtime-template.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Coroutine

from neuralclaw.channels.protocol import ChannelAdapter, ChannelMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Managed bridge directory — npm deps are auto-installed here
# ---------------------------------------------------------------------------

BRIDGE_DIR = Path.home() / ".neuralclaw" / "bridge"


def ensure_baileys_installed(*, quiet: bool = False) -> Path:
    """Ensure @whiskeysockets/baileys is installed in the managed bridge directory.

    Automatically runs ``npm install`` if the package is missing.
    Returns the bridge directory path.

    Raises ``RuntimeError`` if Node.js is not installed or npm install fails.
    """
    if not shutil.which("node"):
        raise RuntimeError(
            "Node.js not found. WhatsApp requires Node.js >= 18.\n"
            "Install from https://nodejs.org and try again."
        )

    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    baileys_marker = BRIDGE_DIR / "node_modules" / "@whiskeysockets" / "baileys"

    if baileys_marker.exists():
        return BRIDGE_DIR

    # Need to install — create a minimal package.json if missing
    pkg_json = BRIDGE_DIR / "package.json"
    if not pkg_json.exists():
        pkg_json.write_text(json.dumps({
            "name": "neuralclaw-whatsapp-bridge",
            "version": "1.0.0",
            "private": True,
            "dependencies": {
                "@whiskeysockets/baileys": "^6",
                "@hapi/boom": "^10",
            },
        }, indent=2), encoding="utf-8")

    # Run npm install
    npm_cmd = shutil.which("npm")
    if not npm_cmd:
        raise RuntimeError(
            "npm not found. Install Node.js (which includes npm) from https://nodejs.org"
        )

    if not quiet:
        logger.info("[WhatsApp] Installing bridge dependencies (one-time setup)...")

    result = subprocess.run(
        [npm_cmd, "install", "--production", "--no-audit", "--no-fund"],
        cwd=str(BRIDGE_DIR),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"npm install failed in {BRIDGE_DIR}:\n{result.stderr[:500]}"
        )

    if not quiet:
        logger.info("[WhatsApp] Bridge dependencies installed successfully.")

    return BRIDGE_DIR


def render_qr_terminal(data: str, console: Any) -> None:
    """Render a QR code as ASCII art inside a Rich panel.

    *data* is the raw QR payload string emitted by the Baileys bridge.
    *console* is a ``rich.console.Console`` instance.
    """
    try:
        import qrcode  # type: ignore[import-untyped]
    except ImportError:
        console.print(f"[yellow]qrcode package not installed — raw QR data:[/yellow]\n{data}")
        return

    qr = qrcode.QRCode(border=2)
    qr.add_data(data)
    qr.make(fit=True)

    # Render to string using print_ascii
    buf = io.StringIO()
    qr.print_ascii(out=buf, invert=True)
    ascii_art = buf.getvalue()

    from rich.panel import Panel
    console.print(Panel(
        ascii_art,
        title="Scan with WhatsApp",
        subtitle="WhatsApp → Linked Devices → Link a Device",
        style="bold green",
        expand=False,
    ))


class BaileysWhatsAppAdapter(ChannelAdapter):
    """
    WhatsApp adapter using @whiskeysockets/baileys.

    Requires Node.js (>=18) and the baileys npm package::

        npm install @whiskeysockets/baileys

    Communication happens over stdin/stdout JSON lines with the
    embedded bridge script.  QR codes are emitted as ``qr`` events
    so the runtime can forward them to a dashboard or log.
    """

    name = "whatsapp-baileys"

    def __init__(
        self,
        auth_dir: str = ".baileys_auth",
        *,
        on_qr: Callable[[str], Any] | None = None,
    ) -> None:
        super().__init__()
        self._auth_dir = auth_dir
        self._on_qr = on_qr
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._connected = asyncio.Event()
        self._fatal = False
        self._fatal_message = ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the Baileys bridge subprocess.

        Automatically installs npm dependencies on first run into
        ``~/.neuralclaw/bridge/`` — no manual ``npm install`` needed.
        """
        bridge_dir = ensure_baileys_installed()
        script = self._get_bridge_script()

        # Set NODE_PATH so the bridge script finds packages in the managed dir
        import os
        env = os.environ.copy()
        node_modules = str(bridge_dir / "node_modules")
        env["NODE_PATH"] = node_modules

        self._process = await asyncio.create_subprocess_exec(
            "node", "-e", script,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        self._reader_task = asyncio.create_task(self._read_loop())
        logger.info("[WhatsApp-Baileys] Bridge started — waiting for QR or auth")

    async def stop(self) -> None:
        """Gracefully stop the Baileys bridge."""
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        logger.info("[WhatsApp-Baileys] Bridge stopped")

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send(self, channel_id: str, content: str, **kwargs: Any) -> None:
        """Send a text message to a WhatsApp JID."""
        if not self._process or not self._process.stdin:
            raise RuntimeError("Baileys bridge is not running")

        payload = json.dumps({
            "type": "send",
            "to": channel_id,
            "content": content,
        })
        self._process.stdin.write(f"{payload}\n".encode())
        await self._process.stdin.drain()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    async def _read_loop(self) -> None:
        """Read JSON-line events from the bridge stdout."""
        assert self._process and self._process.stdout

        while True:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    break

                data = json.loads(line.decode().strip())
                event_type = data.get("type")

                if event_type == "message":
                    msg = ChannelMessage(
                        content=data.get("content", ""),
                        author_id=data.get("from", "unknown"),
                        author_name=data.get("name", "Unknown"),
                        channel_id=data.get("chat_id", ""),
                        metadata={"platform": "whatsapp"},
                    )
                    await self._dispatch(msg)

                elif event_type == "qr":
                    qr_data = data.get("data", "")
                    logger.info("[WhatsApp-Baileys] QR code received")
                    if self._on_qr:
                        result = self._on_qr(qr_data)
                        if asyncio.iscoroutine(result):
                            await result

                elif event_type == "connected":
                    self._connected.set()
                    logger.info("[WhatsApp-Baileys] Connected")

                elif event_type == "disconnected":
                    self._connected.clear()
                    logger.warning("[WhatsApp-Baileys] Disconnected: %s", data.get("reason"))

                elif event_type == "fatal":
                    self._connected.clear()
                    self._fatal_message = data.get("message", "Unknown fatal error")
                    logger.error("[WhatsApp-Baileys] Fatal: %s", self._fatal_message)
                    # Signal the _connected event so waiters stop blocking
                    self._fatal = True
                    self._connected.set()
                    break

            except json.JSONDecodeError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[WhatsApp-Baileys] Read error: %s", exc)
                await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # Connectivity check
    # ------------------------------------------------------------------

    async def test_connection(self) -> tuple[bool, str]:
        """Check if WhatsApp auth files exist from a previous pairing."""
        auth_path = Path(self._auth_dir)
        if not auth_path.exists():
            return False, "auth directory does not exist — run neuralclaw channels connect whatsapp"
        creds = auth_path / "creds.json"
        if creds.exists():
            return True, f"auth files found in {self._auth_dir}"
        return False, "not paired — run neuralclaw channels connect whatsapp"

    # ------------------------------------------------------------------
    # Bridge script
    # ------------------------------------------------------------------

    def _get_bridge_script(self) -> str:
        """Return the embedded Node.js Baileys bridge."""
        return """
const { default: makeWASocket, useMultiFileAuthState, DisconnectReason } = require('@whiskeysockets/baileys');
const { Boom } = require('@hapi/boom');
const fs = require('fs');

const AUTH_DIR = '__AUTH_DIR__';
const MAX_RETRIES = 5;
const RETRY_DELAY_MS = 3000;
let retryCount = 0;
let gotQR = false;

async function start() {
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);

    const sock = makeWASocket({
        auth: state,
        printQRInTerminal: false,
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;
        if (qr) {
            gotQR = true;
            retryCount = 0;
            console.log(JSON.stringify({ type: 'qr', data: qr }));
        }
        if (connection === 'open') {
            retryCount = 0;
            console.log(JSON.stringify({ type: 'connected' }));
        }
        if (connection === 'close') {
            const reason = new Boom(lastDisconnect?.error)?.output?.statusCode;
            console.log(JSON.stringify({ type: 'disconnected', reason: String(reason) }));

            if (reason === DisconnectReason.loggedOut) {
                console.log(JSON.stringify({ type: 'fatal', message: 'Logged out — delete auth folder and re-pair' }));
                process.exit(0);
            }

            retryCount++;
            if (retryCount > MAX_RETRIES && !gotQR) {
                console.log(JSON.stringify({
                    type: 'fatal',
                    message: 'Failed to connect after ' + MAX_RETRIES + ' attempts (reason: ' + reason + '). Check your network or Node.js version.',
                }));
                process.exit(1);
            }

            const delay = Math.min(RETRY_DELAY_MS * retryCount, 15000);
            setTimeout(() => start(), delay);
        }
    });

    sock.ev.on('messages.upsert', async ({ messages }) => {
        for (const msg of messages) {
            if (!msg.message || msg.key.fromMe) continue;
            const text = msg.message.conversation
                || msg.message.extendedTextMessage?.text
                || '';
            if (!text) continue;
            const jid = msg.key.remoteJid || '';
            let name = msg.pushName || 'Unknown';
            console.log(JSON.stringify({
                type: 'message',
                content: text,
                from: jid,
                name: name,
                chat_id: jid,
                timestamp: msg.messageTimestamp,
            }));
        }
    });

    process.stdin.on('data', async (data) => {
        try {
            const cmd = JSON.parse(data.toString().trim());
            if (cmd.type === 'send') {
                await sock.sendMessage(cmd.to, { text: cmd.content });
            }
        } catch (e) {
            console.error('stdin parse error:', e.message);
        }
    });
}

start().catch(err => {
    console.log(JSON.stringify({ type: 'fatal', message: String(err) }));
    process.exit(1);
});
""".replace("__AUTH_DIR__", self._auth_dir.replace("\\", "\\\\").replace("'", "\\'"))
