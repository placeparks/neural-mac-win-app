"""
Agent Runtime — Lightweight reasoning pipeline for spawned agents.

Each agent gets its own provider, memory namespace, and system prompt.
Handles incoming mesh messages and delegation tasks through a simplified
cognitive pipeline: memory recall -> LLM completion -> memory store.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from neuralclaw.cortex.memory.episodic import EpisodicMemory
from neuralclaw.cortex.memory.procedural import ProceduralMemory
from neuralclaw.cortex.memory.semantic import SemanticMemory
from neuralclaw.cortex.memory.shared import SharedMemoryBridge
from neuralclaw.providers.router import LLMProvider, LLMResponse
from neuralclaw.swarm.agent_store import AgentDefinition
from neuralclaw.swarm.delegation import DelegationContext, DelegationResult, DelegationStatus
from neuralclaw.swarm.mesh import MeshMessage

log = logging.getLogger(__name__)


def build_provider(defn: AgentDefinition) -> LLMProvider:
    """Create a provider instance from an agent definition."""
    provider_type = defn.provider.lower()

    if provider_type in ("local", "ollama"):
        from neuralclaw.providers.local import LocalProvider
        return LocalProvider(
            model=defn.model,
            base_url=defn.base_url or "http://localhost:11434/v1",
        )
    elif provider_type == "openai":
        from neuralclaw.providers.openai import OpenAIProvider
        return OpenAIProvider(
            api_key=defn.api_key,
            model=defn.model,
            base_url=defn.base_url or "https://api.openai.com/v1",
        )
    elif provider_type == "anthropic":
        from neuralclaw.providers.anthropic import AnthropicProvider
        return AnthropicProvider(
            api_key=defn.api_key,
            model=defn.model,
        )
    elif provider_type == "openrouter":
        from neuralclaw.providers.openrouter import OpenRouterProvider
        return OpenRouterProvider(
            api_key=defn.api_key,
            model=defn.model,
        )
    else:
        # Default: treat as OpenAI-compatible
        from neuralclaw.providers.openai import OpenAIProvider
        return OpenAIProvider(
            api_key=defn.api_key or "none",
            model=defn.model,
            base_url=defn.base_url or "https://api.openai.com/v1",
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

    def __init__(
        self,
        definition: AgentDefinition,
        episodic: EpisodicMemory | None = None,
        semantic: SemanticMemory | None = None,
        procedural: ProceduralMemory | None = None,
        shared_bridge: SharedMemoryBridge | None = None,
    ) -> None:
        self.definition = definition
        self.provider = build_provider(definition)
        self._episodic = episodic
        self._semantic = semantic
        self._procedural = procedural
        self._shared = shared_bridge
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

            # Call LLM
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
                payload={"confidence": 0.8, "model": self.definition.model},
            )

        except Exception as e:
            log.error("AgentRuntime[%s] error: %s", self.definition.name, e)
            self._record_completion(
                task=msg.content,
                result="",
                elapsed_seconds=time.time() - start,
                success=False,
                error=str(e),
            )
            return msg.reply(
                content=f"Error: {e}",
                payload={"error": str(e)},
            )

    async def handle_delegation(self, ctx: DelegationContext) -> DelegationResult:
        """Handle a delegated task from another agent or the main gateway."""
        start = time.time()
        try:
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

            response = await self.provider.complete(
                messages=messages,
                temperature=0.5,
                max_tokens=ctx.max_steps * 500 if ctx.max_steps else 4096,
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
                confidence=0.8,
                elapsed_seconds=elapsed,
            )

        except Exception as e:
            elapsed = time.time() - start
            self._record_completion(
                task=ctx.task_description,
                result="",
                elapsed_seconds=elapsed,
                success=False,
                error=str(e),
            )
            return DelegationResult(
                delegation_id="",
                status=DelegationStatus.FAILED,
                error=str(e),
                elapsed_seconds=elapsed,
            )

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
