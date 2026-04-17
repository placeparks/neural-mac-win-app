"""Tests for Federation integration, AgentSpawner, and FederationBridge."""

from __future__ import annotations

import asyncio
import time

import pytest

from neuralclaw.bus.neural_bus import NeuralBus
from neuralclaw.cortex.reasoning.deliberate import ToolDef
from neuralclaw.swarm.mesh import AgentMesh, MeshMessage
from neuralclaw.swarm.delegation import (
    DelegationChain,
    DelegationContext,
    DelegationResult,
    DelegationStatus,
)
from neuralclaw.swarm.federation import (
    FederationProtocol,
    FederationRegistry,
    FederationBridge,
    NodeStatus,
)
from neuralclaw.swarm.spawn import AgentSpawner, SpawnedAgent
from neuralclaw.swarm.agent_runtime import AgentRuntime
from neuralclaw.swarm.agent_store import AgentDefinition
from neuralclaw.config import FederationConfig


# ---------------------------------------------------------------------------
# FederationConfig
# ---------------------------------------------------------------------------


class TestFederationConfig:
    def test_defaults(self):
        cfg = FederationConfig()
        assert cfg.enabled is True
        assert cfg.port == 8100
        assert cfg.bind_host == "127.0.0.1"
        assert cfg.seed_nodes == []
        assert cfg.heartbeat_interval == 60
        assert cfg.node_name == ""

    def test_custom(self):
        cfg = FederationConfig(port=9999, seed_nodes=["http://peer:8100"])
        assert cfg.port == 9999
        assert len(cfg.seed_nodes) == 1


# ---------------------------------------------------------------------------
# FederationRegistry
# ---------------------------------------------------------------------------


class TestFederationRegistry:
    def setup_method(self):
        self.registry = FederationRegistry()

    def test_register_and_count(self):
        self.registry.register("node-a", "http://localhost:9001")
        assert self.registry.node_count == 1

    def test_find_by_capability(self):
        self.registry.register("a", "http://a:1", capabilities=["search"])
        self.registry.register("b", "http://b:1", capabilities=["code"])
        results = self.registry.find_by_capability("search")
        assert len(results) == 1
        assert results[0].name == "a"

    def test_trust_scoring(self):
        node = self.registry.register("n", "http://n:1")
        initial = node.trust_score
        self.registry.record_success(node.node_id)
        assert node.trust_score > initial

    def test_trust_decrement(self):
        node = self.registry.register("n", "http://n:1")
        initial = node.trust_score
        self.registry.record_failure(node.node_id)
        assert node.trust_score < initial

    def test_sweep_stale(self):
        node = self.registry.register("stale", "http://s:1")
        node.last_heartbeat = time.time() - 300  # 5 minutes ago
        stale_ids = self.registry.sweep_stale()
        assert node.node_id in stale_ids
        assert node.status == NodeStatus.OFFLINE

    def test_get_status(self):
        self.registry.register("x", "http://x:1")
        status = self.registry.get_status()
        assert status["total_nodes"] == 1
        assert len(status["nodes"]) == 1

    def test_blacklist(self):
        node = self.registry.register("bad", "http://evil:666")
        self.registry.blacklist(node.node_id)
        assert self.registry.node_count == 0
        with pytest.raises(ValueError):
            self.registry.register("bad2", "http://evil:666")

    def test_get_node(self):
        node = self.registry.register("x", "http://x:1")
        found = self.registry.get_node(node.node_id)
        assert found is not None
        assert found.name == "x"

    def test_get_node_missing(self):
        assert self.registry.get_node("nonexistent") is None

    def test_heartbeat_restores_online(self):
        node = self.registry.register("h", "http://h:1")
        node.status = NodeStatus.OFFLINE
        self.registry.record_heartbeat(node.node_id)
        assert node.status == NodeStatus.ONLINE


# ---------------------------------------------------------------------------
# FederationProtocol
# ---------------------------------------------------------------------------


