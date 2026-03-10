"""
Federation — Cross-network agent discovery, trust, and messaging.

Enables NeuralClaw agents running on different machines or networks to
discover each other, establish trust, and exchange messages/tasks.
Implements a lightweight federation protocol over HTTP.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from neuralclaw import __version__
from neuralclaw.bus.neural_bus import NeuralBus, EventType


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class NodeStatus(Enum):
    ONLINE = auto()
    DEGRADED = auto()
    OFFLINE = auto()
    UNTRUSTED = auto()


@dataclass
class FederationNode:
    """A remote NeuralClaw agent in the federation."""
    node_id: str
    name: str
    endpoint: str                          # e.g. "https://agent.example.com:8100"
    capabilities: list[str] = field(default_factory=list)
    status: NodeStatus = NodeStatus.ONLINE
    trust_score: float = 0.5               # 0.0 (untrusted) → 1.0 (fully trusted)
    last_heartbeat: float = field(default_factory=time.time)
    version: str = ""
    region: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    successful_exchanges: int = 0
    failed_exchanges: int = 0

    @property
    def is_alive(self) -> bool:
        return time.time() - self.last_heartbeat < 120  # 2-minute timeout

    @property
    def reliability(self) -> float:
        total = self.successful_exchanges + self.failed_exchanges
        return self.successful_exchanges / total if total > 0 else 0.5

    def to_card(self) -> dict[str, Any]:
        """Serialize to a federation card for exchange."""
        return {
            "node_id": self.node_id,
            "name": self.name,
            "endpoint": self.endpoint,
            "capabilities": self.capabilities,
            "version": self.version,
            "region": self.region,
            "trust_score": self.trust_score,
        }


@dataclass
class FederationMessage:
    """A message exchanged between federated nodes."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    from_node: str = ""
    to_node: str = ""
    message_type: str = "task"     # task, response, discovery, heartbeat
    content: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    ttl: int = 3                   # Max hops before message is dropped

    def reply(self, content: str, payload: dict[str, Any] | None = None) -> FederationMessage:
        return FederationMessage(
            from_node=self.to_node,
            to_node=self.from_node,
            message_type="response",
            content=content,
            payload=payload or {},
        )


# ---------------------------------------------------------------------------
# Federation Registry
# ---------------------------------------------------------------------------

class FederationRegistry:
    """
    Tracks known federation nodes and their health.

    Handles node registration, heartbeat monitoring, and trust scoring.
    """

    HEARTBEAT_INTERVAL = 60     # seconds between heartbeats
    STALE_THRESHOLD = 180       # seconds before node is marked offline
    TRUST_INCREMENT = 0.02      # Trust gain per successful exchange
    TRUST_DECREMENT = 0.05      # Trust loss per failure
    MIN_TRUST = 0.0
    MAX_TRUST = 1.0

    def __init__(self) -> None:
        self._nodes: dict[str, FederationNode] = {}
        self._blacklist: set[str] = set()

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def online_nodes(self) -> list[FederationNode]:
        return [n for n in self._nodes.values() if n.is_alive and n.status != NodeStatus.UNTRUSTED]

    def register(
        self,
        name: str,
        endpoint: str,
        capabilities: list[str] | None = None,
        version: str = "",
        region: str = "",
        trust_score: float = 0.5,
    ) -> FederationNode:
        """Register a new federation node."""
        node_id = hashlib.sha256(endpoint.encode()).hexdigest()[:16]

        if node_id in self._blacklist:
            raise ValueError(f"Node {endpoint} is blacklisted")

        node = FederationNode(
            node_id=node_id,
            name=name,
            endpoint=endpoint,
            capabilities=capabilities or [],
            version=version,
            region=region,
            trust_score=trust_score,
        )
        self._nodes[node_id] = node
        return node

    def unregister(self, node_id: str) -> None:
        """Remove a node from the registry."""
        self._nodes.pop(node_id, None)

    def blacklist(self, node_id: str) -> None:
        """Blacklist a node (ban from federation)."""
        self._blacklist.add(node_id)
        self.unregister(node_id)

    def get_node(self, node_id: str) -> FederationNode | None:
        return self._nodes.get(node_id)

    def find_by_capability(self, capability: str) -> list[FederationNode]:
        """Find nodes that advertise a specific capability."""
        return [
            n for n in self.online_nodes
            if capability in n.capabilities
        ]

    def find_by_region(self, region: str) -> list[FederationNode]:
        """Find nodes in a specific region."""
        return [n for n in self.online_nodes if n.region == region]

    def record_heartbeat(self, node_id: str) -> None:
        """Update a node's heartbeat timestamp."""
        node = self._nodes.get(node_id)
        if node:
            node.last_heartbeat = time.time()
            if node.status == NodeStatus.OFFLINE:
                node.status = NodeStatus.ONLINE

    def record_success(self, node_id: str) -> None:
        """Record a successful exchange with a node."""
        node = self._nodes.get(node_id)
        if node:
            node.successful_exchanges += 1
            node.trust_score = min(
                self.MAX_TRUST,
                node.trust_score + self.TRUST_INCREMENT,
            )

    def record_failure(self, node_id: str) -> None:
        """Record a failed exchange with a node."""
        node = self._nodes.get(node_id)
        if node:
            node.failed_exchanges += 1
            node.trust_score = max(
                self.MIN_TRUST,
                node.trust_score - self.TRUST_DECREMENT,
            )
            if node.trust_score <= 0.1:
                node.status = NodeStatus.UNTRUSTED

    def sweep_stale(self) -> list[str]:
        """Mark stale nodes as offline. Returns list of node IDs marked."""
        stale = []
        now = time.time()
        for node in self._nodes.values():
            if now - node.last_heartbeat > self.STALE_THRESHOLD:
                if node.status != NodeStatus.OFFLINE:
                    node.status = NodeStatus.OFFLINE
                    stale.append(node.node_id)
        return stale

    def get_status(self) -> dict[str, Any]:
        """Get federation status summary."""
        return {
            "total_nodes": len(self._nodes),
            "online_nodes": len(self.online_nodes),
            "blacklisted": len(self._blacklist),
            "nodes": [
                {
                    "name": n.name,
                    "endpoint": n.endpoint,
                    "status": n.status.name,
                    "trust_score": round(n.trust_score, 2),
                    "capabilities": n.capabilities,
                    "region": n.region,
                    "alive": n.is_alive,
                    "reliability": round(n.reliability, 2),
                }
                for n in self._nodes.values()
            ],
        }


