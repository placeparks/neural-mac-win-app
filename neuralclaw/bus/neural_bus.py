"""
Neural Bus — Async inter-cortex event system.

The neural bus is the central nervous system of NeuralClaw. Every cortex
communicates through events published on the bus. This enables loose coupling,
full observability, and reasoning trace construction.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Coroutine


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

class EventType(Enum):
    """All event types that flow through the neural bus."""

    INFO = auto()

    # Perception cortex events
    SIGNAL_RECEIVED = auto()
    THREAT_SCREENED = auto()
    INTENT_CLASSIFIED = auto()
    CONTEXT_ENRICHED = auto()

    # Memory cortex events
    MEMORY_QUERY = auto()
    MEMORY_RETRIEVED = auto()
    MEMORY_STORED = auto()

    # Reasoning cortex events
    REASONING_STARTED = auto()
    REASONING_FAST_PATH = auto()
    REASONING_DELIBERATE = auto()
    REASONING_COMPLETE = auto()

    # Action cortex events
    ACTION_REQUESTED = auto()
    ACTION_EXECUTING = auto()
    ACTION_COMPLETE = auto()
    ACTION_DENIED = auto()

    # Memory lifecycle events (Phase 2)
    MEMORY_CONSOLIDATED = auto()
    MEMORY_DECAYED = auto()
    MEMORY_STRENGTHENED = auto()
    PROCEDURE_LEARNED = auto()

    # Reasoning events (Phase 2)
    REFLECTION_STARTED = auto()
    REFLECTION_COMPLETE = auto()

    # Evolution events (Phase 2)
    EVOLUTION_CALIBRATED = auto()
    SKILL_SYNTHESIZED = auto()
    EXPERIENCE_DISTILLED = auto()

    # RAG / Knowledge Base events
    RAG_INGESTED = auto()
    RAG_SEARCHED = auto()

    # Workflow engine events
    WORKFLOW_CREATED = auto()
    WORKFLOW_STARTED = auto()
    WORKFLOW_STEP_STARTED = auto()
    WORKFLOW_STEP_COMPLETED = auto()
    WORKFLOW_COMPLETED = auto()
    WORKFLOW_PAUSED = auto()

    # MCP server events
    MCP_CLIENT_CONNECTED = auto()
    MCP_TOOL_CALLED = auto()
    MCP_SERVER_STARTED = auto()
    MCP_SERVER_STOPPED = auto()

    # Gateway lifecycle events
    GATEWAY_STARTED = auto()
    GATEWAY_STOPPED = auto()
    CONFIG_RELOADED = auto()

    # Response events
    RESPONSE_READY = auto()
    RESPONSE_SENT = auto()

    # Health events
    HEALTH_CHECK_STARTED = auto()
    HEALTH_CHECK_COMPLETE = auto()
    HEALTH_REPAIR_STARTED = auto()
    HEALTH_REPAIR_COMPLETE = auto()

    # System events
    ERROR = auto()
    SHUTDOWN = auto()


# ---------------------------------------------------------------------------
# Event dataclass
# ---------------------------------------------------------------------------

@dataclass
class Event:
    """A single event on the neural bus."""

    type: EventType
    data: dict[str, Any]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    source: str = "system"
    correlation_id: str | None = None  # Links related events in a chain

    def child(self, event_type: EventType, data: dict[str, Any], source: str = "") -> Event:
        """Create a child event that inherits this event's correlation chain."""
        return Event(
            type=event_type,
            data=data,
            source=source or self.source,
            correlation_id=self.correlation_id or self.id,
        )


# ---------------------------------------------------------------------------
# Subscriber type
# ---------------------------------------------------------------------------

SyncHandler = Callable[[Event], None]
AsyncHandler = Callable[[Event], Coroutine[Any, Any, None]]
Handler = SyncHandler | AsyncHandler


# ---------------------------------------------------------------------------
# Neural Bus
# ---------------------------------------------------------------------------

