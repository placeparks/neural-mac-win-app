"""
Reflective Reasoning — Multi-step planning with self-critique.

Layer 3 of the reasoning cortex. When the deliberative path detects
a complex multi-step task, it escalates to the reflective reasoner.

The reflective loop:
1. Decompose the query into sub-tasks
2. Execute each sub-task with the deliberative reasoner
3. Self-critique: evaluate partial results
4. Revise plan if intermediate results reveal issues
5. Synthesize final answer from sub-task results
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.cortex.memory.retrieval import MemoryContext
from neuralclaw.cortex.perception.intake import Signal
from neuralclaw.cortex.reasoning.deliberate import ConfidenceEnvelope, DeliberativeReasoner, ToolDef
from neuralclaw.cortex.reasoning.structured import StructuredOutputError, StructuredReasoner, TaskDecomposition


# ---------------------------------------------------------------------------
# Reflection data models
# ---------------------------------------------------------------------------

@dataclass
class SubTask:
    """A decomposed sub-task."""
    id: int
    description: str
    result: str | None = None
    confidence: float = 0.0
    status: str = "pending"  # pending, in_progress, complete, revised


@dataclass
class ReflectionPlan:
    """A multi-step reflection plan."""
    original_query: str
    sub_tasks: list[SubTask]
    current_step: int = 0
    revisions: int = 0
    max_revisions: int = 2


# ---------------------------------------------------------------------------
# Reflective Reasoner
# ---------------------------------------------------------------------------

class ReflectiveReasoner:
    """
    Multi-step planning with self-critique.

    For complex queries that need decomposition:
    1. Ask LLM to break query into steps
    2. Execute each step via deliberative reasoner
    3. Self-critique: ask LLM to evaluate quality
    4. Revise if needed
    5. Synthesize final answer
    """

    MAX_SUB_TASKS = 5
    COMPLEXITY_THRESHOLD = 50  # Min character length to consider reflective

    def __init__(
        self,
        bus: NeuralBus,
        deliberate: DeliberativeReasoner,
        structured: StructuredReasoner | None = None,
    ) -> None:
        self._bus = bus
        self._deliberate = deliberate
        self._structured = structured

    def should_reflect(self, signal: Signal, memory_ctx: MemoryContext) -> bool:
        """
        Heuristic check: should this query use reflective reasoning?

        Complex queries have multiple clauses, comparison words,
        or explicit multi-step language.
        """
        text = signal.content.lower()

        # Too short for reflection
        if len(text) < self.COMPLEXITY_THRESHOLD:
            return False

        # Multi-step indicators
        multi_step_words = [
            "step by step", "first", "then", "after that", "finally",
            "compare", "analyze", "research", "plan", "investigate",
            "break down", "walk me through", "how do i", "explain in detail",
            "multiple", "several", "all the", "comprehensive",
        ]

        indicator_count = sum(1 for w in multi_step_words if w in text)

        # Multiple sentences suggest complexity
        sentence_count = text.count(".") + text.count("?") + text.count("!")

        return indicator_count >= 2 or (sentence_count >= 3 and len(text) > 100)

    async def reflect(
        self,
        signal: Signal,
        memory_ctx: MemoryContext,
        tools: list[ToolDef] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        extra_system_sections: list[str] | None = None,
    ) -> ConfidenceEnvelope:
        """Run the full reflective reasoning loop."""

        await self._bus.publish(
            EventType.REFLECTION_STARTED,
            {"signal_id": signal.id, "query_length": len(signal.content)},
            source="reasoning.reflective",
        )

        # Step 1: Decompose into sub-tasks
        plan = await self._decompose(signal, memory_ctx, extra_system_sections)

        if not plan.sub_tasks:
            # Fall back to deliberative if decomposition fails
            return await self._deliberate.reason(
                signal, memory_ctx, tools, conversation_history, extra_system_sections,
            )

        # Step 2: Execute each sub-task
        for i, task in enumerate(plan.sub_tasks):
            plan.current_step = i
            task.status = "in_progress"

            # Create a sub-signal for this task
            sub_signal = Signal(
                content=task.description,
                author_id=signal.author_id,
                author_name=signal.author_name,
                channel_type=signal.channel_type,
                channel_id=signal.channel_id,
            )

            result = await self._deliberate.reason(
                sub_signal, memory_ctx, tools, conversation_history, extra_system_sections,
            )

            task.result = result.response
            task.confidence = result.confidence
            task.status = "complete"

        # Step 3: Self-critique
        critique_passed = await self._self_critique(plan, signal, memory_ctx, extra_system_sections)

        # Step 4: Revise if needed (one revision attempt)
        if not critique_passed and plan.revisions < plan.max_revisions:
            plan.revisions += 1
            plan = await self._revise_plan(
                plan,
                signal,
                memory_ctx,
                tools,
                conversation_history,
                extra_system_sections,
            )

        # Step 5: Synthesize final answer
        envelope = await self._synthesize(plan, signal, memory_ctx, extra_system_sections)

        await self._bus.publish(
            EventType.REFLECTION_COMPLETE,
            {
                "signal_id": signal.id,
                "sub_tasks": len(plan.sub_tasks),
                "revisions": plan.revisions,
                "confidence": envelope.confidence,
            },
            source="reasoning.reflective",
        )

        return envelope

    async def _decompose(
        self,
        signal: Signal,
        memory_ctx: MemoryContext,
        extra_system_sections: list[str] | None = None,
    ) -> ReflectionPlan:
        """Ask the LLM to decompose the query into sub-tasks."""
        if self._structured:
            try:
                result = await self._structured.extract(
                    text=signal.content,
                    schema=TaskDecomposition,
                    instructions=(
                        f"Break down the request into {self.MAX_SUB_TASKS} or fewer "
                        "clear sequential sub_tasks. Set estimated_complexity and list any "
                        "tools that are likely required."
                    ),
                    max_retries=3,
                    extra_system_sections=extra_system_sections,
                )
                sub_tasks = [
                    SubTask(id=i, description=str(desc))
                    for i, desc in enumerate(result.sub_tasks[: self.MAX_SUB_TASKS])
                ]
                if sub_tasks:
                    return ReflectionPlan(
                        original_query=signal.content,
                        sub_tasks=sub_tasks,
                    )
            except StructuredOutputError:
                pass

        decompose_signal = Signal(
            content=(
                f"Break down this complex request into {self.MAX_SUB_TASKS} or fewer "
                f"clear, sequential sub-tasks. Return ONLY a JSON array of strings, "
                f"each being one sub-task description.\n\n"
                f"Request: {signal.content}\n\n"
                f"Return format: [\"sub-task 1\", \"sub-task 2\", ...]"
            ),
            author_id=signal.author_id,
            author_name=signal.author_name,
            channel_type=signal.channel_type,
            channel_id=signal.channel_id,
        )

        result = await self._deliberate.reason(
            decompose_signal,
            memory_ctx,
            extra_system_sections=extra_system_sections,
        )

        # Parse sub-tasks from LLM response
        sub_tasks: list[SubTask] = []
        try:
            # Try to extract JSON array from response
            content = result.response
            start = content.find("[")
            end = content.rfind("]") + 1
            if start >= 0 and end > start:
                tasks_list = json.loads(content[start:end])
                for i, desc in enumerate(tasks_list[:self.MAX_SUB_TASKS]):
                    sub_tasks.append(SubTask(id=i, description=str(desc)))
        except (json.JSONDecodeError, ValueError):
            # If parsing fails, treat the whole query as one task
            pass

        return ReflectionPlan(
            original_query=signal.content,
            sub_tasks=sub_tasks,
        )

    async def _self_critique(
        self,
        plan: ReflectionPlan,
        signal: Signal,
        memory_ctx: MemoryContext,
        extra_system_sections: list[str] | None = None,
    ) -> bool:
        """
        Ask the LLM to evaluate the quality of sub-task results.
        Returns True if the critique passes.
        """
        results_summary = "\n".join(
            f"Step {t.id + 1}: {t.description}\n  Result: {(t.result or 'N/A')[:200]}\n  Confidence: {t.confidence}"
            for t in plan.sub_tasks
        )

        critique_signal = Signal(
            content=(
                f"Evaluate whether these sub-task results adequately answer the original question. "
                f"Reply with PASS if they do, or FAIL with a brief explanation of what's missing.\n\n"
                f"Original question: {plan.original_query}\n\n"
                f"Sub-task results:\n{results_summary}"
            ),
            author_id=signal.author_id,
            author_name=signal.author_name,
            channel_type=signal.channel_type,
            channel_id=signal.channel_id,
        )

        result = await self._deliberate.reason(
            critique_signal,
            memory_ctx,
            extra_system_sections=extra_system_sections,
        )
        return "PASS" in result.response.upper()

    async def _revise_plan(
        self,
        plan: ReflectionPlan,
        signal: Signal,
        memory_ctx: MemoryContext,
        tools: list[ToolDef] | None,
        history: list[dict[str, str]] | None,
        extra_system_sections: list[str] | None = None,
    ) -> ReflectionPlan:
        """Re-execute failed or low-confidence sub-tasks."""
        for task in plan.sub_tasks:
            if task.confidence < 0.5:
                task.status = "revised"
                sub_signal = Signal(
                    content=(
                        f"Please provide a more thorough answer to: {task.description}\n\n"
                        f"Previous attempt was: {(task.result or 'N/A')[:200]}\n"
                        f"Try to be more specific and accurate."
                    ),
                    author_id=signal.author_id,
                    author_name=signal.author_name,
                    channel_type=signal.channel_type,
                    channel_id=signal.channel_id,
                )
                result = await self._deliberate.reason(
                    sub_signal,
                    memory_ctx,
                    tools,
                    history,
                    extra_system_sections,
                )
                task.result = result.response
                task.confidence = result.confidence

        return plan

    async def _synthesize(
        self,
        plan: ReflectionPlan,
        signal: Signal,
        memory_ctx: MemoryContext,
        extra_system_sections: list[str] | None = None,
    ) -> ConfidenceEnvelope:
        """Synthesize the final answer from all sub-task results."""
        results_text = "\n\n".join(
            f"**{t.description}:**\n{t.result or 'No result'}"
            for t in plan.sub_tasks
        )

        synth_signal = Signal(
            content=(
                f"Synthesize a comprehensive answer to this question based on the research below. "
                f"Provide a clear, well-organized response.\n\n"
                f"Original question: {plan.original_query}\n\n"
                f"Research results:\n{results_text}"
            ),
            author_id=signal.author_id,
            author_name=signal.author_name,
            channel_type=signal.channel_type,
            channel_id=signal.channel_id,
        )

        result = await self._deliberate.reason(
            synth_signal,
            memory_ctx,
            extra_system_sections=extra_system_sections,
        )

        # Compute aggregate confidence
        avg_confidence = (
            sum(t.confidence for t in plan.sub_tasks) / len(plan.sub_tasks)
            if plan.sub_tasks else 0.5
        )
        # Synthesis confidence is weighted average of sub-task + synthesis
        final_confidence = (avg_confidence * 0.6 + result.confidence * 0.4)

        return ConfidenceEnvelope(
            response=result.response,
            confidence=round(final_confidence, 2),
            source="reflective",
            alternatives_considered=len(plan.sub_tasks),
            uncertainty_factors=result.uncertainty_factors + (
                ["revised_plan"] if plan.revisions > 0 else []
            ),
            tool_calls_made=result.tool_calls_made,
        )
