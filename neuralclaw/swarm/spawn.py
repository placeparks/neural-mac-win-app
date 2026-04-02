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

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from neuralclaw.swarm.agent_runtime import AgentRuntime
    from neuralclaw.swarm.agent_store import AgentDefinition

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
        self._runtimes: dict[str, "AgentRuntime"] = {}

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
        if name in self._agents:
            return self._agents[name]

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

    def spawn_from_definition(
        self,
        defn: "AgentDefinition",
        episodic: Any | None = None,
        semantic: Any | None = None,
        procedural: Any | None = None,
        shared_bridge: Any | None = None,
    ) -> SpawnedAgent:
        """
        Spawn a local agent from a persistent AgentDefinition.

        Creates an AgentRuntime with its own provider + memory namespace,
        then registers it in the mesh and delegation chain.
        """
        from neuralclaw.swarm.agent_runtime import AgentRuntime
        from neuralclaw.cortex.memory.procedural import ProceduralMemory
        from neuralclaw.cortex.memory.semantic import SemanticMemory

        if defn.name in self._agents:
            return self._agents[defn.name]

        # Build namespaced semantic memory if a base semantic instance is provided
        namespaced_semantic = None
        if semantic is not None:
            namespaced_semantic = SemanticMemory(
                db_path=semantic._db_path,
                db_pool=semantic._db_pool,
                namespace=defn.memory_namespace or f"agent:{defn.name}",
            )
            namespaced_semantic._db = semantic._db

        namespaced_procedural = None
        if procedural is not None:
            namespaced_procedural = ProceduralMemory(
                db_path=procedural._db_path,
                bus=procedural._bus,
                db_pool=procedural._db_pool,
                namespace=defn.memory_namespace or f"agent:{defn.name}",
            )
            namespaced_procedural._db = procedural._db

        runtime = AgentRuntime(
            definition=defn,
            episodic=episodic,
            semantic=namespaced_semantic,
            procedural=namespaced_procedural,
            shared_bridge=shared_bridge,
        )
        self._runtimes[defn.name] = runtime

        return self.spawn_local(
            name=defn.name,
            description=defn.description,
            capabilities=defn.capabilities,
            handler=runtime.handle_message,
            executor=runtime.handle_delegation,
            metadata={
                "agent_id": defn.agent_id,
                "provider": defn.provider,
                "model": defn.model,
                "base_url": defn.base_url,
                "source": "definition",
                "memory_namespace": defn.memory_namespace,
            },
        )

    def get_runtime(self, name: str) -> "AgentRuntime | None":
        """Get the runtime for a spawned agent."""
        return self._runtimes.get(name)

    def update_runtime_context(
        self,
        name: str,
        *,
        requested_model: str | None = None,
        effective_model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        runtime = self._runtimes.get(name)
        if not runtime:
            return
        runtime.update_execution_context(
            requested_model=requested_model,
            effective_model=effective_model,
            base_url=base_url,
        )

    def despawn(self, name: str) -> bool:
        """Remove an agent from mesh, delegation, and spawner registry."""
        if name not in self._agents:
            return False

        self._mesh.unregister(name)
        self._delegation.unregister_executor(name)
        self._runtimes.pop(name, None)
        del self._agents[name]

        if self._bus:
            self._bus.emit(EventType.ACTION_COMPLETE, {
                "spawn_event": "agent_despawned",
                "agent": name,
            })
        return True

    def get_status(self) -> list[dict[str, Any]]:
        """Return status of all spawned agents."""
        payload: list[dict[str, Any]] = []
        for agent in self._agents.values():
            mesh_card = self._mesh.get_agent(agent.name)
            runtime = self._runtimes.get(agent.name)
            metrics = runtime.get_metrics() if runtime else {}
            requested_model = str(metrics.get("requested_model") or agent.metadata.get("model", ""))
            effective_model = str(metrics.get("effective_model") or requested_model)
            payload.append(
                {
                    "name": agent.name,
                    "description": agent.description,
                    "capabilities": agent.capabilities,
                    "status": (mesh_card.status.name.lower() if mesh_card else "offline"),
                    "active_tasks": (mesh_card.active_tasks if mesh_card else 0),
                    "source": agent.source,
                    "endpoint": agent.endpoint or "local",
                    "provider": agent.metadata.get("provider", ""),
                    "model": requested_model,
                    "requested_model": requested_model,
                    "effective_model": effective_model,
                    "base_url": str(metrics.get("base_url") or agent.metadata.get("base_url", "") or "local"),
                    "memory_namespace": metrics.get("memory_namespace") or agent.metadata.get("memory_namespace", ""),
                    "last_task_at": metrics.get("last_task_at"),
                    "avg_latency_ms": metrics.get("avg_latency_ms"),
                    "token_usage": metrics.get("token_usage"),
                    "last_error": metrics.get("last_error"),
                    "success_count": metrics.get("success_count", 0),
                    "failure_count": metrics.get("failure_count", 0),
                    "recent_tasks": metrics.get("recent_tasks", []),
                    "recent_logs": metrics.get("recent_logs", []),
                }
            )
        return payload

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
