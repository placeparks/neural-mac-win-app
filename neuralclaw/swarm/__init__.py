"""
NeuralClaw Swarm — Multi-agent collaboration module.

Provides delegation chains, consensus protocols, agent mesh,
federation protocol, and dynamic agent spawning for inter-agent
communication and task distribution.
"""

from neuralclaw.swarm.delegation import (
    DelegationChain,
    DelegationContext,
    DelegationResult,
    DelegationStatus,
    DelegationPolicy,
    DelegationRecord,
)
from neuralclaw.swarm.consensus import (
    ConsensusProtocol,
    ConsensusStrategy,
    ConsensusResult,
    ConsensusVote,
)
from neuralclaw.swarm.mesh import (
    AgentMesh,
    AgentCard,
    AgentStatus,
    MeshMessage,
)
from neuralclaw.swarm.federation import (
    FederationProtocol,
    FederationRegistry,
    FederationNode,
    FederationMessage,
    FederationBridge,
    NodeStatus,
)
from neuralclaw.swarm.spawn import (
    AgentSpawner,
    SpawnedAgent,
)

__all__ = [
    "DelegationChain",
    "DelegationContext",
    "DelegationResult",
    "DelegationStatus",
    "DelegationPolicy",
    "DelegationRecord",
    "ConsensusProtocol",
    "ConsensusStrategy",
    "ConsensusResult",
    "ConsensusVote",
    "AgentMesh",
    "AgentCard",
    "AgentStatus",
    "MeshMessage",
    "FederationProtocol",
    "FederationRegistry",
    "FederationNode",
    "FederationMessage",
    "FederationBridge",
    "NodeStatus",
    "AgentSpawner",
    "SpawnedAgent",
]
