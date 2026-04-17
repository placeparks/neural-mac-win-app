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
        start = time.monotonic()
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

        # Quorum check: enough agents must actually respond
        if len(votes) < min_agents:
            return ConsensusResult(
                strategy=strategy,
                final_response=f"Quorum not met: {len(votes)} responded out of {len(available)} consulted, need {min_agents}",
                final_confidence=0.0,
                votes=votes,
                consensus_reached=False,
            )

        # Apply strategy
        if strategy == ConsensusStrategy.DELIBERATION:
            result = await self._deliberate(votes, task, timeout - (time.monotonic() - start))
        else:
            result = self._apply_strategy(strategy, votes)

        result.elapsed_seconds = time.monotonic() - start

        # Publish event (await to guarantee delivery)
        if self._bus:
            await self._bus.publish(EventType.REASONING_COMPLETE, {
                "consensus": True,
                "strategy": strategy.name,
                "agents": len(votes),
                "consensus_reached": result.consensus_reached,
                "confidence": result.final_confidence,
            }, source="consensus.protocol")

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

    # -- Response similarity helpers -----------------------------------------

    @staticmethod
    def _normalize_response(text: str) -> str:
        """Normalize a response for grouping: lowercase, collapse whitespace, strip filler."""
        import re
        text = text.lower().strip()
        # Strip common conversational filler that doesn't affect meaning
        for filler in ("based on my analysis, ", "based on the information, ",
                       "here is my response: ", "i believe that ", "in my opinion, "):
            if text.startswith(filler):
                text = text[len(filler):]
        text = re.sub(r'\s+', ' ', text)
        return text

    @staticmethod
    def _ngrams(text: str, n: int = 4) -> set[str]:
        """Extract character n-grams from text."""
        return {text[i:i + n] for i in range(max(0, len(text) - n + 1))}

    @classmethod
    def _response_similarity(cls, a: str, b: str) -> float:
        """Jaccard similarity on character 4-grams after normalization."""
        na, nb = cls._normalize_response(a), cls._normalize_response(b)
        if na == nb:
            return 1.0
        ga, gb = cls._ngrams(na), cls._ngrams(nb)
        if not ga and not gb:
            return 1.0
        if not ga or not gb:
            return 0.0
        return len(ga & gb) / len(ga | gb)

    @classmethod
    def _group_votes(cls, votes: list[ConsensusVote], threshold: float = 0.45) -> list[list[ConsensusVote]]:
        """
        Group votes by semantic similarity using 4-gram Jaccard.

        Assigns each vote to the first existing group whose centroid
        (highest-confidence member) exceeds the similarity threshold.
        """
        groups: list[list[ConsensusVote]] = []
        for v in votes:
            placed = False
            for group in groups:
                centroid = max(group, key=lambda g: g.confidence)
                if cls._response_similarity(v.response, centroid.response) >= threshold:
                    group.append(v)
                    placed = True
                    break
            if not placed:
                groups.append([v])
        return groups

    # -- Voting strategies ---------------------------------------------------

    def _majority_vote(self, votes: list[ConsensusVote]) -> ConsensusResult:
        """Group similar responses and pick the majority cluster."""
        groups = self._group_votes(votes)

        largest = max(groups, key=len)
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
        groups = self._group_votes(votes)

        best_group = max(groups, key=lambda g: sum(v.confidence for v in g))
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
        groups = self._group_votes(votes)

        unanimous = len(groups) == 1
        best = max(votes, key=lambda v: v.confidence)

        return ConsensusResult(
            strategy=ConsensusStrategy.UNANIMOUS,
            final_response=best.response,
            final_confidence=best.confidence if unanimous else 0.0,
            votes=votes,
            consensus_reached=unanimous,
            dissenting_agents=[] if unanimous else [
                v.agent_name for v in votes if v not in groups[0]
            ] if groups else [],
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
