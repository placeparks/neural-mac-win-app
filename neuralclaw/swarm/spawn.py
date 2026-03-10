"""
Agent Spawner — Dynamic agent lifecycle management.

Provides a unified API to spawn, track, and destroy agents at runtime.
Each spawned agent is registered in both the AgentMesh (for communication)
and DelegationChain (for task execution).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.swarm.delegation import (
    DelegationChain,
    DelegationContext,
    DelegationResult,
    DelegationStatus,
)
from neuralclaw.swarm.mesh import AgentMesh, MeshMessage

MessageHandler = Callable[[MeshMessage], Awaitable[MeshMessage | None]]


@dataclass
class SpawnedAgent:
    """Record of a spawned agent."""

    name: str
    description: str
    capabilities: list[str]
    agent_id: str = ""
    endpoint: str | None = None
    source: str = "local"  # "local", "federation", "manual"
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentSpawner:
    """
    Unified agent lifecycle manager.

    Spawning an agent:
    1. Registers it in AgentMesh (for discovery and messaging)
    2. Registers a delegation executor in DelegationChain (for task handoff)
    3. Tracks it in internal registry for lifecycle management
    """

    def __init__(
        self,
        mesh: AgentMesh,
        delegation: DelegationChain,
        bus: NeuralBus | None = None,
    ) -> None:
        self._mesh = mesh
        self._delegation = delegation
        self._bus = bus
        self._agents: dict[str, SpawnedAgent] = {}

    @property
    def agents(self) -> dict[str, SpawnedAgent]:
        return dict(self._agents)

    @property
    def count(self) -> int:
        return len(self._agents)

    def spawn_local(
        self,
        name: str,
        description: str,
        capabilities: list[str],
        handler: MessageHandler,
        executor: Callable[[DelegationContext], Awaitable[DelegationResult]] | None = None,
        max_concurrent: int = 3,
        metadata: dict[str, Any] | None = None,
    ) -> SpawnedAgent:
        """
        Spawn a local in-process agent.

        Registers in both mesh and delegation chain. If no executor is
        provided, a default wrapper around the handler is created.
        """
        card = self._mesh.register(
            name=name,
            description=description,
            capabilities=capabilities,
            handler=handler,
            max_concurrent=max_concurrent,
            metadata=metadata,
        )

        if executor:
            self._delegation.register_executor(name, executor)
        else:
            self._delegation.register_executor(
                name, self._make_default_executor(name, handler),
            )

        agent = SpawnedAgent(
            name=name,
            description=description,
            capabilities=capabilities,
            agent_id=card.agent_id,
            source="local",
            metadata=metadata or {},
        )
        self._agents[name] = agent

        if self._bus:
            self._bus.emit(EventType.ACTION_COMPLETE, {
                "spawn_event": "agent_spawned",
                "agent": name,
                "source": "local",
                "capabilities": capabilities,
            })

        return agent

    def spawn_remote(
        self,
        name: str,
        description: str,
        capabilities: list[str],
        endpoint: str,
        source: str = "manual",
        metadata: dict[str, Any] | None = None,
    ) -> SpawnedAgent:
        """
        Spawn a remote agent (from federation or manual registration).

        Creates proxy handler/executor that forward via the mesh HTTP layer.
        """
        mesh_ref = self._mesh

        async def remote_handler(msg: MeshMessage) -> MeshMessage | None:
            return await mesh_ref._send_remote(endpoint, msg, timeout=60.0)

        async def remote_executor(ctx: DelegationContext) -> DelegationResult:
            result_msg = await mesh_ref.send(
                from_agent="spawner",
                to_agent=name,
                content=ctx.task_description,
                message_type="delegation",
                payload={
                    "constraints": ctx.constraints,
                    "expected_output_format": ctx.expected_output_format,
                    "max_steps": ctx.max_steps,
                },
                timeout=ctx.timeout_seconds,
            )
            if result_msg and result_msg.message_type != "error":
                return DelegationResult(
                    delegation_id="",
                    status=DelegationStatus.COMPLETED,
                    result=result_msg.content,
                    confidence=result_msg.payload.get("confidence", 0.7),
                )
            return DelegationResult(
                delegation_id="",
                status=DelegationStatus.FAILED,
                error=result_msg.content if result_msg else "No response from remote agent",
            )

        card = self._mesh.register(
            name=name,
            description=description,
            capabilities=capabilities,
            handler=remote_handler,
            endpoint=endpoint,
            metadata=metadata,
        )
        self._delegation.register_executor(name, remote_executor)

        agent = SpawnedAgent(
            name=name,
            description=description,
            capabilities=capabilities,
            agent_id=card.agent_id,
            endpoint=endpoint,
            source=source,
            metadata=metadata or {},
        )
        self._agents[name] = agent

        if self._bus:
            self._bus.emit(EventType.ACTION_COMPLETE, {
                "spawn_event": "agent_spawned",
                "agent": name,
                "source": source,
                "endpoint": endpoint,
                "capabilities": capabilities,
            })

        return agent

    def despawn(self, name: str) -> bool:
        """Remove an agent from mesh, delegation, and spawner registry."""
        if name not in self._agents:
            return False

        self._mesh.unregister(name)
        self._delegation.unregister_executor(name)
        del self._agents[name]

        if self._bus:
            self._bus.emit(EventType.ACTION_COMPLETE, {
                "spawn_event": "agent_despawned",
                "agent": name,
            })
        return True

    def get_status(self) -> list[dict[str, Any]]:
        """Return status of all spawned agents."""
        return [
            {
                "name": a.name,
                "description": a.description,
                "capabilities": a.capabilities,
                "source": a.source,
                "endpoint": a.endpoint or "local",
            }
            for a in self._agents.values()
        ]

    @staticmethod
    def _make_default_executor(
        name: str,
        handler: MessageHandler,
    ) -> Callable[[DelegationContext], Awaitable[DelegationResult]]:
        """Wrap a mesh MessageHandler into a delegation AgentExecutor."""

        async def executor(ctx: DelegationContext) -> DelegationResult:
            msg = MeshMessage(
                from_agent="delegation",
                to_agent=name,
                message_type="delegation",
                content=ctx.task_description,
                payload={"constraints": ctx.constraints},
            )
            response = await handler(msg)
            if response:
                return DelegationResult(
                    delegation_id="",
                    status=DelegationStatus.COMPLETED,
                    result=response.content,
                    confidence=response.payload.get("confidence", 0.7),
                )
            return DelegationResult(
                delegation_id="",
                status=DelegationStatus.FAILED,
                error=f"Agent '{name}' returned no response",
            )

        return executor
