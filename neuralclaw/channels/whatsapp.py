"""
WhatsApp Channel Adapter — WhatsApp via whatsapp-web.js bridge.

Uses a Node.js subprocess running whatsapp-web.js to bridge
WhatsApp messages to NeuralClaw.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from neuralclaw.channels.protocol import ChannelAdapter, ChannelMessage


class WhatsAppAdapter(ChannelAdapter):
    """
    WhatsApp adapter using whatsapp-web.js bridge.

    Requires Node.js and whatsapp-web.js to be installed.
    Communicates via stdin/stdout JSON messages.

    Setup:
        npm install whatsapp-web.js qrcode-terminal

    The bridge script handles QR code pairing and message routing.
    """

    name = "whatsapp"

    def __init__(self, session_path: str = ".wwebjs_auth") -> None:
        super().__init__()
        self._session_path = session_path
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the WhatsApp bridge subprocess."""
        bridge_script = self._get_bridge_script()

        self._process = await asyncio.create_subprocess_exec(
            "node", "-e", bridge_script,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._reader_task = asyncio.create_task(self._read_messages())
        print("[WhatsApp] Bridge started. Scan QR code if prompted.")

    async def stop(self) -> None:
        """Stop the WhatsApp bridge."""
        if self._process:
            self._process.terminate()
            await self._process.wait()
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

    async def send(self, channel_id: str, content: str, **kwargs: Any) -> None:
        """Send a message to a WhatsApp chat."""
        if self._process and self._process.stdin:
            msg = json.dumps({"type": "send", "to": channel_id, "content": content})
            self._process.stdin.write(f"{msg}\n".encode())
            await self._process.stdin.drain()

    async def _read_messages(self) -> None:
        """Read messages from the bridge subprocess."""
        if not self._process or not self._process.stdout:
            return

        while True:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    break

                data = json.loads(line.decode().strip())
                if data.get("type") == "message":
                    msg = ChannelMessage(
                        content=data.get("content", ""),
                        author_id=data.get("from", "unknown"),
                        author_name=data.get("name", "Unknown"),
                        channel_id=data.get("chat_id", ""),
                        metadata={"platform": "whatsapp"},
                    )
                    await self._dispatch(msg)

            except json.JSONDecodeError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[WhatsApp] Read error: {e}")
                await asyncio.sleep(1)

    def _get_bridge_script(self) -> str:
        """Generate the Node.js bridge script."""
        return """
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');

const client = new Client({
    authStrategy: new LocalAuth({ dataPath: '%s' }),
    puppeteer: { headless: true, args: ['--no-sandbox'] }
});

client.on('qr', qr => {
    qrcode.generate(qr, { small: true });
    console.error('Scan QR code above to connect WhatsApp');
});

client.on('ready', () => {
    console.error('WhatsApp client ready');
});

client.on('message', async msg => {
    const data = {
        type: 'message',
        content: msg.body,
        from: msg.from,
        name: (await msg.getContact()).pushname || 'Unknown',
        chat_id: msg.from,
        timestamp: msg.timestamp
    };
    console.log(JSON.stringify(data));
});

process.stdin.on('data', async data => {
    try {
        const cmd = JSON.parse(data.toString().trim());
        if (cmd.type === 'send') {
            await client.sendMessage(cmd.to, cmd.content);
        }
    } catch (e) {}
});

client.initialize();
""".replace("%s", self._session_path)
