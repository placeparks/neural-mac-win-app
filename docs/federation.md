# 🌐 Federation

Federation enables NeuralClaw agents running on **different machines or networks**
to discover each other, establish trust, and exchange tasks. It uses a
lightweight HTTP/JSON protocol with automatic trust scoring.

---

## Concept

```
  Machine A                           Machine B
┌──────────────┐                  ┌──────────────┐
│  NeuralClaw  │  ◄── HTTP ──►   │  NeuralClaw  │
│  Agent "pi"  │   Federation    │  Agent "desk" │
│  :8100       │   Protocol      │  :8100        │
└──────────────┘                  └──────────────┘
     │                                    │
     └────── discover, message, ──────────┘
              heartbeat, status
```

Each agent runs an HTTP server that exposes four endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/federation/discover` | POST | Exchange node cards (identity) |
| `/federation/message` | POST | Send a task or message |
| `/federation/heartbeat` | POST | Health check / keepalive |
| `/federation/status` | GET | View all known nodes |

---

## Quick Start: Federating Two Agents

### Agent 1 (e.g., Raspberry Pi)

```python
import asyncio
from neuralclaw.swarm.federation import FederationProtocol

async def main():
    fed = FederationProtocol(node_name="pi-agent", port=8100)
    await fed.start()
    print(f"Federation server running on :8100")
    print(f"Node ID: {fed.node_id}")

    # Keep running
    await asyncio.Event().wait()

asyncio.run(main())
```

### Agent 2 (e.g., Desktop / another Pi)

```python
import asyncio
from neuralclaw.swarm.federation import FederationProtocol

async def main():
    fed = FederationProtocol(node_name="desktop-agent", port=8100)
    await fed.start()

    # Join the federation by connecting to Agent 1
    success = await fed.join_federation("http://192.168.1.50:8100")
    if success:
        print("✓ Connected to pi-agent!")
    else:
        print("✗ Failed to connect")

    # Check federation status
    status = fed.registry.get_status()
    print(f"Known nodes: {status['total_nodes']}")
    print(f"Online: {status['online_nodes']}")

    await asyncio.Event().wait()

asyncio.run(main())
```

Replace `192.168.1.50` with Agent 1's actual IP address.

---

## Sending Messages

Once two agents are federated, they can exchange messages:

```python
# Get the peer's node ID from the registry
for node in fed.registry.online_nodes:
    print(f"Peer: {node.name} (ID: {node.node_id})")

# Send a task
response = await fed.send_message(
    target_node_id=peer_node_id,
    content="Analyze the server logs for anomalies",
    message_type="task",
    payload={"log_path": "/var/log/syslog"},
    timeout=30.0,
)

if response:
    print(f"Response: {response.content}")
    print(f"Payload: {response.payload}")
```

---

## Broadcasting

Send a message to **all** online peers:

```python
responses = await fed.broadcast(
    content="Status check: report your load",
)

for r in responses:
    print(f"  {r.from_node}: {r.content}")
```

Filter by capability:

```python
responses = await fed.broadcast(
    content="Analyze this dataset",
    capability_filter="analysis",
)
```

---

## Trust Scoring

NeuralClaw uses **automatic trust scoring** to rate federation peers.
Trust determines whether an agent will accept messages from a peer.

### How Trust Works

| Event | Trust Change |
|-------|-------------|
| Successful message exchange | +0.02 |
| Failed message exchange | -0.05 |
| New node joins | Starts at 0.5 |
| Trust drops below 0.1 | Node marked `UNTRUSTED` |

### Minimum Trust

Messages from peers with trust below **0.3** are automatically rejected.

```python
# Check a node's trust
node = fed.registry.get_node(node_id)
print(f"Trust: {node.trust_score}")
print(f"Reliability: {node.reliability}")
print(f"Successful: {node.successful_exchanges}")
print(f"Failed: {node.failed_exchanges}")
```

### Blacklisting

Permanently ban a malicious node:

```python
fed.registry.blacklist(node_id)
```

---

## Heartbeats

Agents send periodic heartbeats to detect offline peers:

```python
# Send heartbeats to all known peers
await fed.send_heartbeats()
```

- **Heartbeat interval:** 60 seconds
- **Stale threshold:** 180 seconds (3 missed heartbeats → marked OFFLINE)
- **Alive check:** Node is alive if last heartbeat was within 120 seconds

---

## Node States

| State | Meaning |
|-------|---------|
| `ONLINE` | Healthy, accepting messages |
| `DEGRADED` | Responding slowly or with errors |
| `OFFLINE` | No heartbeat for 180+ seconds |
| `UNTRUSTED` | Trust score dropped below 0.1 |

---

## Federation Registry

The registry tracks all known nodes:

```python
registry = fed.registry

