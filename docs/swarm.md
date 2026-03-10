# 🐝 Swarm Intelligence (Multi-Agent)

NeuralClaw's Swarm module enables **multi-agent collaboration**.
A parent agent can delegate tasks to specialists, consult multiple agents
for consensus decisions, and discover agents on a mesh network.

---

## Components

| Component | File | Purpose |
|-----------|------|---------|
| **Delegation Chain** | `swarm/delegation.py` | Task handoff with context preservation |
| **Consensus Protocol** | `swarm/consensus.py` | Multi-agent voting on decisions |
| **Agent Mesh** | `swarm/mesh.py` | Agent discovery and communication |
| **Agent Spawner** | `swarm/spawn.py` | Dynamic agent lifecycle management |
| **Federation Bridge** | `swarm/federation.py` | Sync federation peers into mesh |

---

## Delegation Chains

Delegate sub-tasks to specialist agents with full context and provenance.

### Basic Delegation

```python
import asyncio
from neuralclaw.swarm.delegation import (
    DelegationChain,
    DelegationContext,
    DelegationResult,
    DelegationStatus,
)

chain = DelegationChain()

# Register a specialist agent
async def researcher_handler(ctx: DelegationContext) -> DelegationResult:
    # Specialist does its work here
    return DelegationResult(
        delegation_id="",  # Set automatically
        status=DelegationStatus.COMPLETED,
        result=f"Research complete: found 3 results for '{ctx.task_description}'",
        confidence=0.85,
        steps_taken=3,
    )

chain.register_executor("researcher", researcher_handler)

# Delegate a task
ctx = DelegationContext(
    task_description="Research competitor pricing",
    max_steps=10,
    timeout_seconds=60.0,
)

result = await chain.delegate("researcher", ctx)
print(f"Result: {result.result}")
print(f"Confidence: {result.confidence}")
print(f"Status: {result.status.name}")
```

### Parallel Delegation

Delegate multiple tasks to specialists in parallel:

```python
tasks = [
    ("researcher", DelegationContext(task_description="Research topic A")),
    ("researcher", DelegationContext(task_description="Research topic B")),
    ("analyst", DelegationContext(task_description="Analyze dataset")),
]

results = await chain.delegate_parallel(tasks)

for r in results:
    print(f"{r.result} (confidence: {r.confidence})")
```

### Nested Delegation

Agents can delegate to other agents, creating a chain:

```python
async def coordinator_handler(ctx: DelegationContext) -> DelegationResult:
    # The coordinator itself delegates sub-tasks
    sub_result = await chain.delegate(
        "researcher",
        DelegationContext(task_description="Sub-task of: " + ctx.task_description),
        parent_id=ctx.task_description,  # Track provenance
    )
    return DelegationResult(
        delegation_id="",
        status=DelegationStatus.COMPLETED,
        result=f"Coordinated: {sub_result.result}",
        confidence=sub_result.confidence,
    )
```

### Delegation Policy

Control delegation behavior:

```python
from neuralclaw.swarm.delegation import DelegationPolicy

policy = DelegationPolicy(
    max_depth=3,            # Max nesting depth
    max_concurrent=5,       # Max parallel delegations
    timeout_seconds=120.0,  # Timeout per delegation
    retry_on_failure=True,  # Auto-retry on failure
    max_retries=2,          # Retry limit
    fallback_to_parent=True,  # Return to parent on failure
)

chain = DelegationChain(policy=policy)
```

### View Chain Summary

```python
summary = chain.get_chain_summary(delegation_id)
print(summary)
```

---

## Consensus Protocol

When high-stakes decisions need validation, consult multiple agents
and synthesize their responses.

### Five Strategies

| Strategy | Behavior |
|----------|----------|
| `MAJORITY_VOTE` | Group similar responses, pick the majority cluster |
| `WEIGHTED_CONFIDENCE` | Weight responses by confidence, pick highest total |
| `BEST_CONFIDENCE` | Pick the single highest-confidence response |
| `UNANIMOUS` | All agents must agree |
| `DELIBERATION` | Multi-round: agents see each other's answers and revise |