class TestFederationProtocol:
    def test_node_card(self):
        fp = FederationProtocol("test-node", port=9999)
        card = fp.get_node_card()
        assert card["name"] == "test-node"
        assert "9999" in card["endpoint"]

    def test_node_id_deterministic(self):
        fp1 = FederationProtocol("a", port=100)
        fp2 = FederationProtocol("a", port=100)
        assert fp1.node_id == fp2.node_id

    def test_node_id_differs_for_different_config(self):
        fp1 = FederationProtocol("a", port=100)
        fp2 = FederationProtocol("b", port=200)
        assert fp1.node_id != fp2.node_id

    def test_message_log_empty(self):
        fp = FederationProtocol("test")
        assert fp.get_message_log() == []

    def test_registry_accessible(self):
        fp = FederationProtocol("test")
        assert isinstance(fp.registry, FederationRegistry)


# ---------------------------------------------------------------------------
# AgentSpawner
# ---------------------------------------------------------------------------


class TestAgentSpawner:
    def setup_method(self):
        self.bus = NeuralBus()
        self.mesh = AgentMesh(bus=self.bus)
        self.delegation = DelegationChain(bus=self.bus)
        self.spawner = AgentSpawner(self.mesh, self.delegation, self.bus)

    def test_spawn_local(self):
        async def handler(msg):
            return msg.reply("ok")

        agent = self.spawner.spawn_local(
            name="worker",
            description="A worker",
            capabilities=["work"],
            handler=handler,
        )
        assert isinstance(agent, SpawnedAgent)
        assert agent.name == "worker"
        assert agent.source == "local"
        assert self.spawner.count == 1
        assert self.mesh.agent_count >= 1
        assert "worker" in self.delegation.get_available_agents()

    def test_spawn_remote(self):
        agent = self.spawner.spawn_remote(
            name="remote-1",
            description="Remote agent",
            capabilities=["search"],
            endpoint="http://peer:8100",
            source="federation",
        )
        assert agent.endpoint == "http://peer:8100"
        assert agent.source == "federation"
        assert self.spawner.count == 1
        assert self.mesh.get_agent("remote-1") is not None
        assert "remote-1" in self.delegation.get_available_agents()

    def test_despawn(self):
        async def handler(msg):
            return msg.reply("ok")

        self.spawner.spawn_local("temp", "Temp", ["t"], handler)
        assert self.spawner.count == 1
        result = self.spawner.despawn("temp")
        assert result is True
        assert self.spawner.count == 0
        assert self.mesh.get_agent("temp") is None
        assert "temp" not in self.delegation.get_available_agents()

    def test_despawn_nonexistent(self):
        assert self.spawner.despawn("ghost") is False

    def test_get_status(self):
        async def handler(msg):
            return msg.reply("ok")

        self.spawner.spawn_local("a", "A", ["x"], handler)
        status = self.spawner.get_status()
        assert len(status) == 1
        assert status[0]["name"] == "a"
        assert status[0]["source"] == "local"

    def test_agents_property(self):
        async def handler(msg):
            return msg.reply("ok")

        self.spawner.spawn_local("b", "B", ["y"], handler)
        agents = self.spawner.agents
        assert "b" in agents
        assert isinstance(agents["b"], SpawnedAgent)

    @pytest.mark.asyncio
    async def test_local_agent_delegation(self):
        """Spawned local agent should be usable via delegation."""

        async def handler(msg):
            return msg.reply("handler result", payload={"confidence": 0.95})

        self.spawner.spawn_local("smart", "Smart", ["think"], handler)
        result = await self.delegation.delegate(
            "smart",
            DelegationContext(task_description="Think about this"),
        )
        assert result.status == DelegationStatus.COMPLETED
        assert "handler result" in result.result

    @pytest.mark.asyncio
    async def test_local_agent_with_custom_executor(self):
        """Spawned agent with explicit executor should use that executor."""

        async def handler(msg):
            return msg.reply("mesh path")

        async def executor(ctx):
            return DelegationResult(
                delegation_id="",
                status=DelegationStatus.COMPLETED,
                result="executor path",
                confidence=0.99,
            )

        self.spawner.spawn_local("dual", "Dual", ["x"], handler, executor=executor)
        result = await self.delegation.delegate(
            "dual",
            DelegationContext(task_description="Test"),
        )
        assert result.result == "executor path"

    @pytest.mark.asyncio
    async def test_mesh_send_to_spawned_agent(self):
        """Spawned agent should be reachable via mesh.send()."""

        async def handler(msg):
            return msg.reply(f"echo: {msg.content}")

        self.spawner.spawn_local("echo", "Echo", ["echo"], handler)
        response = await self.mesh.send(
            from_agent="test",
            to_agent="echo",
            content="hello",
        )
        assert response is not None
        assert "echo: hello" in response.content

    def test_agent_runtime_rebuilds_provider_on_context_update(self):
        definition = AgentDefinition(
            agent_id="agent-1",
            name="writer",
            provider="local",
            model="qwen3.5:35b",
            base_url="http://localhost:11434/v1",
            metadata={},
        )
        runtime = AgentRuntime(definition=definition)

        runtime.update_execution_context(
            requested_model="qwen3.5:35b",
            effective_model="qwen3.5:9b",
            base_url="http://localhost:11434/v1",
        )

        assert runtime.definition.model == "qwen3.5:9b"
        assert runtime.definition.base_url == "http://localhost:11434/v1"
        assert getattr(runtime.provider, "_model", "") == "qwen3.5:9b"
        assert getattr(runtime.provider, "_base_url", "") == "http://localhost:11434/v1"

    @pytest.mark.asyncio
    async def test_agent_runtime_tool_failures_keep_non_empty_error_detail(self):
        class BlankError(Exception):
            def __str__(self) -> str:
                return ""

        async def boom_tool(**_kwargs):
            raise BlankError()

        definition = AgentDefinition(
            agent_id="agent-1",
            name="writer",
            provider="local",
            model="qwen3.5:35b",
            base_url="http://localhost:11434/v1",
            metadata={},
        )
        runtime = AgentRuntime(definition=definition)

        result = await runtime._execute_tool_call(
            type("ToolCall", (), {"name": "forge_skill", "arguments": {}})(),
            [
                ToolDef(
                    name="forge_skill",
                    description="Forge a skill",
                    parameters={"type": "object", "properties": {}},
                    handler=boom_tool,
                )
            ],
        )

        assert result["error"] == "Tool 'forge_skill' failed: BlankError()"


