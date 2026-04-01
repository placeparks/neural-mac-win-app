"""
Agent Mesh — Agent-to-agent communication layer.

Supports local (in-process) and remote (HTTP) mesh topologies.
Implements agent discovery, capability registration, and structured
message passing compatible with Google's A2A protocol concepts.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Awaitable

from neuralclaw.bus.neural_bus import NeuralBus, EventType


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class AgentStatus(Enum):
    ONLINE = auto()
    BUSY = auto()
    OFFLINE = auto()


@dataclass
class AgentCard:
    """
    Agent identity and capabilities — inspired by A2A protocol's Agent Card.

    This is what an agent advertises on the mesh so others can discover it.
    """
    agent_id: str
    name: str
    description: str
    capabilities: list[str]          # e.g. ["research", "code", "analysis"]
    status: AgentStatus = AgentStatus.ONLINE
    endpoint: str | None = None      # For remote agents: HTTP URL
    max_concurrent_tasks: int = 3
    active_tasks: int = 0
    registered_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return (
            self.status == AgentStatus.ONLINE
            and self.active_tasks < self.max_concurrent_tasks
        )


@dataclass
class MeshMessage:
    """A structured message between agents on the mesh."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    from_agent: str = ""
    to_agent: str = ""
    message_type: str = "task"       # task, response, broadcast, ping
    content: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None
    timestamp: float = field(default_factory=time.time)

    def reply(self, content: str, payload: dict[str, Any] | None = None) -> MeshMessage:
        """Create a reply to this message."""
        return MeshMessage(
            from_agent=self.to_agent,
            to_agent=self.from_agent,
            message_type="response",
            content=content,
            payload=payload or {},
            correlation_id=self.id,
        )


# Type for message handler functions
MessageHandler = Callable[[MeshMessage], Awaitable[MeshMessage | None]]


# ---------------------------------------------------------------------------
# Agent Mesh
# ---------------------------------------------------------------------------

