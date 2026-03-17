"""
Discord Channel Adapter — Discord bot integration using discord.py.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from neuralclaw.channels.protocol import ChannelAdapter, ChannelMessage


class DiscordAdapter(ChannelAdapter):
    """
    Discord bot adapter using discord.py.

    Requires a bot token from the Discord Developer Portal.
    Responds to mentions and DMs.
    """

    name = "discord"

    def __init__(self, token: str, auto_disconnect_empty_vc: bool = True) -> None:
        super().__init__()
        self._token = token
        self._client: Any = None
        self._task: asyncio.Task[None] | None = None
        self._voice_client: Any = None
        self._current_voice_channel: str | None = None
        self._auto_disconnect_empty_vc = auto_disconnect_empty_vc

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

        @self._client.event
        async def on_voice_state_update(member: Any, before: Any, after: Any) -> None:
            if not self._auto_disconnect_empty_vc or member != self._client.user or not self._voice_client:
                return
            channel = getattr(self._voice_client, "channel", None)
            if not channel:
                return
            if len([m for m in getattr(channel, "members", []) if not getattr(m, "bot", False)]) == 0:
                await adapter.leave_voice()

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

    async def send_stream(
        self,
        channel_id: str,
        token_iterator: AsyncIterator[str],
        **kwargs: Any,
    ) -> None:
        """Stream by editing a placeholder Discord message."""
        if not self._client:
            await super().send_stream(channel_id, token_iterator, **kwargs)
            return

        channel = self._client.get_channel(int(channel_id))
        if channel is None:
            channel = await self._client.fetch_channel(int(channel_id))
        if channel is None:
            await super().send_stream(channel_id, token_iterator, **kwargs)
            return

        message = await channel.send("▌")
        buffer: list[str] = []
        edit_interval = max(1, int(kwargs.get("edit_interval", 20)))

        async for token in token_iterator:
            buffer.append(token)
            if len(buffer) % edit_interval == 0:
                await message.edit(content=("".join(buffer) + "▌")[:2000])

        final = "".join(buffer) or " "
        await message.edit(content=final[:2000])

    async def join_voice(self, channel_id: str) -> bool:
        if not self._client:
            return False
        channel = self._client.get_channel(int(channel_id))
        if channel is None:
            channel = await self._client.fetch_channel(int(channel_id))
        if channel is None or not hasattr(channel, "connect"):
            return False
        if self._voice_client and getattr(self._voice_client, "is_connected", lambda: False)():
            if str(getattr(getattr(self._voice_client, "channel", None), "id", "")) == str(channel_id):
                self._current_voice_channel = channel_id
                return True
            await self.leave_voice()
        self._voice_client = await channel.connect()
        self._current_voice_channel = str(channel_id)
        return True

    async def leave_voice(self) -> None:
        if self._voice_client and hasattr(self._voice_client, "disconnect"):
            await self._voice_client.disconnect()
        self._voice_client = None
        self._current_voice_channel = None

    async def speak(self, audio_path: str, channel_id: str | None = None) -> None:
        if channel_id and (not self._voice_client or self._current_voice_channel != str(channel_id)):
            joined = await self.join_voice(channel_id)
            if not joined:
                raise RuntimeError(f"Could not join Discord voice channel {channel_id}")
        if not self._voice_client:
            raise RuntimeError("Discord voice client is not connected")
        try:
            import discord
        except ImportError as exc:
            raise RuntimeError("discord.py voice support is not installed") from exc
        source = discord.FFmpegPCMAudio(audio_path)
        self._voice_client.play(source)

    async def is_in_voice(self) -> bool:
        return bool(self._voice_client and getattr(self._voice_client, "is_connected", lambda: False)())

    @property
    def current_voice_channel(self) -> str | None:
        return self._current_voice_channel
