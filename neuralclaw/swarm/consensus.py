"""
Consensus Protocol — Multi-agent decision-making with configurable strategies.

When high-stakes decisions need validation, multiple agents are consulted
and their responses are synthesized using a chosen strategy.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from neuralclaw.bus.neural_bus import NeuralBus, EventType
from neuralclaw.swarm.delegation import (
    DelegationChain,
    DelegationContext,
    DelegationResult,
    DelegationStatus,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

class ConsensusStrategy(Enum):
    MAJORITY_VOTE = auto()       # Most common answer wins
    WEIGHTED_CONFIDENCE = auto() # Highest total confidence wins
    BEST_CONFIDENCE = auto()     # Single highest confidence response
    UNANIMOUS = auto()           # All must agree
    DELIBERATION = auto()        # Iterative refinement rounds


@dataclass
class ConsensusVote:
    """A single agent's vote in a consensus round."""
    agent_name: str
    response: str
    confidence: float
    reasoning: str = ""
    elapsed_seconds: float = 0.0


@dataclass
class ConsensusResult:
    """The synthesized result of a consensus process."""
    strategy: ConsensusStrategy
    final_response: str
    final_confidence: float
    votes: list[ConsensusVote]
    rounds: int = 1
    consensus_reached: bool = True
    dissenting_agents: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Consensus Protocol
# ---------------------------------------------------------------------------

