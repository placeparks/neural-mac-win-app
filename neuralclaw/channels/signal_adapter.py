"""
Signal Channel Adapter — Signal messenger via signal-cli bridge.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from neuralclaw.channels.protocol import ChannelAdapter, ChannelMessage


class SignalAdapter(ChannelAdapter):
    """
    Signal messenger adapter via signal-cli.

    Uses signal-cli's JSON-RPC mode for message sending/receiving.
    Requires signal-cli to be installed and registered with a phone number.

    Setup:
        # Install signal-cli (Java required)
        # Register: signal-cli -u +1234567890 register
        # Verify:   signal-cli -u +1234567890 verify CODE
    """

    name = "signal"

    def __init__(self, phone_number: str) -> None:
        super().__init__()
        self._phone = phone_number
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start signal-cli in JSON-RPC mode."""
        self._process = await asyncio.create_subprocess_exec(
            "signal-cli", "-u", self._phone, "jsonRpc",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._reader_task = asyncio.create_task(self._read_messages())
        print(f"[Signal] Listening on {self._phone}")

    async def stop(self) -> None:
        """Stop the Signal adapter."""
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
        """Send a Signal message."""
        if self._process and self._process.stdin:
            rpc = json.dumps({
                "jsonrpc": "2.0",
                "method": "send",
                "params": {
                    "recipient": [channel_id],
                    "message": content,
                },
                "id": 1,
            })
            self._process.stdin.write(f"{rpc}\n".encode())
            await self._process.stdin.drain()

    async def _read_messages(self) -> None:
        """Read incoming messages from signal-cli."""
        if not self._process or not self._process.stdout:
            return

        while True:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    break

                data = json.loads(line.decode().strip())

                # Handle incoming message notifications
                if data.get("method") == "receive":
                    params = data.get("params", {})
                    envelope = params.get("envelope", {})
                    data_msg = envelope.get("dataMessage", {})

                    if data_msg.get("message"):
                        msg = ChannelMessage(
                            content=data_msg["message"],
                            author_id=envelope.get("source", "unknown"),
                            author_name=envelope.get("sourceName", "Unknown"),
                            channel_id=envelope.get("source", ""),
                            metadata={
                                "platform": "signal",
                                "source": "signal",
                                "is_private": True,
                                "is_shared": False,
                            },
                        )
                        await self._dispatch(msg)

            except json.JSONDecodeError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Signal] Read error: {e}")
                await asyncio.sleep(1)
