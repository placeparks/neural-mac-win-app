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
from neuralclaw.errors import ErrorCode


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
    timeout_seconds: float = 300.0
    tools: list[Any] = field(default_factory=list)
    allowed_skills: list[str] = field(default_factory=list)


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
    error_code: ErrorCode | None = None


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
    timeout_seconds: float = 300.0  # Default timeout per delegation
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

    MAX_RECORD_HISTORY = 500  # Prune completed records beyond this limit

    def __init__(
        self,
        bus: NeuralBus | None = None,
        policy: DelegationPolicy | None = None,
    ) -> None:
        self._bus = bus
        self._policy = policy or DelegationPolicy()
        self._records: dict[str, DelegationRecord] = {}
        self._executors: dict[str, AgentExecutor] = {}
        self._concurrency_sem = asyncio.Semaphore(self._policy.max_concurrent)

    @property
    def policy(self) -> DelegationPolicy:
        return self._policy

    @property
    def active_delegations(self) -> int:
        return self._policy.max_concurrent - self._concurrency_sem._value  # noqa: SLF001

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
                error_code=ErrorCode.DELEGATION_DEPTH_EXCEEDED,
            )

        # Check concurrency limit (non-blocking check)
        if not self._concurrency_sem._value:  # noqa: SLF001
            return DelegationResult(
                delegation_id="",
                status=DelegationStatus.FAILED,
                error=f"Max concurrent delegations ({self._policy.max_concurrent}) reached",
                error_code=ErrorCode.DELEGATION_CONCURRENCY_EXCEEDED,
            )

        # Check if agent exists
        if agent_name not in self._executors:
            return DelegationResult(
                delegation_id="",
                status=DelegationStatus.FAILED,
                error=f"Unknown agent: {agent_name}. Available: {list(self._executors.keys())}",
                error_code=ErrorCode.DELEGATION_AGENT_NOT_FOUND,
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

        # Publish event (await to guarantee delivery)
        if self._bus:
            await self._bus.publish(EventType.ACTION_COMPLETE, {
                "delegation_id": delegation_id,
                "agent": agent_name,
                "status": result.status.name,
                "confidence": result.confidence,
            }, source="delegation.chain")

        # Prune old completed records to prevent unbounded growth
        self._prune_records()

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

    async def delegate_pipeline(
        self,
        agents: list[str],
        initial_task: str,
        base_context: DelegationContext,
        parent_id: str | None = None,
        shared_bridge: Any = None,
        shared_task_id: str = "",
    ) -> list[DelegationResult]:
        """
        Run agents sequentially — each agent's output becomes the next
        agent's input. This is the handoff / pipeline pattern.

        Agent 1 receives: initial_task
        Agent 2 receives: initial_task + Agent 1's full result
        Agent 3 receives: initial_task + Agent 1's result + Agent 2's result
        ...

        Args:
            agents:         Ordered list of agent names.
            initial_task:   The original task description.
            base_context:   Base context (timeout, constraints, etc.).
            parent_id:      Optional parent delegation ID.
            shared_bridge:  Optional SharedMemoryBridge to write handoff memories.
            shared_task_id: Shared task ID to attach handoff memories to.

        Returns:
            List of DelegationResult in agent order.
        """
        results: list[DelegationResult] = []
        accumulated_context = ""

        for i, agent_name in enumerate(agents):
            if accumulated_context:
                # Build handoff prompt: original task + prior agents' outputs
                handoff_sections = []
                for j, prev_result in enumerate(results):
                    prev_agent = agents[j]
                    handoff_sections.append(
                        f"--- {prev_agent.upper()} OUTPUT ---\n{prev_result.result}\n"
                    )
                task_with_handoff = (
                    f"{initial_task}\n\n"
                    f"=== PRIOR AGENT OUTPUTS (use these as your input) ===\n"
                    + "\n".join(handoff_sections)
                    + f"\n=== YOUR ROLE: {agent_name} ===\n"
                    f"Based on the above, continue the pipeline for your part."
                )
            else:
                task_with_handoff = initial_task

            ctx = DelegationContext(
                task_description=task_with_handoff,
                parent_memories=base_context.parent_memories,
                constraints={
                    **base_context.constraints,
                    "pipeline_step": i,
                    "pipeline_total": len(agents),
                    "shared_task_id": shared_task_id,
                },
                timeout_seconds=base_context.timeout_seconds,
                allowed_skills=base_context.allowed_skills,
            )

            result = await self.delegate(agent_name, ctx, parent_id)
            results.append(result)

            # Write this agent's output to shared memory so all agents
            # can see the chain (and future agents in this pipeline too)
            if shared_bridge and shared_task_id and result.result:
                try:
                    await shared_bridge.add_memory(
                        task_id=shared_task_id,
                        from_agent=agent_name,
                        content=result.result,
                        memory_type="pipeline_handoff",
                    )
                except Exception as exc:
                    import logging
                    logging.getLogger("neuralclaw.swarm.delegation").warning(
                        "Pipeline shared-memory write failed for %s (task %s): %s",
                        agent_name, shared_task_id, exc,
                    )

            # Stop the pipeline early if an agent failed
            if result.status not in (DelegationStatus.COMPLETED,):
                break

            accumulated_context = result.result

        return results

    async def _execute_with_retry(self, record: DelegationRecord) -> DelegationResult:
        """Execute a delegation with retry logic."""
        attempts = 0
        max_attempts = 1 + (self._policy.max_retries if self._policy.retry_on_failure else 0)
        last_error = ""

        while attempts < max_attempts:
            attempts += 1
            async with self._concurrency_sem:
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
                        error_code=ErrorCode.DELEGATION_TIMEOUT,
                    )
                except Exception as e:
                    last_error = str(e)

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

    def _prune_records(self) -> None:
        """Remove oldest completed records when history exceeds cap."""
        if len(self._records) <= self.MAX_RECORD_HISTORY:
            return
        completed = sorted(
            (r for r in self._records.values()
             if r.status in (DelegationStatus.COMPLETED, DelegationStatus.FAILED, DelegationStatus.TIMED_OUT)),
            key=lambda r: r.completed_at or r.created_at,
        )
        prune_count = len(self._records) - self.MAX_RECORD_HISTORY
        for record in completed[:prune_count]:
            self._records.pop(record.id, None)
