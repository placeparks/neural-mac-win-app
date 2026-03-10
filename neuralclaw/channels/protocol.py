"""
Channel Protocol — Universal channel adapter interface.

Every channel (Telegram, Discord, CLI, etc.) implements ChannelAdapter.
This ensures the cognitive pipeline is completely channel-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine


# ---------------------------------------------------------------------------
# Channel message wrapper
# ---------------------------------------------------------------------------

@dataclass
class ChannelMessage:
    """Raw channel-specific message wrapper."""
    content: str
    author_id: str
    author_name: str
    channel_id: str
    raw: Any = None  # Original platform-specific message object
    media: list[dict[str, Any]] = field(default_factory=list)
    reply_to: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Channel adapter ABC
# ---------------------------------------------------------------------------

MessageCallback = Callable[[ChannelMessage], Coroutine[Any, Any, None]]


class ChannelAdapter(ABC):
    """
    Abstract base class for channel adapters.

    Every messaging channel implements this interface:
    - start() / stop() lifecycle
    - send() to push messages to the channel
    - on_message() to register callbacks for incoming messages
    """

    name: str = "base"

    def __init__(self) -> None:
        self._callbacks: list[MessageCallback] = []

    def on_message(self, callback: MessageCallback) -> None:
        """Register a callback for incoming messages."""
        self._callbacks.append(callback)

    async def _dispatch(self, message: ChannelMessage) -> None:
        """Dispatch a received message to all callbacks."""
        for cb in self._callbacks:
            try:
                await cb(message)
            except Exception as e:
                print(f"[{self.name}] Callback error: {e}")

    @abstractmethod
    async def start(self) -> None:
        """Start the channel adapter (connect, begin polling, etc.)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the channel adapter."""
        ...

    @abstractmethod
    async def send(self, channel_id: str, content: str, **kwargs: Any) -> None:
        """Send a message to a specific channel."""
        ...

    async def test_connection(self) -> tuple[bool, str]:
        """Test if the channel credentials are valid and the service is reachable.

        Returns ``(success, message)``.  Subclasses should override to provide
        real connectivity checks.
        """
        return True, "no connectivity test available for this channel"