# All nodes
print(f"Total: {registry.node_count}")

# Online nodes only
for node in registry.online_nodes:
    print(f"  {node.name} @ {node.endpoint}")
    print(f"    Trust: {node.trust_score:.2f}")
    print(f"    Capabilities: {node.capabilities}")
    print(f"    Alive: {node.is_alive}")

# Find by capability
analysts = registry.find_by_capability("analysis")

# Find by region
local_nodes = registry.find_by_region("us-east")

# Full status
status = registry.get_status()
```

---

## Message Log

View the federation message history:

```python
messages = fed.get_message_log(limit=50)
for m in messages:
    print(f"  [{m['type']}] {m['from']} → {m['to']}: {m['content']}")
```

---

## TTL (Time-To-Live)

Federation messages have a TTL (default: 3) that decrements with each hop.
This prevents infinite message loops in complex topologies:

```
Agent A → Agent B → Agent C
  TTL=3    TTL=2     TTL=1
```

If TTL reaches 0, the message is dropped.

---

## Gateway Integration

Federation is automatically started by the gateway when `features.swarm = true`
and `federation.enabled = true`. Configure it in `~/.neuralclaw/config.toml`:

```toml
[federation]
enabled = true
port = 8100
bind_host = "127.0.0.1"
seed_nodes = ["http://192.168.1.50:8100"]
heartbeat_interval = 60
node_name = ""  # Defaults to general.name
```

When the gateway starts:
1. The federation HTTP server starts on the configured port
2. All seed nodes are joined automatically
3. A heartbeat loop runs every `heartbeat_interval` seconds
4. The **FederationBridge** periodically syncs online federation peers into the
   local agent mesh as `fed:<name>` remote agents, making them available for
   delegation and mesh messaging

### Accessing the Spawner

```python
gw = NeuralClawGateway()
await gw.start()

# Spawner is available for programmatic agent management
spawner = gw.spawner
spawner.spawn_local("my-agent", "Custom agent", ["custom"], handler)
```

---

## Federation Bridge

The `FederationBridge` automatically syncs federation nodes into the local
mesh via the `AgentSpawner`:

```python
from neuralclaw.swarm.federation import FederationBridge
from neuralclaw.swarm.spawn import AgentSpawner

bridge = FederationBridge(federation=fed, spawner=spawner)
await bridge.start(sync_interval=30.0)

# Federation peers appear in the mesh as "fed:<peer-name>"
# They are usable via mesh.send() and delegation.delegate()
mesh_agents = mesh.discover(capability="analysis")

bridge.sync()      # One-shot manual sync
await bridge.stop()
```

---

## CLI

```bash
neuralclaw federation            # Show live federation status (nodes, trust scores)
neuralclaw federation --port 9000  # Query federation on a custom port
```

When the gateway is running, the CLI queries the live `/federation/status`
endpoint and displays a table of connected nodes with name, status, trust
score, capabilities, and endpoint. If the server is not running, it falls
back to showing protocol info.

---

## Practical Example: Pi Cluster

If you have multiple Raspberry Pis, you can create a NeuralClaw
agent cluster:

```bash
# Pi 1 (192.168.1.50) — coordinator
python -c "
import asyncio
from neuralclaw.swarm.federation import FederationProtocol

async def main():
    fed = FederationProtocol('coordinator', port=8100)
    await fed.start()
    print('Coordinator running on :8100')
    await asyncio.Event().wait()

asyncio.run(main())
"

# Pi 2 (192.168.1.51) — researcher
python -c "
import asyncio
from neuralclaw.swarm.federation import FederationProtocol

async def main():
    fed = FederationProtocol('researcher', port=8100)
    await fed.start()
    await fed.join_federation('http://192.168.1.50:8100')
    print('Researcher joined federation')
    await asyncio.Event().wait()

asyncio.run(main())
"

# Pi 3 (192.168.1.52) — analyst
# Same pattern, join federation at coordinator's address
```

Each Pi contributes its own capabilities. The coordinator can delegate
tasks to any peer in the federation.

---

## Requirements

Federation requires `aiohttp` (included in core dependencies):

```
aiohttp>=3.9
```