class NeuralBus:
    """
    Async publish/subscribe event bus for inter-cortex communication.

    Usage:
        bus = NeuralBus()
        bus.subscribe(EventType.SIGNAL_RECEIVED, my_handler)
        await bus.start()
        await bus.publish(EventType.SIGNAL_RECEIVED, {"msg": "hello"})
        await bus.stop()
    """

    def __init__(self, max_queue_size: int = 1000) -> None:
        self._subscribers: dict[EventType, list[Handler]] = {}
        self._global_subscribers: list[Handler] = []
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=max_queue_size)
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._max_log_size = 2000
        self._event_log: deque[Event] = deque(maxlen=self._max_log_size)

    # -- Subscription -------------------------------------------------------

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        """Register a handler for a specific event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def subscribe_all(self, handler: Handler) -> None:
        """Register a handler that receives ALL events (for telemetry)."""
        self._global_subscribers.append(handler)

    def unsubscribe(self, event_type: EventType, handler: Handler) -> None:
        """Remove a handler."""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                h for h in self._subscribers[event_type] if h is not handler
            ]

    def unsubscribe_all(self, handler: Handler) -> None:
        """Remove a handler from both global and type-specific subscriptions."""
        self._global_subscribers = [h for h in self._global_subscribers if h is not handler]
        for event_type, handlers in list(self._subscribers.items()):
            self._subscribers[event_type] = [h for h in handlers if h is not handler]

    # -- Publishing ---------------------------------------------------------

    async def publish(
        self,
        event_type: EventType,
        data: dict[str, Any],
        source: str = "system",
        correlation_id: str | None = None,
    ) -> Event:
        """Publish an event to the bus. Returns the created Event."""
        event = Event(
            type=event_type,
            data=data,
            source=source,
            correlation_id=correlation_id,
        )
        await self._queue.put(event)
        return event

    def emit(
        self,
        event_type: EventType,
        data: dict[str, Any],
        source: str = "system",
        correlation_id: str | None = None,
    ) -> None:
        """Fire-and-forget sync wrapper around publish (for use in sync code)."""
        event = Event(
            type=event_type,
            data=data,
            source=source,
            correlation_id=correlation_id,
        )
        try:
            self._queue.put_nowait(event)
        except Exception:
            pass  # Queue full — drop non-critical sync event

    async def publish_event(self, event: Event) -> None:
        """Publish a pre-built Event object."""
        await self._queue.put(event)

    # -- Processing loop ----------------------------------------------------

    async def start(self) -> None:
        """Start the event processing loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._process_loop())

    async def stop(self) -> None:
        """Gracefully stop the bus."""
        self._running = False
        # Drain remaining events
        while not self._queue.empty():
            try:
                event = self._queue.get_nowait()
                await self._dispatch(event)
            except asyncio.QueueEmpty:
                break
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _process_loop(self) -> None:
        """Main event processing loop."""
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=0.5)
                await self._dispatch(event)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _dispatch(self, event: Event) -> None:
        """Dispatch event to all registered handlers."""
        # Record in log (deque auto-evicts oldest when maxlen exceeded)
        self._event_log.append(event)

        # Global subscribers (telemetry)
        for handler in self._global_subscribers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                # Never let a subscriber crash the bus
                self._event_log.append(Event(
                    type=EventType.ERROR,
                    data={"error": str(e), "handler": str(handler), "event_id": event.id},
                    source="neural_bus",
                ))

        # Type-specific subscribers
        handlers = self._subscribers.get(event.type, [])
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                self._event_log.append(Event(
                    type=EventType.ERROR,
                    data={"error": str(e), "handler": str(handler), "event_id": event.id},
                    source="neural_bus",
                ))

    # -- Introspection ------------------------------------------------------

    def get_event_log(self, limit: int = 100) -> list[Event]:
        """Return recent events for debugging."""
        return list(self._event_log)[-limit:]

    def get_correlation_chain(self, correlation_id: str) -> list[Event]:
        """Return all events in a correlation chain (reasoning trace)."""
        return [
            e for e in self._event_log
            if e.correlation_id == correlation_id or e.id == correlation_id
        ]

    @property
    def is_running(self) -> bool:
        return self._running