class ConsensusProtocol:
    """
    For high-stakes decisions, consult N agents and synthesize their responses.

    Strategies:
    - MAJORITY_VOTE: group responses by similarity, pick the majority cluster
    - WEIGHTED_CONFIDENCE: sum confidence per group, highest total wins
    - BEST_CONFIDENCE: simply pick the single highest-confidence response
    - UNANIMOUS: all agents must agree (or escalate)
    - DELIBERATION: multi-round refinement (agents see each other's responses)
    """

    DEFAULT_AGENTS = 3
    MAX_DELIBERATION_ROUNDS = 3

    def __init__(
        self,
        delegation: DelegationChain,
        bus: NeuralBus | None = None,
    ) -> None:
        self._delegation = delegation
        self._bus = bus

    async def seek_consensus(
        self,
        task: str,
        strategy: ConsensusStrategy = ConsensusStrategy.WEIGHTED_CONFIDENCE,
        agent_names: list[str] | None = None,
        min_agents: int = 2,
        timeout: float = 60.0,
    ) -> ConsensusResult:
        """
        Seek consensus from multiple agents on a task.

        Args:
            task: The question or task to decide on.
            strategy: Which consensus strategy to use.
            agent_names: Specific agents to consult. If None, uses all available.
            min_agents: Minimum agents required for consensus.
            timeout: Max time for the entire consensus process.
        """
        start = time.time()
        available = agent_names or self._delegation.get_available_agents()

        if len(available) < min_agents:
            return ConsensusResult(
                strategy=strategy,
                final_response=f"Insufficient agents: need {min_agents}, have {len(available)}",
                final_confidence=0.0,
                votes=[],
                consensus_reached=False,
            )

        # Collect votes from all agents in parallel
        votes = await self._collect_votes(available, task, timeout)

        if not votes:
            return ConsensusResult(
                strategy=strategy,
                final_response="No agents responded",
                final_confidence=0.0,
                votes=[],
                consensus_reached=False,
            )

        # Apply strategy
        if strategy == ConsensusStrategy.DELIBERATION:
            result = await self._deliberate(votes, task, timeout - (time.time() - start))
        else:
            result = self._apply_strategy(strategy, votes)

        result.elapsed_seconds = time.time() - start

        # Emit event
        if self._bus:
            self._bus.emit(EventType.REASONING_COMPLETE, {
                "consensus": True,
                "strategy": strategy.name,
                "agents": len(votes),
                "consensus_reached": result.consensus_reached,
                "confidence": result.final_confidence,
            })

        return result

    async def _collect_votes(
        self,
        agents: list[str],
        task: str,
        timeout: float,
    ) -> list[ConsensusVote]:
        """Collect votes from all agents in parallel."""
        contexts = [
            (name, DelegationContext(
                task_description=task,
                timeout_seconds=timeout,
                constraints={"role": "consensus_voter"},
            ))
            for name in agents
        ]

        results = await self._delegation.delegate_parallel(contexts)
        votes = []
        for (name, _), result in zip(contexts, results):
            if result.status == DelegationStatus.COMPLETED:
                votes.append(ConsensusVote(
                    agent_name=name,
                    response=result.result,
                    confidence=result.confidence,
                    elapsed_seconds=result.elapsed_seconds,
                ))
        return votes

    def _apply_strategy(
        self,
        strategy: ConsensusStrategy,
        votes: list[ConsensusVote],
    ) -> ConsensusResult:
        """Apply a non-deliberative consensus strategy."""
        if strategy == ConsensusStrategy.BEST_CONFIDENCE:
            return self._best_confidence(votes)
        elif strategy == ConsensusStrategy.MAJORITY_VOTE:
            return self._majority_vote(votes)
        elif strategy == ConsensusStrategy.WEIGHTED_CONFIDENCE:
            return self._weighted_confidence(votes)
        elif strategy == ConsensusStrategy.UNANIMOUS:
            return self._unanimous(votes)
        else:
            return self._weighted_confidence(votes)

    def _best_confidence(self, votes: list[ConsensusVote]) -> ConsensusResult:
        """Pick the single highest-confidence response."""
        best = max(votes, key=lambda v: v.confidence)
        dissenters = [v.agent_name for v in votes if v.agent_name != best.agent_name]
        return ConsensusResult(
            strategy=ConsensusStrategy.BEST_CONFIDENCE,
            final_response=best.response,
            final_confidence=best.confidence,
            votes=votes,
            dissenting_agents=dissenters,
        )

    def _majority_vote(self, votes: list[ConsensusVote]) -> ConsensusResult:
        """Group similar responses and pick the majority cluster."""
        # Simple approach: group by normalized response prefix (first 100 chars)
        groups: dict[str, list[ConsensusVote]] = {}
        for v in votes:
            key = v.response[:100].strip().lower()
            groups.setdefault(key, []).append(v)

        # Pick largest group
        largest = max(groups.values(), key=len)
        winner = max(largest, key=lambda v: v.confidence)
        dissenters = [v.agent_name for v in votes if v not in largest]

        return ConsensusResult(
            strategy=ConsensusStrategy.MAJORITY_VOTE,
            final_response=winner.response,
            final_confidence=sum(v.confidence for v in largest) / len(largest),
            votes=votes,
            consensus_reached=len(largest) > len(votes) / 2,
            dissenting_agents=dissenters,
        )

    def _weighted_confidence(self, votes: list[ConsensusVote]) -> ConsensusResult:
        """Weight responses by confidence, pick highest total."""
        groups: dict[str, list[ConsensusVote]] = {}
        for v in votes:
            key = v.response[:100].strip().lower()
            groups.setdefault(key, []).append(v)

        # Pick group with highest total confidence
        best_key = max(groups, key=lambda k: sum(v.confidence for v in groups[k]))
        best_group = groups[best_key]
        winner = max(best_group, key=lambda v: v.confidence)
        dissenters = [v.agent_name for v in votes if v not in best_group]

        total_conf = sum(v.confidence for v in best_group)
        avg_conf = total_conf / len(best_group)

        return ConsensusResult(
            strategy=ConsensusStrategy.WEIGHTED_CONFIDENCE,
            final_response=winner.response,
            final_confidence=avg_conf,
            votes=votes,
            consensus_reached=avg_conf >= 0.6,
            dissenting_agents=dissenters,
        )

    def _unanimous(self, votes: list[ConsensusVote]) -> ConsensusResult:
        """All agents must agree."""
        groups: dict[str, list[ConsensusVote]] = {}
        for v in votes:
            key = v.response[:100].strip().lower()
            groups.setdefault(key, []).append(v)

        unanimous = len(groups) == 1
        best = max(votes, key=lambda v: v.confidence)

        return ConsensusResult(
            strategy=ConsensusStrategy.UNANIMOUS,
            final_response=best.response,
            final_confidence=best.confidence if unanimous else 0.0,
            votes=votes,
            consensus_reached=unanimous,
            dissenting_agents=[] if unanimous else [
                v.agent_name for v in votes if v.response[:100].strip().lower() != best.response[:100].strip().lower()
            ],
        )

    async def _deliberate(
        self,
        initial_votes: list[ConsensusVote],
        task: str,
        remaining_timeout: float,
    ) -> ConsensusResult:
        """
        Multi-round deliberation: agents see each other's responses
        and can revise their answers.
        """
        current_votes = initial_votes
        rounds = 1

        for _ in range(self.MAX_DELIBERATION_ROUNDS - 1):
            if remaining_timeout <= 0:
                break

            # Check if we already have consensus
            check = self._weighted_confidence(current_votes)
            if check.consensus_reached and check.final_confidence >= 0.8:
                check.rounds = rounds
                return check

            # Build deliberation prompt with all previous votes visible
            prior_summary = "\n".join(
                f"- {v.agent_name} (confidence {v.confidence:.1%}): {v.response[:200]}"
                for v in current_votes
            )
            deliberation_task = (
                f"Original task: {task}\n\n"
                f"Other agents' responses:\n{prior_summary}\n\n"
                f"Please reconsider and provide your refined answer."
            )

            agent_names = [v.agent_name for v in current_votes]
            new_votes = await self._collect_votes(
                agent_names, deliberation_task, remaining_timeout,
            )

            if new_votes:
                current_votes = new_votes
            rounds += 1

        result = self._weighted_confidence(current_votes)
        result.rounds = rounds
        result.strategy = ConsensusStrategy.DELIBERATION
        return result