# ---------------------------------------------------------------------------
# Federation Protocol
# ---------------------------------------------------------------------------

class FederationProtocol:
    """
    HTTP-based federation protocol for cross-network agent communication.

    Supports:
    - Node discovery via /federation/discover
    - Task delegation via /federation/message
    - Heartbeat monitoring via /federation/heartbeat
    - Trust-gated message relay
    """

    MIN_TRUST_FOR_RELAY = 0.3   # Minimum trust to accept a message
    MAX_MESSAGE_LOG = 500       # Cap message log to prevent memory leak
    MAX_REGISTERED_NODES = 100  # Prevent registration spam DoS

    def __init__(
        self,
        node_name: str,
        bus: NeuralBus | None = None,
        port: int = 8100,
        bind_host: str = "127.0.0.1",
    ) -> None:
        self._node_name = node_name
        self._bus = bus
        self._port = port
        self._bind_host = bind_host
        self._registry = FederationRegistry()
        self._node_id = hashlib.sha256(
            f"{node_name}:{port}".encode()
        ).hexdigest()[:16]
        self._message_log: list[FederationMessage] = []
        self._running = False
        self._app = None
        self._runner = None

    @property
    def registry(self) -> FederationRegistry:
        return self._registry

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def node_name(self) -> str:
        return self._node_name

    def get_node_card(self) -> dict[str, Any]:
        """Get this node's federation card."""
        return {
            "node_id": self._node_id,
            "name": self._node_name,
            "endpoint": f"http://localhost:{self._port}",
            "version": __version__,
        }

    async def start(self) -> None:
        """Start the federation HTTP server."""
        try:
            import aiohttp
            from aiohttp import web

            self._app = web.Application()
            self._app.router.add_post("/federation/discover", self._handle_discover)
            self._app.router.add_post("/federation/message", self._handle_message)
            self._app.router.add_post("/federation/heartbeat", self._handle_heartbeat)
            self._app.router.add_get("/federation/status", self._handle_status)

            self._runner = web.AppRunner(self._app)
            await self._runner.setup()
            site = web.TCPSite(self._runner, self._bind_host, self._port)
            await site.start()
            self._running = True

            if self._bus:
                self._bus.emit(EventType.ACTION_COMPLETE, {
                    "federation": "started",
                    "port": self._port,
                })
        except Exception as e:
            print(f"[Federation] Failed to start: {e}")

    async def stop(self) -> None:
        """Stop the federation server."""
        self._running = False
        if self._runner:
            await self._runner.cleanup()

    async def join_federation(self, seed_endpoint: str) -> bool:
        """
        Join a federation by connecting to a seed node.

        Sends a discovery message with our card, receives
        the peer's card, and registers them in our registry.
        """
        try:
            import aiohttp

            our_card = self.get_node_card()

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{seed_endpoint}/federation/discover",
                    json=our_card,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        peer_card = await resp.json()
                        self._registry.register(
                            name=peer_card.get("name", "unknown"),
                            endpoint=seed_endpoint,
                            capabilities=peer_card.get("capabilities", []),
                            version=peer_card.get("version", ""),
                            region=peer_card.get("region", ""),
                        )
                        return True
        except Exception as e:
            print(f"[Federation] Join failed: {e}")
        return False

    async def send_message(
        self,
        target_node_id: str,
        content: str,
        message_type: str = "task",
        payload: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> FederationMessage | None:
        """Send a message to a federated node."""
        node = self._registry.get_node(target_node_id)
        if not node:
            return None

        if node.trust_score < self.MIN_TRUST_FOR_RELAY:
            return None

        msg = FederationMessage(
            from_node=self._node_id,
            to_node=target_node_id,
            message_type=message_type,
            content=content,
            payload=payload or {},
        )
        self._message_log.append(msg)
        if len(self._message_log) > self.MAX_MESSAGE_LOG:
            self._message_log = self._message_log[-self.MAX_MESSAGE_LOG:]

        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{node.endpoint}/federation/message",
                    json={
                        "id": msg.id,
                        "from_node": msg.from_node,
                        "to_node": msg.to_node,
                        "type": msg.message_type,
                        "content": msg.content,
                        "payload": msg.payload,
                        "ttl": msg.ttl,
                    },
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    if resp.status == 200:
                        self._registry.record_success(target_node_id)
                        data = await resp.json()
                        return msg.reply(
                            content=data.get("content", ""),
                            payload=data.get("payload", {}),
                        )
                    else:
                        self._registry.record_failure(target_node_id)
        except Exception:
            self._registry.record_failure(target_node_id)

        return None

    async def broadcast(
        self,
        content: str,
        capability_filter: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> list[FederationMessage]:
        """Broadcast a message to all (or filtered) federation peers."""
        targets = (
            self._registry.find_by_capability(capability_filter)
            if capability_filter
            else self._registry.online_nodes
        )

        responses = []
        for node in targets:
            resp = await self.send_message(
                node.node_id, content,
                message_type="broadcast",
                payload=payload,
            )
            if resp:
                responses.append(resp)

        return responses

    async def send_heartbeats(self) -> None:
        """Send heartbeats to all known peers."""
        for node in list(self._registry.online_nodes):
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{node.endpoint}/federation/heartbeat",
                        json=self.get_node_card(),
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status == 200:
                            self._registry.record_heartbeat(node.node_id)
            except Exception:
                self._registry.record_failure(node.node_id)

        # Sweep stale nodes
        self._registry.sweep_stale()

    # -- HTTP handlers ------------------------------------------------------

    async def _handle_discover(self, request: Any) -> Any:
        """Handle discovery request — exchange node cards."""
        from aiohttp import web
        try:
            # Rate-limit registrations to prevent memory DoS
            if self._registry.node_count >= self.MAX_REGISTERED_NODES:
                return web.json_response(
                    {"error": "Node registry full"}, status=429
                )
            peer_card = await request.json()
            self._registry.register(
                name=peer_card.get("name", "unknown"),
                endpoint=peer_card.get("endpoint", ""),
                capabilities=peer_card.get("capabilities", []),
                version=peer_card.get("version", ""),
                region=peer_card.get("region", ""),
            )
            return web.json_response(self.get_node_card())
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    def set_message_handler(
        self,
        handler: Any,  # async (content: str, from_node: str) -> str
    ) -> None:
        """Set handler for incoming task messages. Called with (content, from_node) -> response str."""
        self._message_handler = handler

    async def _handle_message(self, request: Any) -> Any:
        """Handle incoming federation message — process through pipeline if handler set."""
        from aiohttp import web
        try:
            data = await request.json()

            # TTL check
            ttl = data.get("ttl", 0)
            if ttl <= 0:
                return web.json_response({"error": "TTL expired"}, status=400)

            # Trust check
            from_node = data.get("from_node", "")
            node = self._registry.get_node(from_node)
            if node and node.trust_score < self.MIN_TRUST_FOR_RELAY:
                return web.json_response({"error": "Insufficient trust"}, status=403)

            msg = FederationMessage(
                id=data.get("id", ""),
                from_node=from_node,
                to_node=data.get("to_node", ""),
                message_type=data.get("type", "task"),
                content=data.get("content", "")[:8000],
                payload=data.get("payload", {}),
                ttl=ttl - 1,
            )
            self._message_log.append(msg)
            if len(self._message_log) > self.MAX_MESSAGE_LOG:
                self._message_log = self._message_log[-self.MAX_MESSAGE_LOG:]

            if self._bus:
                self._bus.emit(EventType.SIGNAL_RECEIVED, {
                    "federation_message": True,
                    "from": from_node,
                    "type": msg.message_type,
                })

            # Process through cognitive pipeline if handler is set and message is a task
            response_content = f"Message received by {self._node_name}"
            response_payload: dict[str, Any] = {"status": "acknowledged"}
            handler = getattr(self, "_message_handler", None)
            if handler and msg.message_type == "task":
                try:
                    from_name = node.name if node else from_node[:8]
                    response_content = await handler(msg.content, from_name)
                    response_payload = {"status": "processed"}
                    if node:
                        self._registry.record_success(from_node)
                except Exception as exc:
                    response_content = f"Processing failed: {exc}"
                    response_payload = {"status": "error"}

            return web.json_response({
                "content": response_content,
                "payload": response_payload,
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def _handle_heartbeat(self, request: Any) -> Any:
        """Handle heartbeat from a peer."""
        from aiohttp import web
        try:
            peer_card = await request.json()
            node_id = peer_card.get("node_id", "")
            if node_id:
                self._registry.record_heartbeat(node_id)
            return web.json_response({"status": "ok"})
        except Exception:
            return web.json_response({"status": "ok"})

    async def _handle_status(self, request: Any) -> Any:
        """Return federation status."""
        from aiohttp import web
        return web.json_response(self._registry.get_status())

    def get_message_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent federation messages."""
        return [
            {
                "id": m.id,
                "from": m.from_node,
                "to": m.to_node,
                "type": m.message_type,
                "content": m.content[:200],
                "timestamp": m.timestamp,
            }
            for m in self._message_log[-limit:]
        ]


# ---------------------------------------------------------------------------
# Federation ↔ Mesh/Delegation bridge
# ---------------------------------------------------------------------------


class FederationBridge:
    """
    Bridges federation node discovery to mesh/delegation via AgentSpawner.

    When a new federation node is discovered, it is spawned as a remote
    agent in the mesh (prefixed ``fed:``). When a node goes offline, it
    is despawned.  Runs a periodic sync task to keep the mesh in sync
    with the federation registry.
    """

    def __init__(
        self,
        federation: FederationProtocol,
        spawner: Any,  # AgentSpawner — avoids circular import
        bus: NeuralBus | None = None,
    ) -> None:
        self._federation = federation
        self._spawner = spawner
        self._bus = bus
        self._synced_nodes: set[str] = set()
        self._sync_task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self, sync_interval: float = 30.0) -> None:
        """Start periodic sync between federation registry and mesh."""
        self._running = True
        self._sync_task = asyncio.create_task(self._sync_loop(sync_interval))

    async def stop(self) -> None:
        """Stop the sync loop."""
        self._running = False
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass

    async def _sync_loop(self, interval: float) -> None:
        while self._running:
            try:
                self.sync()
            except Exception as exc:
                if self._bus:
                    self._bus.emit(EventType.ERROR, {
                        "error": f"Federation bridge sync failed: {exc}",
                        "component": "federation_bridge",
                    })
            await asyncio.sleep(interval)

    def sync(self) -> None:
        """One-shot sync: register new nodes, remove stale ones."""
        registry = self._federation.registry
        current_online = {n.node_id for n in registry.online_nodes}

        # Add new nodes
        for node in registry.online_nodes:
            if node.node_id in self._synced_nodes:
                continue
            agent_name = f"fed:{node.name}"
            if agent_name in self._spawner.agents:
                continue
            self._spawner.spawn_remote(
                name=agent_name,
                description=f"Federated agent from {node.endpoint}",
                capabilities=node.capabilities,
                endpoint=node.endpoint,
                source="federation",
                metadata={
                    "federation_node_id": node.node_id,
                    "trust_score": node.trust_score,
                    "region": node.region,
                },
            )
            self._synced_nodes.add(node.node_id)

        # Remove nodes that went offline
        stale = self._synced_nodes - current_online
        for node_id in stale:
            node = registry.get_node(node_id)
            if node:
                self._spawner.despawn(f"fed:{node.name}")
            self._synced_nodes.discard(node_id)