# ---------------------------------------------------------------------------
# FederationBridge
# ---------------------------------------------------------------------------


class TestFederationBridge:
    def setup_method(self):
        self.bus = NeuralBus()
        self.mesh = AgentMesh(bus=self.bus)
        self.delegation = DelegationChain(bus=self.bus)
        self.spawner = AgentSpawner(self.mesh, self.delegation, self.bus)
        self.federation = FederationProtocol("test-node", bus=self.bus, port=19999)
        self.bridge = FederationBridge(self.federation, self.spawner, self.bus)

    def test_sync_adds_nodes(self):
        self.federation.registry.register(
            name="peer-a",
            endpoint="http://peer-a:8100",
            capabilities=["research"],
        )
        self.bridge.sync()
        assert "fed:peer-a" in self.spawner.agents
        assert self.mesh.get_agent("fed:peer-a") is not None
        assert "fed:peer-a" in self.delegation.get_available_agents()

    def test_sync_removes_offline_nodes(self):
        node = self.federation.registry.register(
            name="peer-b",
            endpoint="http://peer-b:8100",
        )
        self.bridge.sync()
        assert "fed:peer-b" in self.spawner.agents

        # Make node stale
        node.last_heartbeat = time.time() - 300
        self.federation.registry.sweep_stale()
        self.bridge.sync()
        assert "fed:peer-b" not in self.spawner.agents

    def test_sync_idempotent(self):
        self.federation.registry.register(
            name="peer-c",
            endpoint="http://peer-c:8100",
        )
        self.bridge.sync()
        self.bridge.sync()
        assert self.spawner.count == 1

    @pytest.mark.asyncio
    async def test_start_stop(self):
        await self.bridge.start(sync_interval=0.1)
        assert self.bridge._running is True
        await asyncio.sleep(0.05)
        await self.bridge.stop()
        assert self.bridge._running is False


# ---------------------------------------------------------------------------
# DelegationChain.unregister_executor
# ---------------------------------------------------------------------------


class TestDelegationUnregister:
    def test_unregister_executor(self):
        chain = DelegationChain(bus=NeuralBus())

        async def noop(ctx):
            pass

        chain.register_executor("agent", noop)
        assert "agent" in chain.get_available_agents()
        chain.unregister_executor("agent")
        assert "agent" not in chain.get_available_agents()

    def test_unregister_nonexistent(self):
        chain = DelegationChain(bus=NeuralBus())
        chain.unregister_executor("ghost")  # Should not raise