class AgentMesh:
    """
    Agent-to-agent communication layer.

    Features:
    - Agent discovery by name or capability
    - Structured message passing (request/response)
    - Local (in-process) communication
    - Remote agent support via HTTP endpoints
    - Broadcast messages to all agents
    """

    def __init__(self, bus: NeuralBus | None = None) -> None:
        self._bus = bus
        self._agents: dict[str, AgentCard] = {}
        self._handlers: dict[str, MessageHandler] = {}
        self._message_log: list[MeshMessage] = []

    @property
    def agent_count(self) -> int:
        return len(self._agents)

    @property
    def online_agents(self) -> list[AgentCard]:
        return [a for a in self._agents.values() if a.status == AgentStatus.ONLINE]

    def register(
        self,
        name: str,
        description: str,
        capabilities: list[str],
        handler: MessageHandler,
        endpoint: str | None = None,
        max_concurrent: int = 3,
        metadata: dict[str, Any] | None = None,
    ) -> AgentCard:
        """
        Register an agent on the mesh.

        Args:
            name: Unique agent name.
            description: What this agent specializes in.
            capabilities: List of capability tags (e.g. ["research", "code"]).
            handler: Async function that processes incoming MeshMessages.
            endpoint: Optional HTTP URL for remote agents.
        """
        agent_id = uuid.uuid4().hex[:12]
        card = AgentCard(
            agent_id=agent_id,
            name=name,
            description=description,
            capabilities=capabilities,
            endpoint=endpoint,
            max_concurrent_tasks=max_concurrent,
            metadata=metadata or {},
        )
        self._agents[name] = card
        self._handlers[name] = handler

        if self._bus:
            self._bus.emit(EventType.ACTION_COMPLETE, {
                "mesh_event": "agent_registered",
                "agent": name,
                "capabilities": capabilities,
            })

        return card

    def unregister(self, name: str) -> None:
        """Remove an agent from the mesh."""
        self._agents.pop(name, None)
        self._handlers.pop(name, None)

    def get_agent(self, name: str) -> AgentCard | None:
        """Look up an agent by name."""
        return self._agents.get(name)

    def discover(
        self,
        capability: str | None = None,
        available_only: bool = True,
    ) -> list[AgentCard]:
        """
        Discover agents on the mesh, optionally filtered by capability.

        Args:
            capability: Filter agents that have this capability.
            available_only: Only return agents that are online and not at capacity.
        """
        results = list(self._agents.values())

        if capability:
            results = [a for a in results if capability in a.capabilities]

        if available_only:
            results = [a for a in results if a.available]

        return results

    async def send(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        message_type: str = "task",
        payload: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> MeshMessage | None:
        """
        Send a message to a specific agent and wait for a response.

        Args:
            from_agent: Sender agent name.
            to_agent: Recipient agent name.
            content: Message content.
            message_type: Type of message (task, ping, etc.).
            payload: Additional structured data.
            timeout: Max seconds to wait for response.

        Returns:
            Response MeshMessage, or None if timeout/error.
        """
        if to_agent not in self._agents:
            return None

        msg = MeshMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=message_type,
            content=content,
            payload=payload or {},
        )
        self._message_log.append(msg)

        card = self._agents[to_agent]
        card.active_tasks += 1
        card.status = AgentStatus.BUSY if card.active_tasks > 0 else AgentStatus.ONLINE

        try:
            if card.endpoint:
                # Remote agent — send via HTTP
                response = await self._send_remote(card.endpoint, msg, timeout)
            else:
                # Local agent — call handler directly
                handler = self._handlers.get(to_agent)
                if not handler:
                    return None
                response = await asyncio.wait_for(handler(msg), timeout=timeout)

            if response:
                self._message_log.append(response)
            return response

        except asyncio.TimeoutError:
            return MeshMessage(
                from_agent=to_agent,
                to_agent=from_agent,
                message_type="error",
                content=f"Agent '{to_agent}' timed out after {timeout}s",
                correlation_id=msg.id,
            )
        except Exception as e:
            return MeshMessage(
                from_agent=to_agent,
                to_agent=from_agent,
                message_type="error",
                content=f"Agent '{to_agent}' error: {e}",
                correlation_id=msg.id,
            )
        finally:
            card.active_tasks = max(0, card.active_tasks - 1)
            card.status = AgentStatus.ONLINE if card.active_tasks == 0 else AgentStatus.BUSY

    async def broadcast(
        self,
        from_agent: str,
        content: str,
        capability_filter: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> list[MeshMessage]:
        """
        Broadcast a message to all agents (or filtered by capability).

        Returns list of responses from agents that responded.
        """
        targets = self.discover(capability=capability_filter, available_only=True)
        targets = [a for a in targets if a.name != from_agent]

        responses = []
        for card in targets:
            resp = await self.send(
                from_agent=from_agent,
                to_agent=card.name,
                content=content,
                message_type="broadcast",
                payload=payload or {},
                timeout=30.0,
            )
            if resp and resp.message_type != "error":
                responses.append(resp)

        return responses

    async def _send_remote(
        self,
        endpoint: str,
        msg: MeshMessage,
        timeout: float,
    ) -> MeshMessage | None:
        """Send a message to a remote agent via HTTP POST."""
        try:
            import aiohttp

            payload = {
                "id": msg.id,
                "from": msg.from_agent,
                "to": msg.to_agent,
                "type": msg.message_type,
                "content": msg.content,
                "payload": msg.payload,
                "timestamp": msg.timestamp,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{endpoint}/a2a/message",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return MeshMessage(
                            from_agent=msg.to_agent,
                            to_agent=msg.from_agent,
                            message_type="response",
                            content=data.get("content", ""),
                            payload=data.get("payload", {}),
                            correlation_id=msg.id,
                        )
        except Exception:
            pass
        return None

    def get_mesh_status(self) -> dict[str, Any]:
        """Get overall mesh status summary."""
        return {
            "total_agents": len(self._agents),
            "online_agents": len(self.online_agents),
            "total_messages": len(self._message_log),
            "agents": [
                {
                    "name": a.name,
                    "status": a.status.name,
                    "capabilities": a.capabilities,
                    "active_tasks": a.active_tasks,
                    "endpoint": a.endpoint or "local",
                }
                for a in self._agents.values()
            ],
        }

    def record_message(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        message_type: str = "task",
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> MeshMessage:
        """Append a synthetic activity event to the mesh log."""
        msg = MeshMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=message_type,
            content=content,
            payload=payload or {},
            correlation_id=correlation_id,
        )
        self._message_log.append(msg)
        return msg

    def get_recent_messages(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent mesh traffic for dashboards and desktop clients."""
        return [
            {
                "id": msg.id,
                "from_agent": msg.from_agent,
                "to_agent": msg.to_agent,
                "message_type": msg.message_type,
                "content": msg.content,
                "payload": msg.payload,
                "timestamp": msg.timestamp,
            }
            for msg in self._message_log[-limit:]
        ]
