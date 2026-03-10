"""
Delegation Engine — Task handoff chains with context preservation.

Enables a NeuralClaw agent to delegate sub-tasks to specialist sub-agents,
package relevant context, collect results, and maintain full provenance.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Awaitable

from neuralclaw.bus.neural_bus import NeuralBus, EventType


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class DelegationStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    TIMED_OUT = auto()
    CANCELLED = auto()


@dataclass
class DelegationContext:
    """Context bundle sent from parent to child agent."""
    task_description: str
    parent_memories: list[dict[str, Any]] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    expected_output_format: str = "text"
    max_steps: int = 10
    timeout_seconds: float = 120.0


@dataclass
class DelegationResult:
    """Result returned by a child agent."""
    delegation_id: str
    status: DelegationStatus
    result: str = ""
    confidence: float = 0.0
    steps_taken: int = 0
    elapsed_seconds: float = 0.0
    provenance: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


@dataclass
class DelegationRecord:
    """Full record of a delegation in the chain."""
    id: str
    parent_id: str | None
    agent_name: str
    context: DelegationContext
    status: DelegationStatus = DelegationStatus.PENDING
    result: DelegationResult | None = None
    children: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None


# ---------------------------------------------------------------------------
# Delegation policies
# ---------------------------------------------------------------------------

@dataclass
class DelegationPolicy:
    """Controls delegation behavior."""
    max_depth: int = 3              # Max nesting depth
    max_concurrent: int = 5         # Max parallel delegations
    timeout_seconds: float = 120.0  # Default timeout per delegation
    retry_on_failure: bool = True   # Retry failed delegations
    max_retries: int = 2            # Max retry attempts
    fallback_to_parent: bool = True # If child fails, parent handles it


# ---------------------------------------------------------------------------
# Delegation Chain
# ---------------------------------------------------------------------------

# Type for agent executor functions
AgentExecutor = Callable[[DelegationContext], Awaitable[DelegationResult]]


class DelegationChain:
    """
    Orchestrates task delegation across agent hierarchies.

    A parent agent can break a complex task into sub-tasks, delegate each
    to a specialist, collect results, and synthesize a final answer.
    """

    def __init__(
        self,
        bus: NeuralBus | None = None,
        policy: DelegationPolicy | None = None,
    ) -> None:
        self._bus = bus
        self._policy = policy or DelegationPolicy()
        self._records: dict[str, DelegationRecord] = {}
        self._executors: dict[str, AgentExecutor] = {}
        self._active_count = 0

    @property
    def policy(self) -> DelegationPolicy:
        return self._policy

    @property
    def active_delegations(self) -> int:
        return self._active_count

    @property
    def history(self) -> list[DelegationRecord]:
        return list(self._records.values())

    def register_executor(self, agent_name: str, executor: AgentExecutor) -> None:
        """Register a specialist agent that can handle delegated tasks."""
        self._executors[agent_name] = executor

    def unregister_executor(self, agent_name: str) -> None:
        """Remove a specialist agent executor."""
        self._executors.pop(agent_name, None)

    def get_available_agents(self) -> list[str]:
        """List all registered specialist agents."""
        return list(self._executors.keys())

    async def delegate(
        self,
        agent_name: str,
        context: DelegationContext,
        parent_id: str | None = None,
    ) -> DelegationResult:
        """
        Delegate a task to a specialist agent.

        Args:
            agent_name: Name of the specialist to delegate to.
            context: Context bundle with task, memories, constraints.
            parent_id: ID of the parent delegation (for nesting).

        Returns:
            DelegationResult with the specialist's response.
        """
        # Check depth limit
        depth = self._calculate_depth(parent_id)
        if depth >= self._policy.max_depth:
            return DelegationResult(
                delegation_id="",
                status=DelegationStatus.FAILED,
                error=f"Max delegation depth ({self._policy.max_depth}) exceeded",
            )

        # Check concurrency limit
        if self._active_count >= self._policy.max_concurrent:
            return DelegationResult(
                delegation_id="",
                status=DelegationStatus.FAILED,
                error=f"Max concurrent delegations ({self._policy.max_concurrent}) reached",
            )

        # Check if agent exists
        if agent_name not in self._executors:
            return DelegationResult(
                delegation_id="",
                status=DelegationStatus.FAILED,
                error=f"Unknown agent: {agent_name}. Available: {list(self._executors.keys())}",
            )

        # Create delegation record
        delegation_id = uuid.uuid4().hex[:12]
        record = DelegationRecord(
            id=delegation_id,
            parent_id=parent_id,
            agent_name=agent_name,
            context=context,
        )
        self._records[delegation_id] = record

        # Link to parent
        if parent_id and parent_id in self._records:
            self._records[parent_id].children.append(delegation_id)

        # Execute with retry
        result = await self._execute_with_retry(record)

        # Update record
        record.status = result.status
        record.result = result
        record.completed_at = time.time()
        result.delegation_id = delegation_id

        # Emit event
        if self._bus:
            self._bus.emit(EventType.ACTION_COMPLETE, {
                "delegation_id": delegation_id,
                "agent": agent_name,
                "status": result.status.name,
                "confidence": result.confidence,
            })

        return result

    async def delegate_parallel(
        self,
        tasks: list[tuple[str, DelegationContext]],
        parent_id: str | None = None,
    ) -> list[DelegationResult]:
        """
        Delegate multiple tasks in parallel and collect all results.

        Args:
            tasks: List of (agent_name, context) tuples.
            parent_id: Optional parent delegation ID.

        Returns:
            List of results in the same order as the input tasks.
        """
        coros = [
            self.delegate(agent_name, ctx, parent_id)
            for agent_name, ctx in tasks
        ]
        return await asyncio.gather(*coros)

    async def _execute_with_retry(self, record: DelegationRecord) -> DelegationResult:
        """Execute a delegation with retry logic."""
        attempts = 0
        max_attempts = 1 + (self._policy.max_retries if self._policy.retry_on_failure else 0)
        last_error = ""

        while attempts < max_attempts:
            attempts += 1
            self._active_count += 1
            record.status = DelegationStatus.RUNNING
            start = time.time()

            try:
                executor = self._executors[record.agent_name]
                timeout = record.context.timeout_seconds or self._policy.timeout_seconds

                result = await asyncio.wait_for(
                    executor(record.context),
                    timeout=timeout,
                )
                result.elapsed_seconds = time.time() - start
                result.provenance.append({
                    "agent": record.agent_name,
                    "attempt": attempts,
                    "timestamp": time.time(),
                })

                if result.status == DelegationStatus.COMPLETED:
                    return result
                last_error = result.error or "Unknown error"

            except asyncio.TimeoutError:
                last_error = f"Timed out after {record.context.timeout_seconds}s"
                return DelegationResult(
                    delegation_id=record.id,
                    status=DelegationStatus.TIMED_OUT,
                    error=last_error,
                    elapsed_seconds=time.time() - start,
                )
            except Exception as e:
                last_error = str(e)
            finally:
                self._active_count -= 1

        # All retries exhausted
        if self._policy.fallback_to_parent:
            return DelegationResult(
                delegation_id=record.id,
                status=DelegationStatus.FAILED,
                error=f"All {max_attempts} attempts failed. Last error: {last_error}",
            )
        return DelegationResult(
            delegation_id=record.id,
            status=DelegationStatus.FAILED,
            error=last_error,
        )

    def _calculate_depth(self, parent_id: str | None) -> int:
        """Calculate the nesting depth of a delegation."""
        depth = 0
        current = parent_id
        while current and current in self._records:
            depth += 1
            current = self._records[current].parent_id
        return depth

    def get_chain_summary(self, delegation_id: str) -> dict[str, Any]:
        """Get a summary of a delegation chain starting from the given ID."""
        record = self._records.get(delegation_id)
        if not record:
            return {}

        summary: dict[str, Any] = {
            "id": record.id,
            "agent": record.agent_name,
            "task": record.context.task_description[:100],
            "status": record.status.name,
            "children": [],
        }

        if record.result:
            summary["confidence"] = record.result.confidence
            summary["elapsed"] = record.result.elapsed_seconds

        for child_id in record.children:
            summary["children"].append(self.get_chain_summary(child_id))

        return summary
