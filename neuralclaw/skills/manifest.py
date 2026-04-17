"""
Skill Manifest — Skill capability declarations.

Every skill declares its metadata, required capabilities, and tool
definitions in a SkillManifest. This is the contract between a skill
and the NeuralClaw runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from neuralclaw.cortex.action.capabilities import Capability


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

@dataclass
class ToolParameter:
    """A parameter for a tool function."""
    name: str
    type: str  # "string", "integer", "boolean", "number", "array", "object"
    description: str
    required: bool = True
    default: Any = None
    enum: list[str] | None = None
    items_type: str = "string"  # For arrays: the type of each element

    def to_json_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {
            "type": self.type,
            "description": self.description,
        }
        if self.enum:
            schema["enum"] = self.enum
        # OpenAI requires "items" for array types
        if self.type == "array":
            if self.items_type == "array":
                # Nested array (e.g. 2D sheet values)
                schema["items"] = {"type": "array", "items": {"type": "string"}}
            else:
                schema["items"] = {"type": self.items_type}
        return schema


@dataclass
class ToolDefinition:
    """A single tool exposed by a skill."""
    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)
    handler: Callable[..., Coroutine[Any, Any, Any]] | None = None

    def to_json_schema(self) -> dict[str, Any]:
        """Convert to JSON Schema for LLM tool use."""
        required = [p.name for p in self.parameters if p.required]
        properties = {p.name: p.to_json_schema() for p in self.parameters}

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }


@dataclass
class SkillManifest:
    """
    Metadata and capability declarations for a skill.

    Every skill must provide a manifest that declares:
    - What it does (name, description)
    - What it needs (capabilities)
    - What tools it exposes (tool definitions)
    """
    name: str
    description: str
    version: str = "0.1.0"
    author: str = "neuralclaw"
    capabilities: list[Capability] = field(default_factory=list)
    tools: list[ToolDefinition] = field(default_factory=list)
    enabled: bool = True
    dependencies: list[str] = field(default_factory=list)
    composition_metadata: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"
    multimodal_capabilities: list[str] = field(default_factory=list)