### Basic Usage

```python
from neuralclaw.swarm.consensus import ConsensusProtocol, ConsensusStrategy

# Build on a delegation chain with registered agents
consensus = ConsensusProtocol(chain)

result = await consensus.seek_consensus(
    task="Should we deploy the new release to production?",
    strategy=ConsensusStrategy.MAJORITY_VOTE,
    min_agents=3,       # Minimum agents needed
    timeout=60.0,       # Max time to collect votes
)

print(f"Decision: {result.final_response}")
print(f"Confidence: {result.final_confidence}")
print(f"Consensus reached: {result.consensus_reached}")
print(f"Dissenting agents: {result.dissenting_agents}")

# See each agent's vote
for vote in result.votes:
    print(f"  {vote.agent_name}: {vote.response} ({vote.confidence})")
```

### Deliberation Mode

In deliberation mode, agents see each other's responses and can revise:

```python
result = await consensus.seek_consensus(
    task="What is the best architecture for this system?",
    strategy=ConsensusStrategy.DELIBERATION,
    min_agents=3,
)

print(f"Rounds of deliberation: {result.rounds}")
```

---

## Agent Mesh

A mesh for agent-to-agent communication, inspired by Google's A2A protocol.

### Register Agents

```python
from neuralclaw.swarm.mesh import AgentMesh, MeshMessage

mesh = AgentMesh()

# Define a message handler
async def analyst_handler(msg: MeshMessage) -> MeshMessage | None:
    return msg.reply(
        content=f"Analysis complete for: {msg.content}",
        payload={"confidence": 0.9},
    )

# Register an agent
agent_id = mesh.register(
    name="analyst",
    description="Specializes in data analysis",
    capabilities=["analysis", "statistics", "visualization"],
    handler=analyst_handler,
    max_concurrent=3,
)

print(f"Registered agent: {agent_id}")
```

### Discover Agents

```python
# Find all available agents
all_agents = mesh.discover()

# Find agents with a specific capability
researchers = mesh.discover(capability="research")
analysts = mesh.discover(capability="analysis", available_only=True)

for agent in analysts:
    print(f"  {agent.name}: {agent.capabilities}")
```

### Send Messages

```python
# Send a task to a specific agent
response = await mesh.send(
    from_agent="coordinator",
    to_agent="analyst",
    content="Analyze Q4 sales data",
    message_type="task",
    payload={"dataset": "sales_q4.csv"},
    timeout=30.0,
)

if response:
    print(f"Response: {response.content}")
```

### Broadcast

```python
# Broadcast to all agents (or filtered by capability)
responses = await mesh.broadcast(
    from_agent="coordinator",
    content="Status check: report your availability",
    capability_filter="analysis",  # Only broadcast to analysts
)

for r in responses:
    print(f"  {r.from_agent}: {r.content}")
```

### Remote Agents (HTTP)

Agents can register with an HTTP endpoint for cross-machine communication:

```python
mesh.register(
    name="remote-analyst",
    description="Remote data analyst",
    capabilities=["analysis"],
    handler=analyst_handler,
    endpoint="http://192.168.1.100:8100/mesh",  # Remote machine
)
```

### View Mesh Status

```bash
# CLI
neuralclaw swarm status
```

```python
# Python API
status = mesh.get_mesh_status()
print(f"Total agents: {status['total_agents']}")
print(f"Online: {status['online_agents']}")
print(f"Messages: {status['total_messages']}")
```

---

## Agent Spawner

The `AgentSpawner` provides a unified API to dynamically create and destroy
agents at runtime. Each spawned agent is registered in **both** the mesh
(for communication) and the delegation chain (for task execution).

### Spawn a Local Agent

