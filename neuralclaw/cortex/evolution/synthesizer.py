"""
Skill Synthesizer — Auto-generate new skills from failed tasks.

When NeuralClaw encounters a task it can't handle well, the synthesizer:
1. Analyzes what went wrong
2. Drafts a new skill definition
3. Tests it in sandbox
4. Registers it if successful

This is the heart of NeuralClaw's self-evolution capability.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.cortex.action.sandbox import Sandbox
from neuralclaw.cortex.memory.retrieval import MemoryContext
from neuralclaw.cortex.perception.intake import Signal
from neuralclaw.cortex.reasoning.structured import GeneratedSkill, StructuredReasoner
from neuralclaw.skills.manifest import Capability, SkillManifest, ToolDefinition, ToolParameter


# ---------------------------------------------------------------------------
# Synthesis result
# ---------------------------------------------------------------------------

@dataclass
class SynthesisResult:
    """Result of a skill synthesis attempt."""
    success: bool
    skill_name: str
    description: str
    code: str = ""
    error: str | None = None
    test_output: str = ""


@dataclass
class FailedTask:
    """A task the agent couldn't handle well."""
    query: str
    error: str
    timestamp: float = field(default_factory=time.time)
    category: str = "unknown"


# ---------------------------------------------------------------------------
# Skill Synthesizer
# ---------------------------------------------------------------------------

class SkillSynthesizer:
    """
    Analyzes failed tasks and attempts to generate new skills.

    Uses the LLM to write skill code, tests it in sandbox,
    and if it works, registers it with the skill registry.
    """

    def __init__(
        self,
        bus: NeuralBus | None = None,
        sandbox: Sandbox | None = None,
        structured: StructuredReasoner | None = None,
    ) -> None:
        self._bus = bus
        self._sandbox = sandbox or Sandbox(timeout_seconds=15)
        self._structured = structured
        self._failed_tasks: list[FailedTask] = []
        self._synthesized: list[SynthesisResult] = []
        self._provider: Any = None

    def set_provider(self, provider: Any) -> None:
        """Set the LLM provider for code generation."""
        self._provider = provider

    def set_structured(self, structured: StructuredReasoner | None) -> None:
        """Inject the shared structured reasoner."""
        self._structured = structured

    def record_failure(self, query: str, error: str, category: str = "unknown") -> None:
        """Record a failed task for later analysis."""
        self._failed_tasks.append(FailedTask(query=query, error=error, category=category))

        # Keep only recent failures
        if len(self._failed_tasks) > 100:
            self._failed_tasks = self._failed_tasks[-100:]

    async def analyze_failures(self) -> list[dict[str, Any]]:
        """Analyze failure patterns and suggest skill ideas."""
        if not self._failed_tasks:
            return []

        # Group failures by category
        categories: dict[str, list[FailedTask]] = {}
        for task in self._failed_tasks:
            cat = task.category
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(task)

        suggestions = []
        for cat, tasks in categories.items():
            if len(tasks) >= 2:  # At least 2 similar failures
                suggestions.append({
                    "category": cat,
                    "failure_count": len(tasks),
                    "example_queries": [t.query for t in tasks[:3]],
                    "common_errors": list(set(t.error for t in tasks))[:3],
                })

        return suggestions

    async def synthesize_skill(
        self,
        name: str,
        description: str,
        example_inputs: list[str],
        expected_outputs: list[str],
    ) -> SynthesisResult:
        """
        Attempt to synthesize a new skill.

        Asks the LLM to write Python code for the skill,
        tests it in the sandbox, and returns the result.
        """
        if not self._provider and not self._structured:
            return SynthesisResult(
                success=False,
                skill_name=name,
                description=description,
                error="No LLM provider configured for synthesis",
            )

        prompt = self._build_synthesis_prompt(name, description, example_inputs, expected_outputs)
        generated: GeneratedSkill | None = None

        if self._structured:
            try:
                generated = await self._structured.reason_structured(
                    signal=Signal(
                        content=prompt,
                        author_id="system",
                        author_name="SkillSynthesizer",
                    ),
                    schema=GeneratedSkill,
                    memory_ctx=MemoryContext(),
                    extra_system_sections=[
                        "## Skill Generation Rules\n"
                        f"- The function name must be exactly `{name}`\n"
                        "- The `code` field must contain runnable Python only\n"
                        "- Keep the implementation async and return a dict\n"
                        "- Do not include markdown fences inside the code field"
                    ],
                )
            except Exception:
                generated = None

        final_description = description
        if generated:
            code = self._materialize_generated_code(generated)
            final_description = generated.description or description
        else:
            try:
                response = await self._provider.complete(
                    messages=[
                        {"role": "system", "content": "You are a Python skill code generator. Write clean, async Python functions."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                )
            except Exception as e:
                return SynthesisResult(
                    success=False, skill_name=name, description=description,
                    error=f"LLM generation failed: {e}",
                )

            code = self._extract_code(response.content or "")
        if not code:
            return SynthesisResult(
                success=False, skill_name=name, description=description,
                error="Could not extract valid Python code from model output",
            )

        # Test in sandbox
        test_code = f"""
{code}

import asyncio

async def test():
    # Basic smoke test
    result = await {name}({json.dumps(example_inputs[0]) if example_inputs else "'test'"})
    print("TEST_RESULT:", result)

asyncio.run(test())
"""

        sandbox_result = await self._sandbox.execute_python(test_code)

        result = SynthesisResult(
            success=sandbox_result.success,
            skill_name=name,
            description=final_description,
            code=code,
            test_output=sandbox_result.output,
            error=sandbox_result.error,
        )

        self._synthesized.append(result)

        # Publish event
        if self._bus:
            await self._bus.publish(
                EventType.SKILL_SYNTHESIZED,
                {
                    "name": name,
                    "success": result.success,
                    "code_lines": len(code.split("\n")),
                    "test_output": sandbox_result.output[:200],
                },
                source="evolution.synthesizer",
            )

        return result

    def _build_synthesis_prompt(
        self,
        name: str,
        description: str,
        example_inputs: list[str],
        expected_outputs: list[str],
    ) -> str:
        examples = ""
        for inp, out in zip(example_inputs, expected_outputs):
            examples += f"  Input: {inp}\n  Expected: {out}\n\n"

        return (
            f"Write a Python async function called `{name}` that:\n"
            f"- {description}\n\n"
            f"Examples:\n{examples}"
            f"Requirements:\n"
            f"- Function must be async\n"
            f"- Return a dict with results\n"
            f"- Handle errors gracefully\n"
            f"- No external imports beyond standard library + aiohttp\n"
            f"- Include a brief docstring\n\n"
            f"Return ONLY the Python code, no markdown or explanation."
        )

    def _extract_code(self, response: str) -> str:
        """Extract Python code from LLM response."""
        # Try to find code block
        if "```python" in response:
            start = response.find("```python") + 9
            end = response.find("```", start)
            if end > start:
                return response[start:end].strip()

        if "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            if end > start:
                return response[start:end].strip()

        # Assume the whole response is code
        return response.strip()

    def _materialize_generated_code(self, generated: GeneratedSkill) -> str:
        lines: list[str] = []
        for item in generated.required_imports:
            cleaned = item.strip()
            if cleaned:
                lines.append(cleaned)
        if lines and generated.code.strip():
            lines.append("")
        if generated.code.strip():
            lines.append(generated.code.strip())
        return "\n".join(lines).strip()

    @property
    def failure_count(self) -> int:
        return len(self._failed_tasks)

    @property
    def synthesis_count(self) -> int:
        return len(self._synthesized)
