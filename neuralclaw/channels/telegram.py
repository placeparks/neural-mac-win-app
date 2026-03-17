"""
Telegram Channel Adapter — Telegram bot integration using python-telegram-bot.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
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
        self._stop_event: asyncio.Event | None = None

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
                if not update.message:
                    return

                # Extract text: prefer .text, fall back to .caption for media messages
                text = update.message.text or update.message.caption or ""

                # Extract media (photos, image documents)
                media: list[dict[str, Any]] = []
                try:
                    if update.message.photo:
                        # photo is a list of PhotoSize, last is highest resolution
                        photo = update.message.photo[-1]
                        file = await photo.get_file()
                        photo_bytes = await file.download_as_bytearray()
                        media.append({
                            "type": "image",
                            "base64": base64.b64encode(bytes(photo_bytes)).decode("ascii"),
                            "mime_type": "image/jpeg",
                        })
                    elif update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith("image/"):
                        file = await update.message.document.get_file()
                        doc_bytes = await file.download_as_bytearray()
                        media.append({
                            "type": "image",
                            "base64": base64.b64encode(bytes(doc_bytes)).decode("ascii"),
                            "mime_type": update.message.document.mime_type,
                        })
                except Exception as e:
                    print(f"[Telegram] Media download error: {e}")

                # Skip messages with no text and no media
                if not text and not media:
                    return

                msg = ChannelMessage(
                    content=text,
                    author_id=str(update.message.from_user.id) if update.message.from_user else "unknown",
                    author_name=(
                        update.message.from_user.first_name
                        if update.message.from_user
                        else "Unknown"
                    ),
                    channel_id=str(update.message.chat_id),
                    raw=update,
                    media=media,
                    reply_to=(
                        str(update.message.reply_to_message.message_id)
                        if update.message.reply_to_message
                        else None
                    ),
                    metadata={
                        "platform": "telegram",
                        "source": "telegram",
                        "chat_type": update.message.chat.type,
                        "is_private": update.message.chat.type == "private",
                        "is_shared": update.message.chat.type != "private",
                    },
                )
                await self._dispatch(msg)

            # /start command
            async def handle_start(update: Update, context: Any) -> None:
                if update.message:
                    await update.message.reply_text(
                        "🧠 NeuralClaw is online. Send me a message to get started!"
                    )

            self._app.add_handler(CommandHandler("start", handle_start))
            self._app.add_handler(CommandHandler("pair", handle_message))
            self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
            self._app.add_handler(MessageHandler(filters.PHOTO, handle_message))
            self._app.add_handler(MessageHandler(filters.Document.IMAGE, handle_message))

            # Initialize + start + poll
            await self._app.initialize()
            await self._app.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "edited_message"],
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
        if self._stop_event is not None:
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

    async def send_photo(self, channel_id: str, photo_bytes: bytes, caption: str = "") -> None:
        """Send a photo (bytes) to a Telegram chat."""
        if not self._app or not self._app.bot:
            return
        import io
        buf = io.BytesIO(photo_bytes)
        buf.name = "screenshot.png"
        try:
            await self._app.bot.send_photo(
                chat_id=int(channel_id),
                photo=buf,
                caption=caption[:1024] if caption else None,
            )
        except Exception as e:
            print(f"[Telegram] Send photo error: {e}")

    async def send_stream(
        self,
        channel_id: str,
        token_iterator: AsyncIterator[str],
        **kwargs: Any,
    ) -> None:
        """Stream by editing a placeholder Telegram message."""
        if not self._app or not self._app.bot:
            await super().send_stream(channel_id, token_iterator, **kwargs)
            return

        edit_interval = max(1, int(kwargs.get("edit_interval", 20)))
        message = await self._app.bot.send_message(chat_id=int(channel_id), text="▌")
        buffer: list[str] = []

        async for token in token_iterator:
            buffer.append(token)
            current = "".join(buffer)
            if len(current) > 4000:
                await self.send(channel_id, current, **kwargs)
                return
            if len(buffer) % edit_interval == 0:
                try:
                    await self._app.bot.edit_message_text(
                        chat_id=int(channel_id),
                        message_id=message.message_id,
                        text=current + "▌",
                    )
                except Exception as e:
                    print(f"[Telegram] Stream edit error: {e}")

        final = "".join(buffer)
        if len(final) > 4000:
            await self.send(channel_id, final, **kwargs)
            return
        try:
            await self._app.bot.edit_message_text(
                chat_id=int(channel_id),
                message_id=message.message_id,
                text=final or " ",
            )
        except Exception as e:
            print(f"[Telegram] Stream final edit error: {e}")


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
