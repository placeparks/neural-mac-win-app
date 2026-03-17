"""
Structured reasoning helpers backed by Pydantic validation.

The module wraps the existing deliberative reasoner and retries when the model
returns output that does not satisfy the target schema.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.cortex.memory.retrieval import MemoryContext
from neuralclaw.cortex.perception.intake import Signal
from neuralclaw.cortex.reasoning.deliberate import DeliberativeReasoner


class StructuredOutputError(Exception):
    """Raised when a response cannot be validated against a schema."""

    def __init__(
        self,
        message: str,
        *,
        last_response: str = "",
        validation_errors: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.last_response = last_response
        self.validation_errors = validation_errors or []


class GeneratedSkill(BaseModel):
    name: str
    description: str
    code: str
    test_cases: list[str] = Field(default_factory=list)
    required_imports: list[str] = Field(default_factory=list)
    estimated_risk: float = Field(ge=0.0, le=1.0)


class ExtractedFact(BaseModel):
    subject: str
    predicate: str
    obj: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_quote: str


class TaskDecomposition(BaseModel):
    sub_tasks: list[str] = Field(default_factory=list)
    estimated_complexity: Literal["simple", "moderate", "complex"] = "moderate"
    requires_tools: list[str] = Field(default_factory=list)


class StructuredReasoner:
    """Retrying structured extraction on top of the deliberative reasoner."""

    def __init__(
        self,
        deliberate: DeliberativeReasoner,
        bus: NeuralBus | None = None,
    ) -> None:
        self._deliberate = deliberate
        self._bus = bus

    async def reason_structured(
        self,
        signal: Signal,
        schema: type[BaseModel],
        memory_ctx: MemoryContext | None = None,
        max_retries: int = 3,
        use_json_mode: bool = True,
        conversation_history: list[dict[str, str]] | None = None,
        extra_system_sections: list[str] | None = None,
    ) -> BaseModel:
        """Ask the LLM for JSON matching `schema`, retrying on validation failure."""
        memory_ctx = memory_ctx or MemoryContext()
        retries = max(1, max_retries)
        validation_errors: list[str] = []
        last_response = ""

        if self._bus:
            await self._bus.publish(
                EventType.REASONING_STARTED,
                {
                    "component": "structured_reasoner",
                    "signal_id": signal.id,
                    "schema": schema.__name__,
                    "max_retries": retries,
                    "json_mode": use_json_mode,
                },
                source="reasoning.structured",
            )

        for attempt in range(1, retries + 1):
            sections = list(extra_system_sections or [])
            sections.append(self._schema_instruction(schema, use_json_mode))
            if validation_errors:
                joined = " | ".join(validation_errors[-3:])
                sections.append(
                    "## Validation Feedback\n"
                    f"The previous response failed schema validation. Fix these issues and return only valid JSON: {joined}"
                )

            envelope = await self._deliberate.reason(
                signal=signal,
                memory_ctx=memory_ctx,
                conversation_history=conversation_history,
                extra_system_sections=sections,
            )
            last_response = envelope.response or ""

            try:
                payload = self._extract_json(last_response)
                validated = schema.model_validate_json(payload)
                if self._bus:
                    await self._bus.publish(
                        EventType.REASONING_COMPLETE,
                        {
                            "component": "structured_reasoner",
                            "signal_id": signal.id,
                            "schema": schema.__name__,
                            "attempt": attempt,
                        },
                        source="reasoning.structured",
                    )
                return validated
            except StructuredOutputError as exc:
                validation_errors.append(str(exc))
            except ValidationError as exc:
                validation_errors.extend(self._flatten_validation_error(exc))

        error = StructuredOutputError(
            f"Structured output failed after {retries} attempts for schema {schema.__name__}",
            last_response=last_response,
            validation_errors=validation_errors,
        )
        if self._bus:
            await self._bus.publish(
                EventType.ERROR,
                {
                    "component": "structured_reasoner",
                    "schema": schema.__name__,
                    "error": str(error),
                    "validation_errors": validation_errors[:5],
                },
                source="reasoning.structured",
            )
        raise error

    async def extract(
        self,
        text: str,
        schema: type[BaseModel],
        instructions: str = "",
        max_retries: int = 3,
        extra_system_sections: list[str] | None = None,
    ) -> BaseModel:
        """Extract structured data from a text blob."""
        content = (
            f"{instructions.strip()}\n\nText to analyze:\n{text}"
            if instructions.strip()
            else f"Extract structured data from this text:\n{text}"
        )
        signal = Signal(content=content, author_id="system", author_name="StructuredReasoner")
        return await self.reason_structured(
            signal=signal,
            schema=schema,
            memory_ctx=MemoryContext(),
            max_retries=max_retries,
            extra_system_sections=extra_system_sections,
        )

    def _schema_instruction(self, schema: type[BaseModel], use_json_mode: bool) -> str:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        mode_line = "Return JSON only." if use_json_mode else "Prefer raw JSON only."
        return (
            "## Structured Output Contract\n"
            f"{mode_line}\n"
            "Do not include markdown fences, explanations, or prose outside the JSON document.\n"
            f"Target schema name: {schema.__name__}\n"
            f"JSON schema: {schema_json}"
        )

    def _extract_json(self, text: str) -> str:
        stripped = text.strip()
        if not stripped:
            raise StructuredOutputError("Model returned empty output")

        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 3 and lines[-1].strip() == "```":
                stripped = "\n".join(lines[1:-1]).strip()
                if stripped.lower().startswith("json"):
                    stripped = stripped[4:].strip()

        decoder = json.JSONDecoder()
        for idx, char in enumerate(stripped):
            if char not in "{[":
                continue
            try:
                obj, end = decoder.raw_decode(stripped[idx:])
                return json.dumps(obj, ensure_ascii=False)
            except json.JSONDecodeError:
                continue

        raise StructuredOutputError("Could not find valid JSON object or array in model output")

    def _flatten_validation_error(self, exc: ValidationError) -> list[str]:
        items: list[str] = []
        for item in exc.errors():
            loc = ".".join(str(part) for part in item.get("loc", []))
            msg = item.get("msg", "validation error")
            items.append(f"{loc}: {msg}" if loc else msg)
        return items or [str(exc)]
