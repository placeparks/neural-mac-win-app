"""
Agent Runtime — Lightweight reasoning pipeline for spawned agents.

Each agent gets its own provider, memory namespace, and system prompt.
Handles incoming mesh messages and delegation tasks through a simplified
cognitive pipeline: memory recall -> LLM completion -> memory store.
Supports tool-use via an optional SkillRegistry for spawned agents that
need access to skills/tools (web search, file ops, etc.).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, TYPE_CHECKING

from neuralclaw.cortex.action.param_validator import validate_tool_params
from neuralclaw.cortex.memory.episodic import EpisodicMemory
from neuralclaw.cortex.memory.procedural import ProceduralMemory
from neuralclaw.cortex.memory.semantic import SemanticMemory
from neuralclaw.cortex.memory.shared import SharedMemoryBridge
from neuralclaw.errors import ErrorCode, StructuredError
from neuralclaw.providers.router import LLMProvider, LLMResponse
from neuralclaw.swarm.agent_store import AgentDefinition
from neuralclaw.swarm.delegation import DelegationContext, DelegationResult, DelegationStatus
from neuralclaw.swarm.mesh import MeshMessage

if TYPE_CHECKING:
    from neuralclaw.cortex.reasoning.deliberate import ToolDef
    from neuralclaw.skills.registry import SkillRegistry

log = logging.getLogger(__name__)


def _error_detail(exc: Exception) -> str:
    """Return a stable, non-empty error detail for logs, metrics, and replies."""
    return str(exc).strip() or repr(exc).strip() or type(exc).__name__


def build_provider(defn: AgentDefinition, request_timeout_seconds: float | None = None) -> LLMProvider:
    """Create a provider instance from an agent definition."""
    provider_type = defn.provider.lower()
    timeout_seconds = request_timeout_seconds
    if timeout_seconds is None:
        timeout_seconds = float(
            defn.metadata.get(
                "request_timeout_seconds",
                300.0 if provider_type in ("local", "ollama") else 120.0,
            )
        )

    if provider_type in ("local", "ollama"):
        from neuralclaw.providers.local import LocalProvider
        return LocalProvider(
            model=defn.model,
            base_url=defn.base_url or "http://localhost:11434/v1",
            request_timeout_seconds=timeout_seconds,
        )
    elif provider_type == "openai":
        from neuralclaw.providers.openai import OpenAIProvider
        return OpenAIProvider(
            api_key=defn.api_key,
            model=defn.model,
            base_url=defn.base_url or "https://api.openai.com/v1",
            request_timeout_seconds=timeout_seconds,
        )
    elif provider_type == "anthropic":
        from neuralclaw.providers.anthropic import AnthropicProvider
        return AnthropicProvider(
            api_key=defn.api_key,
            model=defn.model,
            request_timeout_seconds=timeout_seconds,
        )
    elif provider_type == "openrouter":
        from neuralclaw.providers.openrouter import OpenRouterProvider
        return OpenRouterProvider(
            api_key=defn.api_key,
            model=defn.model,
            request_timeout_seconds=timeout_seconds,
        )
    else:
        # Default: treat as OpenAI-compatible
        from neuralclaw.providers.openai import OpenAIProvider
        return OpenAIProvider(
            api_key=defn.api_key or "none",
            model=defn.model,
            base_url=defn.base_url or "https://api.openai.com/v1",
            request_timeout_seconds=timeout_seconds,
        )


class AgentRuntime:
    """
    Lightweight reasoning runtime for a spawned agent.

    Each agent gets:
    - Its own LLM provider (any provider + model)
    - Its own memory namespace (episodic via author, semantic/procedural via namespace)
    - Its own system prompt
    - Access to shared memory for collaborative tasks
    """

    # Maximum tool-use loop iterations to prevent runaway tool calls.
    MAX_TOOL_ITERATIONS = 8

    def __init__(
        self,
        definition: AgentDefinition,
        episodic: EpisodicMemory | None = None,
        semantic: SemanticMemory | None = None,
        procedural: ProceduralMemory | None = None,
        shared_bridge: SharedMemoryBridge | None = None,
        skill_registry: "SkillRegistry | None" = None,
    ) -> None:
        self.definition = definition
        self._provider_timeout_seconds = float(
            definition.metadata.get(
                "request_timeout_seconds",
                300.0 if definition.provider.lower() in ("local", "ollama") else 120.0,
            )
        )
        self.provider = build_provider(definition, self._provider_timeout_seconds)
        self._episodic = episodic
        self._semantic = semantic
        self._procedural = procedural
        self._shared = shared_bridge
        self._skill_registry = skill_registry
        self._namespace = definition.memory_namespace or f"agent:{definition.name}"
        self._conversation: list[dict[str, str]] = []
        self._metrics: dict[str, Any] = {
            "requested_model": definition.model,
            "effective_model": definition.model,
            "base_url": definition.base_url,
            "last_task_at": 0.0,
            "avg_latency_ms": 0.0,
            "success_count": 0,
            "failure_count": 0,
            "token_usage": {"input": 0, "output": 0, "total": 0},
            "last_error": "",
            "recent_tasks": [],
            "recent_logs": [],
        }

    def _rebuild_provider(self, *, min_timeout_seconds: float | None = None) -> None:
        timeout_seconds = self._provider_timeout_seconds
        if min_timeout_seconds is not None:
            timeout_seconds = max(timeout_seconds, float(min_timeout_seconds))
        self._provider_timeout_seconds = timeout_seconds
        self.definition.metadata["request_timeout_seconds"] = timeout_seconds
        self.provider = build_provider(self.definition, timeout_seconds)

    def get_metrics(self) -> dict[str, Any]:
        return {
            **self._metrics,
            "token_usage": dict(self._metrics.get("token_usage", {})),
            "recent_tasks": list(self._metrics.get("recent_tasks", [])),
            "recent_logs": list(self._metrics.get("recent_logs", [])),
            "memory_namespace": self._namespace,
        }

    def update_execution_context(
        self,
        *,
        requested_model: str | None = None,
        effective_model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        if requested_model:
            self._metrics["requested_model"] = requested_model
        if effective_model:
            self._metrics["effective_model"] = effective_model
            self.definition.model = effective_model
        if base_url:
            self._metrics["base_url"] = base_url
            self.definition.base_url = base_url
        self._rebuild_provider()

    def _record_usage(self, usage: dict[str, Any] | None) -> None:
        if not isinstance(usage, dict):
            return
        input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or (input_tokens + output_tokens))
        token_usage = self._metrics["token_usage"]
        token_usage["input"] += input_tokens
        token_usage["output"] += output_tokens
        token_usage["total"] += total_tokens

    def _approximate_usage(self, messages: list[dict[str, Any]], content: str) -> None:
        prompt_chars = sum(len(str(message.get("content", ""))) for message in messages)
        output_chars = len(content)
        approx_in = max(1, prompt_chars // 4) if prompt_chars else 0
        approx_out = max(1, output_chars // 4) if output_chars else 0
        token_usage = self._metrics["token_usage"]
        token_usage["input"] += approx_in
        token_usage["output"] += approx_out
        token_usage["total"] += approx_in + approx_out

    def _record_completion(
        self,
        *,
        task: str,
        result: str,
        elapsed_seconds: float,
        success: bool,
        error: str = "",
    ) -> None:
        latency_ms = elapsed_seconds * 1000.0
        successes = int(self._metrics["success_count"])
        failures = int(self._metrics["failure_count"])
        prev_count = successes + failures
        self._metrics["avg_latency_ms"] = (
            ((float(self._metrics["avg_latency_ms"]) * prev_count) + latency_ms) / max(1, prev_count + 1)
        )
        self._metrics["last_task_at"] = time.time()
        if success:
            self._metrics["success_count"] = successes + 1
            self._metrics["last_error"] = ""
        else:
            self._metrics["failure_count"] = failures + 1
            self._metrics["last_error"] = error

        recent_tasks = self._metrics["recent_tasks"]
        recent_tasks.append(
            {
                "task": task[:220],
                "result_preview": (result or error or "").strip()[:280],
                "success": success,
                "latency_ms": round(latency_ms, 2),
                "timestamp": time.time(),
            }
        )
        del recent_tasks[:-8]

        recent_logs = self._metrics["recent_logs"]
        recent_logs.append(
            {
                "timestamp": time.time(),
                "message": (result or error or "").strip()[:280],
                "level": "info" if success else "error",
            }
        )
        del recent_logs[:-12]

    @property
    def system_prompt(self) -> str:
        base = self.definition.system_prompt
        if not base:
            base = (
                f"You are {self.definition.name}, an AI agent. "
                f"{self.definition.description}"
            )
        return base

    # -- Tool helpers --------------------------------------------------------

    def _resolve_tools(
        self,
        ctx_tools: list[Any] | None = None,
        allowed_skills: list[str] | None = None,
    ) -> list["ToolDef"]:
        """
        Resolve the effective set of ToolDefs for this agent.

        Priority: explicit context tools > skill_registry tools.
        If *allowed_skills* is non-empty, only tools whose name appears in
        that list (or belongs to a skill in that list) are included.
        """
        from neuralclaw.cortex.reasoning.deliberate import ToolDef

        tools: list[ToolDef] = []

        # 1. Explicit tools passed via DelegationContext / caller
        if ctx_tools:
            for t in ctx_tools:
                if isinstance(t, ToolDef):
                    tools.append(t)

        # 2. Fall back to skill registry
        if not tools and self._skill_registry:
            tools = self._skill_registry.get_all_tools()

        # 3. Filter by allowed_skills if specified
        if allowed_skills and tools:
            allowed_set = set(allowed_skills)
            tools = [t for t in tools if t.name in allowed_set]

        return tools

    async def _execute_tool_call(
        self,
        tool_call: Any,
        tools: list["ToolDef"],
    ) -> dict[str, Any]:
        """Execute a single tool call and return the result dict."""
        tool_name = tool_call.name
        tool_args = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}

        tool = next((t for t in tools if t.name == tool_name), None)
        if not tool or not tool.handler:
            log.warning(
                "AgentRuntime[%s] tool not found: %s",
                self.definition.name, tool_name,
            )
            return StructuredError(
                code=ErrorCode.TOOL_NOT_FOUND,
                message=f"Tool '{tool_name}' not found or has no handler",
                recoverable=True,
                suggestion="Check available tools and use a different one.",
            ).to_tool_result()

        # Parameter validation and coercion
        if tool.parameters:
            param_err = validate_tool_params(tool_name, tool_args, tool.parameters)
            if param_err is not None:
                log.warning(
                    "AgentRuntime[%s] tool '%s' invalid params: %s",
                    self.definition.name, tool_name, param_err.message,
                )
                return param_err.to_tool_result()

        try:
            result = await tool.handler(**tool_args)
            if not isinstance(result, dict):
                result = {"result": result}
            return result
        except Exception as exc:
            detail = _error_detail(exc)
            log.error(
                "AgentRuntime[%s] tool '%s' failed: %s",
                self.definition.name, tool_name, detail,
            )
            return StructuredError(
                code=ErrorCode.TOOL_EXECUTION_FAILED,
                message=f"Tool '{tool_name}' failed: {detail}",
                recoverable=True,
                suggestion="Try with different arguments or use an alternative tool.",
            ).to_tool_result()

    async def _run_tool_loop(
        self,
        messages: list[dict[str, Any]],
        tools: list["ToolDef"],
        temperature: float = 0.5,
        max_tokens: int = 4096,
    ) -> tuple[str, int]:
        """
        Run the LLM with tool-use loop.

        Calls the provider, and if the response contains tool_calls,
        executes them, appends results, and re-calls the LLM.
        Repeats up to MAX_TOOL_ITERATIONS times.

        Returns:
            (final_text, tool_calls_made)
        """
        tool_defs = [t.to_openai_format() for t in tools] if tools else None
        tool_calls_made = 0

        for iteration in range(self.MAX_TOOL_ITERATIONS):
            response: LLMResponse = await self.provider.complete(
                messages=messages,
                tools=tool_defs,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            self._record_usage(response.usage or {})
            if not response.usage:
                self._approximate_usage(messages, response.content or "")
            self._metrics["effective_model"] = (
                response.model or self._metrics["effective_model"]
            )

            # No tool calls -> final text response
            if not response.tool_calls or not tools:
                return (response.content or ""), tool_calls_made

            # Process tool calls
            for tc in response.tool_calls:
                tool_calls_made += 1
                result = await self._execute_tool_call(tc, tools)
                result_str = json.dumps(result, ensure_ascii=False, default=str)

                # Append assistant message with tool call
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [tc.to_dict()],
                })
                # Append tool result
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

                log.debug(
                    "AgentRuntime[%s] tool '%s' iteration=%d result_preview=%.200s",
                    self.definition.name, tc.name, iteration + 1, result_str,
                )

        # Exhausted iterations — force a text-only completion
        log.warning(
            "AgentRuntime[%s] hit max tool iterations (%d), forcing text response",
            self.definition.name, self.MAX_TOOL_ITERATIONS,
        )
        fallback: LLMResponse = await self.provider.complete(
            messages=messages + [{
                "role": "user",
                "content": (
                    "You have used all available tool iterations. "
                    "Please give a final answer now based on what you have gathered."
                ),
            }],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._record_usage(fallback.usage or {})
        return (fallback.content or ""), tool_calls_made

    async def handle_message(self, msg: MeshMessage) -> MeshMessage | None:
        """Process an incoming mesh message through this agent's pipeline."""
        start = time.time()
        try:
            # Build context
            messages = [{"role": "system", "content": self.system_prompt}]

            # Add memory context
            memory_context = await self._recall_memories(msg.content)
            if memory_context:
                messages.append({
                    "role": "system",
                    "content": f"Relevant memories:\n{memory_context}",
                })

            shared_task_id = str(msg.payload.get("shared_task_id") or "").strip()
            if shared_task_id:
                shared_context = await self._get_shared_context(shared_task_id)
                if shared_context:
                    messages.append({
                        "role": "system",
                        "content": f"Shared task context:\n{shared_context}",
                    })

            # Add conversation history (keep last 10 turns)
            messages.extend(self._conversation[-20:])

            # Add the incoming message
            messages.append({"role": "user", "content": msg.content})

            # Resolve tools for this agent
            tools = self._resolve_tools()

            # Call LLM (with tool-use loop if tools are available)
            if tools:
                result_text, _tc_count = await self._run_tool_loop(
                    messages=messages,
                    tools=tools,
                    temperature=self.definition.metadata.get("temperature", 0.7),
                    max_tokens=self.definition.metadata.get("max_tokens", 4096),
                )
            else:
                response: LLMResponse = await self.provider.complete(
                    messages=messages,
                    temperature=self.definition.metadata.get("temperature", 0.7),
                    max_tokens=self.definition.metadata.get("max_tokens", 4096),
                )
                result_text = response.content or ""
                self._record_usage(response.usage or {})
                if not response.usage:
                    self._approximate_usage(messages, result_text)
                self._metrics["effective_model"] = response.model or self._metrics["effective_model"]

            # Store in conversation history
            self._conversation.append({"role": "user", "content": msg.content})
            self._conversation.append({"role": "assistant", "content": result_text})

            # Store in episodic memory
            if self._episodic:
                await self._episodic.store(
                    content=f"[{msg.from_agent}]: {msg.content}\n[{self.definition.name}]: {result_text}",
                    source="agent_mesh",
                    author=self._namespace,
                    importance=0.6,
                )

            # If this is part of a shared task, write to shared memory
            if shared_task_id and self._shared:
                await self._shared.share_memory(
                    task_id=shared_task_id,
                    from_agent=self.definition.name,
                    content=result_text,
                    memory_type="episodic",
                )

            self._record_completion(
                task=msg.content,
                result=result_text,
                elapsed_seconds=time.time() - start,
                success=True,
            )

            return msg.reply(
                content=result_text,
                payload={"confidence": self._estimate_confidence(result_text), "model": self.definition.model},
            )

        except Exception as e:
            detail = _error_detail(e)
            log.error("AgentRuntime[%s] error: %s", self.definition.name, detail)
            self._record_completion(
                task=msg.content,
                result="",
                elapsed_seconds=time.time() - start,
                success=False,
                error=detail,
            )
            return msg.reply(
                content=f"Error: {detail}",
                payload={"error": detail},
            )

    async def handle_delegation(self, ctx: DelegationContext) -> DelegationResult:
        """Handle a delegated task from another agent or the main gateway."""
        start = time.time()
        try:
            self._rebuild_provider(min_timeout_seconds=max(float(ctx.timeout_seconds or 0.0), 180.0))
            messages = [{"role": "system", "content": self.system_prompt}]

            # Add parent memories if provided
            if ctx.parent_memories:
                context = "\n".join(f"- {m}" for m in ctx.parent_memories)
                messages.append({
                    "role": "system",
                    "content": f"Context from parent agent:\n{context}",
                })

            # Add constraints
            if ctx.constraints:
                messages.append({
                    "role": "system",
                    "content": f"Constraints: {ctx.constraints}",
                })

            shared_task_id = str(ctx.constraints.get("shared_task_id") or "").strip()
            if shared_task_id:
                shared_context = await self._get_shared_context(shared_task_id)
                if shared_context:
                    messages.append({
                        "role": "system",
                        "content": f"Shared task context:\n{shared_context}",
                    })

            messages.append({"role": "user", "content": ctx.task_description})

            # Resolve tools: prefer DelegationContext tools, fall back to registry
            tools = self._resolve_tools(
                ctx_tools=ctx.tools or None,
                allowed_skills=ctx.allowed_skills or None,
            )
            max_tokens = ctx.max_steps * 500 if ctx.max_steps else 4096

            if tools:
                result_text, _tc_count = await self._run_tool_loop(
                    messages=messages,
                    tools=tools,
                    temperature=0.5,
                    max_tokens=max_tokens,
                )
            else:
                response = await self.provider.complete(
                    messages=messages,
                    temperature=0.5,
                    max_tokens=max_tokens,
                )
                result_text = response.content or ""
                self._record_usage(response.usage or {})
                if not response.usage:
                    self._approximate_usage(messages, result_text)
                self._metrics["effective_model"] = response.model or self._metrics["effective_model"]

            # Store result
            if self._episodic:
                await self._episodic.store(
                    content=f"[delegation] Task: {ctx.task_description}\nResult: {result_text}",
                    source="delegation",
                    author=self._namespace,
                    importance=0.7,
                )

            if shared_task_id and self._shared:
                await self._shared.share_memory(
                    task_id=shared_task_id,
                    from_agent=self.definition.name,
                    content=result_text,
                    memory_type="delegation",
                )

            elapsed = time.time() - start
            self._record_completion(
                task=ctx.task_description,
                result=result_text,
                elapsed_seconds=elapsed,
                success=True,
            )
            return DelegationResult(
                delegation_id="",
                status=DelegationStatus.COMPLETED,
                result=result_text,
                confidence=self._estimate_confidence(result_text),
                elapsed_seconds=elapsed,
            )

        except Exception as e:
            detail = _error_detail(e)
            elapsed = time.time() - start
            self._record_completion(
                task=ctx.task_description,
                result="",
                elapsed_seconds=elapsed,
                success=False,
                error=detail,
            )
            return DelegationResult(
                delegation_id="",
                status=DelegationStatus.FAILED,
                error=detail,
                elapsed_seconds=elapsed,
            )

    @staticmethod
    def _estimate_confidence(text: str) -> float:
        """Estimate response confidence from content heuristics."""
        if not text:
            return 0.3
        lower = text.lower()
        # High-uncertainty indicators
        hedging_phrases = (
            "i'm not sure", "i am not sure", "i'm uncertain", "it's unclear",
            "i don't know", "i cannot determine", "i'm not confident",
            "might be", "could be", "possibly", "perhaps", "may or may not",
            "hard to say", "difficult to determine", "unsure",
        )
        hedge_count = sum(1 for p in hedging_phrases if p in lower)
        if hedge_count >= 3:
            return 0.3
        if hedge_count >= 2:
            return 0.5
        if hedge_count >= 1:
            return 0.65
        # Short answers tend to be direct
        if len(text) < 50:
            return 0.75
        return 0.85

    async def _recall_memories(self, query: str) -> str:
        """Recall relevant memories from this agent's namespace."""
        parts: list[str] = []

        if self._episodic:
            try:
                episodes = await self._episodic.get_for_namespace(
                    self._namespace, limit=5,
                )
                if episodes:
                    parts.append("Recent episodes:")
                    for ep in episodes[:5]:
                        parts.append(f"  - {ep.content[:200]}")
            except Exception:
                pass

        if self._semantic:
            try:
                results = await self._semantic.search_entities(query, limit=3)
                if results:
                    parts.append("Related entities:")
                    for ent in results:
                        parts.append(f"  - {ent.name} ({ent.entity_type})")
            except Exception:
                pass

        if self._procedural:
            try:
                procedures = await self._procedural.find_matching(query)
                if procedures:
                    parts.append("Relevant procedures:")
                    for proc in procedures[:3]:
                        parts.append(f"  - {proc.name}: {proc.description}")
            except Exception:
                pass

        return "\n".join(parts) if parts else ""

    async def _get_shared_context(self, task_id: str) -> str:
        if not self._shared:
            return ""
        try:
            memories = await self._shared.get_shared_memories(task_id, limit=8)
        except Exception:
            return ""
        if not memories:
            return ""
        lines = [
            f"- {entry.from_agent} ({entry.memory_type}): {entry.content[:240]}"
            for entry in reversed(memories)
        ]
        return "\n".join(lines)
