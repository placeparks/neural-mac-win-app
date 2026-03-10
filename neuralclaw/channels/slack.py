"""
Slack Channel Adapter — Slack bot via slack-bolt (async, Socket Mode).
"""

from __future__ import annotations

import asyncio
from typing import Any

from neuralclaw.channels.protocol import ChannelAdapter, ChannelMessage


class SlackAdapter(ChannelAdapter):
    """
    Slack bot adapter using slack-bolt async.

    Uses Socket Mode (no public URL required).
    Requires:
        pip install slack-bolt aiohttp

    Env vars needed:
        SLACK_BOT_TOKEN — Bot User OAuth Token (starts with xoxb-)
        SLACK_APP_TOKEN — App-Level Token (starts with xapp-)
    """

    name = "slack"

    def __init__(self, bot_token: str, app_token: str) -> None:
        super().__init__()
        self._bot_token = bot_token
        self._app_token = app_token
        self._app: Any = None
        self._handler: Any = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the Slack bot in Socket Mode."""
        try:
            from slack_bolt.async_app import AsyncApp
            from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
        except ImportError:
            raise RuntimeError(
                "slack-bolt not installed. Run: pip install slack-bolt"
            )

        self._app = AsyncApp(token=self._bot_token)
        adapter = self

        @self._app.event("message")
        async def handle_message(event: dict, say: Any) -> None:
            # Ignore bot messages
            if event.get("bot_id") or event.get("subtype"):
                return

            msg = ChannelMessage(
                content=event.get("text", ""),
                author_id=event.get("user", "unknown"),
                author_name=event.get("user", "Unknown"),
                channel_id=event.get("channel", ""),
                raw=event,
                metadata={
                    "platform": "slack",
                    "thread_ts": event.get("thread_ts"),
                },
            )
            await adapter._dispatch(msg)

        @self._app.event("app_mention")
        async def handle_mention(event: dict, say: Any) -> None:
            text = event.get("text", "")
            # Strip bot mention from text
            if "<@" in text:
                text = text.split(">", 1)[-1].strip()

            msg = ChannelMessage(
                content=text,
                author_id=event.get("user", "unknown"),
                author_name=event.get("user", "Unknown"),
                channel_id=event.get("channel", ""),
                raw=event,
                metadata={
                    "platform": "slack",
                    "is_mention": True,
                    "thread_ts": event.get("thread_ts", event.get("ts")),
                },
            )
            await adapter._dispatch(msg)

        self._handler = AsyncSocketModeHandler(self._app, self._app_token)
        self._task = asyncio.create_task(self._handler.start_async())
        print("[Slack] Bot started in Socket Mode")

    async def stop(self) -> None:
        """Stop the Slack bot."""
        if self._handler:
            await self._handler.close_async()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def send(self, channel_id: str, content: str, **kwargs: Any) -> None:
        """Send a message to a Slack channel."""
        if self._app:
            thread_ts = kwargs.get("thread_ts")
            await self._app.client.chat_postMessage(
                channel=channel_id,
                text=content,
                thread_ts=thread_ts,
            )
