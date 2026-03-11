"""
Discord Channel Adapter — Discord bot integration using discord.py.
"""

from __future__ import annotations

import asyncio
from typing import Any

from neuralclaw.channels.protocol import ChannelAdapter, ChannelMessage


class DiscordAdapter(ChannelAdapter):
    """
    Discord bot adapter using discord.py.

    Requires a bot token from the Discord Developer Portal.
    Responds to mentions and DMs.
    """

    name = "discord"

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token
        self._client: Any = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the Discord bot."""
        try:
            import discord
        except ImportError:
            raise RuntimeError("discord.py not installed. Run: pip install discord.py")

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)

        adapter = self  # Capture for closure

        @self._client.event
        async def on_ready() -> None:
            print(f"[Discord] Logged in as {self._client.user}")

        @self._client.event
        async def on_message(message: discord.Message) -> None:
            # Ignore own messages
            if message.author == self._client.user:
                return

            # Respond to DMs or mentions
            is_dm = isinstance(message.channel, discord.DMChannel)
            is_mentioned = self._client.user in message.mentions if self._client.user else False

            if not is_dm and not is_mentioned:
                return

            content = message.content
            # Strip the mention from content
            if is_mentioned and self._client.user:
                content = content.replace(f"<@{self._client.user.id}>", "").strip()

            msg = ChannelMessage(
                content=content,
                author_id=str(message.author.id),
                author_name=message.author.display_name,
                channel_id=str(message.channel.id),
                raw=message,
                metadata={
                    "platform": "discord",
                    "source": "discord",
                    "is_dm": is_dm,
                    "is_private": is_dm,
                    "is_shared": not is_dm,
                    "guild_id": str(message.guild.id) if message.guild else "",
                    "guild": message.guild.name if message.guild else None,
                },
            )
            await adapter._dispatch(msg)

        # Run the client in a background task
        self._task = asyncio.create_task(self._client.start(self._token))

    async def stop(self) -> None:
        """Stop the Discord bot."""
        if self._client:
            await self._client.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def test_connection(self) -> tuple[bool, str]:
        """Verify the bot token by calling /users/@me."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://discord.com/api/v10/users/@me",
                    headers={"Authorization": f"Bot {self._token}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return True, f"Connected as {data.get('username', 'unknown')}"
                    return False, f"Discord API returned {resp.status}"
        except Exception as e:
            return False, f"Connection failed: {e}"

    async def send(self, channel_id: str, content: str, **kwargs: Any) -> None:
        """Send a message to a Discord channel."""
        if self._client:
            channel = self._client.get_channel(int(channel_id))
            if channel is None:
                channel = await self._client.fetch_channel(int(channel_id))
            if channel:
                await channel.send(content)