```python
from neuralclaw.swarm.spawn import AgentSpawner
from neuralclaw.swarm.mesh import AgentMesh, MeshMessage
from neuralclaw.swarm.delegation import DelegationChain

mesh = AgentMesh()
chain = DelegationChain()
spawner = AgentSpawner(mesh, chain)

async def handler(msg: MeshMessage) -> MeshMessage | None:
    return msg.reply(f"Result: {msg.content}", payload={"confidence": 0.9})

agent = spawner.spawn_local(
    name="analyst",
    description="Data analysis specialist",
    capabilities=["analysis", "statistics"],
    handler=handler,
)

# Now usable via both mesh and delegation:
response = await mesh.send(from_agent="coordinator", to_agent="analyst", content="Analyze data")
result = await chain.delegate("analyst", DelegationContext(task_description="Analyze data"))
```

### Spawn a Remote Agent

```python
agent = spawner.spawn_remote(
    name="remote-researcher",
    description="Remote research agent",
    capabilities=["search", "research"],
    endpoint="http://192.168.1.100:8100",
    source="manual",
)
```

### Despawn

```python
spawner.despawn("analyst")  # Removes from mesh + delegation
```

### Custom Executor

By default, spawning wraps the mesh handler into a delegation executor. You
can provide a custom executor for full control:

```python
async def custom_executor(ctx: DelegationContext) -> DelegationResult:
    return DelegationResult(
        delegation_id="",
        status=DelegationStatus.COMPLETED,
        result="Custom logic result",
        confidence=0.95,
    )

spawner.spawn_local("specialist", "Specialist", ["custom"], handler, executor=custom_executor)
```

### Federation Auto-Spawn

When federation is active, the `FederationBridge` automatically spawns
federation peers as remote agents (prefixed `fed:`). See the
[Federation docs](federation.md) for details.

---

## Putting It All Together

Here's a complete multi-agent scenario — a coordinator delegates research
to specialists, then uses consensus to make a decision:

```python
import asyncio
from neuralclaw.swarm.delegation import *
from neuralclaw.swarm.consensus import *
from neuralclaw.swarm.mesh import *

# 1. Create delegation chain
chain = DelegationChain()

# 2. Register specialist agents
async def market_researcher(ctx):
    return DelegationResult(
        delegation_id="", status=DelegationStatus.COMPLETED,
        result="Market is growing 15% YoY", confidence=0.8,
    )

async def tech_analyst(ctx):
    return DelegationResult(
        delegation_id="", status=DelegationStatus.COMPLETED,
        result="Stack is production-ready", confidence=0.9,
    )

async def risk_analyst(ctx):
    return DelegationResult(
        delegation_id="", status=DelegationStatus.COMPLETED,
        result="Low risk — market conditions favorable", confidence=0.7,
    )

chain.register_executor("market_researcher", market_researcher)
chain.register_executor("tech_analyst", tech_analyst)
chain.register_executor("risk_analyst", risk_analyst)

# 3. Delegate research tasks in parallel
results = await chain.delegate_parallel([
    ("market_researcher", DelegationContext(task_description="Analyze market")),
    ("tech_analyst", DelegationContext(task_description="Assess tech stack")),
    ("risk_analyst", DelegationContext(task_description="Evaluate risks")),
])

# 4. Use consensus for the final decision
consensus = ConsensusProtocol(chain)
decision = await consensus.seek_consensus(
    "Based on research, should we proceed with the launch?",
    strategy=ConsensusStrategy.WEIGHTED_CONFIDENCE,
)

print(f"\n🎯 Decision: {decision.final_response}")
print(f"   Confidence: {decision.final_confidence:.0%}")
```

---

## CLI Commands

```bash
neuralclaw swarm status                          # View mesh status (agents, messages)
neuralclaw swarm spawn <name>                    # Spawn a new agent
neuralclaw swarm spawn analyst -c "data,stats"   # With capabilities
neuralclaw swarm spawn remote -e http://peer:8100  # Remote agent
```

> **Note:** Agents are registered when the gateway starts. If you run
> `neuralclaw swarm status` without the gateway running, it will show
> zero agents. At runtime, use `gateway.spawner` for programmatic spawning.
