"""
Telegram Channel Adapter — Telegram bot integration using python-telegram-bot.
"""

from __future__ import annotations

import asyncio
from typing import Any

from neuralclaw.channels.protocol import ChannelAdapter, ChannelMessage


class TelegramAdapter(ChannelAdapter):
    """
    Telegram bot adapter using python-telegram-bot (async).

    Requires a bot token from @BotFather.
    """

    name = "telegram"

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token
        self._app: Any = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """
        Kick off Telegram bot in a background task.
        Returns immediately so the gateway startup never blocks.
        """
        self._task = asyncio.create_task(self._boot())

    async def _boot(self) -> None:
        """Full boot sequence running in the background."""
        try:
            from telegram import Update
            from telegram.ext import (
                Application,
                CommandHandler,
                MessageHandler,
                filters,
            )
        except ImportError:
            print("[Telegram] python-telegram-bot not installed. Run: pip install python-telegram-bot")
            return

        try:
            self._app = (
                Application.builder()
                .token(self._token)
                .connect_timeout(30)
                .read_timeout(30)
                .write_timeout(30)
                .build()
            )

            # Message handler — forward to gateway pipeline
            async def handle_message(update: Update, context: Any) -> None:
                if not update.message or not update.message.text:
                    return

                msg = ChannelMessage(
                    content=update.message.text,
                    author_id=str(update.message.from_user.id) if update.message.from_user else "unknown",
                    author_name=(
                        update.message.from_user.first_name
                        if update.message.from_user
                        else "Unknown"
                    ),
                    channel_id=str(update.message.chat_id),
                    raw=update,
                    reply_to=(
                        str(update.message.reply_to_message.message_id)
                        if update.message.reply_to_message
                        else None
                    ),
                    metadata={"chat_type": update.message.chat.type},
                )
                await self._dispatch(msg)

            # /start command
            async def handle_start(update: Update, context: Any) -> None:
                if update.message:
                    await update.message.reply_text(
                        "🧠 NeuralClaw is online. Send me a message to get started!"
                    )

            self._app.add_handler(CommandHandler("start", handle_start))
            self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

            # Initialize + start + poll
            await self._app.initialize()
            await self._app.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=["message"],
            )
            await self._app.start()
            print("[Telegram] ✓ Bot connected and polling")
            
            # Block until stopped
            self._stop_event = asyncio.Event()
            await self._stop_event.wait()
            
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[Telegram] Boot failed: {e}")

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        if hasattr(self, '_stop_event'):
            self._stop_event.set()
        
        if self._app:
            try:
                if self._app.updater and self._app.updater.running:
                    await self._app.updater.stop()
                if self._app.running:
                    await self._app.stop()
                await self._app.shutdown()
            except Exception:
                pass

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def test_connection(self) -> tuple[bool, str]:
        """Verify the bot token by calling getMe."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.telegram.org/bot{self._token}/getMe",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        bot_name = data.get("result", {}).get("username", "unknown")
                        return True, f"Connected as @{bot_name}"
                    return False, f"Telegram API returned {resp.status}"
        except Exception as e:
            return False, f"Connection failed: {e}"

    async def send(self, channel_id: str, content: str, **kwargs: Any) -> None:
        """Send a message to a Telegram chat."""
        if not self._app or not self._app.bot:
            return
        for chunk in _split_message(content, 4000):
            try:
                await self._app.bot.send_message(
                    chat_id=int(channel_id),
                    text=chunk,
                )
            except Exception as e:
                print(f"[Telegram] Send error: {e}")


def _split_message(text: str, max_length: int = 4000) -> list[str]:
    """Split a message into chunks that fit Telegram's 4096 char limit."""
    if len(text) <= max_length:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks
