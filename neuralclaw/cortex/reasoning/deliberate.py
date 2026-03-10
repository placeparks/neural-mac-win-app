"""
Deliberate — Standard LLM-powered reasoning with tool use and confidence signaling.

This is Layer 2 of the reasoning cortex — the standard path for requests
that need the language model. Builds a prompt from memory context + tools,
runs a tool-use loop, and wraps every response in a ConfidenceEnvelope.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.cortex.action.idempotency import IdempotencyStore
from neuralclaw.cortex.action.policy import PolicyEngine, RequestContext
from neuralclaw.cortex.memory.retrieval import MemoryContext
from neuralclaw.cortex.perception.intake import Signal
from neuralclaw.security.redaction import redact_secrets


# ---------------------------------------------------------------------------
# Confidence envelope
# ---------------------------------------------------------------------------

@dataclass
class ConfidenceEnvelope:
    """Wraps every NeuralClaw response with machine-readable confidence."""
    response: str
    confidence: float           # 0.0 – 1.0
    source: str                 # "llm", "tool_verified", "memory", "fast_path"
    alternatives_considered: int = 0
    uncertainty_factors: list[str] = field(default_factory=list)
    tool_calls_made: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "response": self.response,
            "confidence": self.confidence,
            "source": self.source,
            "alternatives_considered": self.alternatives_considered,
            "uncertainty_factors": self.uncertainty_factors,
        }


# ---------------------------------------------------------------------------
# Tool definition (for LLM function calling)
# ---------------------------------------------------------------------------

@dataclass
class ToolDef:
    """A tool available for the LLM to call."""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    handler: Any = None          # Async callable

    def to_openai_format(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic_format(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


# ---------------------------------------------------------------------------
# Deliberative Reasoner
# ---------------------------------------------------------------------------

class DeliberativeReasoner:
    """
    Standard LLM-powered reasoning with tool-use loop and confidence signaling.

    Flow:
    1. Build system prompt from persona + memory context
    2. Send to LLM with available tools
    3. If LLM returns tool calls → execute them → feed results back → iterate
    4. Wrap final response in ConfidenceEnvelope
    5. Max iterations guard (default 10)
    """

    MAX_ITERATIONS = 10

    def __init__(
        self,
        bus: NeuralBus,
        persona: str = "You are NeuralClaw, a helpful AI assistant.",
        policy: PolicyEngine | None = None,
        idempotency: IdempotencyStore | None = None,
    ) -> None:
        self._bus = bus
        self._persona = persona
        self._provider: Any = None  # Set via set_provider()
        self._policy = policy
        self._idempotency = idempotency

    def set_provider(self, provider: Any) -> None:
        """Set the LLM provider for reasoning."""
        self._provider = provider

    async def reason(
        self,
        signal: Signal,
        memory_ctx: MemoryContext,
        tools: list[ToolDef] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> ConfidenceEnvelope:
        """
        Run deliberative reasoning with tool-use loop.
        """
        if not self._provider:
            return ConfidenceEnvelope(
                response="I'm not configured with an LLM provider yet. Run `neuralclaw init` to set up.",
                confidence=0.0,
                source="error",
                uncertainty_factors=["no_provider_configured"],
            )

        # Publish reasoning start
        await self._bus.publish(
            EventType.REASONING_STARTED,
            {"signal_id": signal.id, "path": "deliberative", "tools_available": len(tools or [])},
            source="reasoning.deliberate",
        )

        # Build messages
        messages = self._build_messages(signal, memory_ctx, conversation_history)

        # Build tool defs for the provider
        tool_defs = [t.to_openai_format() for t in (tools or [])] if tools else None

        tool_calls_made = 0
        iterations = 0
        request_ctx = RequestContext(request_id=signal.id)

        while iterations < self.MAX_ITERATIONS:
            iterations += 1

            try:
                response = await self._provider.complete(
                    messages=messages,
                    tools=tool_defs,
                )
            except Exception as e:
                return ConfidenceEnvelope(
                    response=f"I encountered an error: {str(e)}",
                    confidence=0.0,
                    source="error",
                    uncertainty_factors=["provider_error"],
                )

            # Check if LLM wants to call tools
            if response.tool_calls and tools:
                for tc in response.tool_calls:
                    tool_calls_made += 1
                    result = await self._execute_tool_call(tc, tools, request_ctx)
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [tc.to_dict()],
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result),
                    })
                continue  # Let LLM process tool results

            # No tool calls — we have our final response
            content = response.content or "I'm not sure how to respond to that."

            # Compute confidence
            confidence = self._estimate_confidence(content, memory_ctx, tool_calls_made)
            source = "tool_verified" if tool_calls_made > 0 else "llm"

            envelope = ConfidenceEnvelope(
                response=content,
                confidence=confidence,
                source=source,
                tool_calls_made=tool_calls_made,
                uncertainty_factors=self._detect_uncertainty(content),
            )

            # Publish completion
            await self._bus.publish(
                EventType.REASONING_COMPLETE,
                {
                    "signal_id": signal.id,
                    "confidence": envelope.confidence,
                    "source": envelope.source,
                    "tool_calls": tool_calls_made,
                    "iterations": iterations,
                },
                source="reasoning.deliberate",
            )

            return envelope

        # Max iterations reached
        return ConfidenceEnvelope(
            response="I spent too many iterations trying to answer. Let me try a simpler approach — could you rephrase?",
            confidence=0.1,
            source="max_iterations",
            uncertainty_factors=["max_iterations_reached"],
            tool_calls_made=tool_calls_made,
        )

    # -- Prompt construction ------------------------------------------------

    def _build_messages(
        self,
        signal: Signal,
        memory_ctx: MemoryContext,
        history: list[dict[str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Build the message list for the LLM."""
        system_prompt = self._persona

        # Append memory context if available
        mem_section = memory_ctx.to_prompt_section()
        if mem_section:
            system_prompt += f"\n\n{mem_section}"

        system_prompt += (
            "\n\n## Guidelines\n"
            "- Be concise and helpful\n"
            "- If you're uncertain, say so explicitly\n"
            "- Use tools when available instead of guessing\n"
            "- Reference memory context when relevant\n"
        )

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        # Add conversation history
        if history:
            messages.extend(history)

        # Add current user message
        messages.append({"role": "user", "content": signal.content})

        return messages

    # -- Tool execution -----------------------------------------------------

    async def _execute_tool_call(
        self,
        tool_call: Any,
        tools: list[ToolDef],
        request_ctx: RequestContext | None,
    ) -> Any:
        """Execute a tool call with policy + idempotency enforcement."""
        tool_name = tool_call.name
        tool_args = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}

        # Find the tool
        tool = next((t for t in tools if t.name == tool_name), None)
        if not tool or not tool.handler:
            return {"error": f"Tool '{tool_name}' not found or has no handler"}

        # Policy enforcement (default-deny allowlist)
        if self._policy:
            pol = self._policy.check_tool_call(tool_name, tool_args, request_ctx=request_ctx)
            if not pol.allowed:
                await self._bus.publish(
                    EventType.ACTION_DENIED,
                    {"skill": tool_name, "reason": redact_secrets(pol.reason)[:200]},
                    source="reasoning.deliberate",
                )
                return {"error": f"Denied by policy: {pol.reason}", "details": pol.details}

            # DNS-rebinding resistant validation for fetch-like tools
            if tool_name == "fetch_url" and self._policy.config.deny_private_networks:
                url = str(tool_args.get("url", ""))
                if url:
                    url_pol = await self._policy.check_url_async(url)
                    if not url_pol.allowed:
                        if request_ctx:
                            request_ctx.increment_denials()
                        await self._bus.publish(
                            EventType.ACTION_DENIED,
                            {"skill": tool_name, "reason": redact_secrets(url_pol.reason)[:200]},
                            source="reasoning.deliberate",
                        )
                        return {"error": f"Denied by policy: {url_pol.reason}"}

        # Idempotency for mutating tools
        idem_key: str | None = None
        is_mutating = bool(self._policy and tool_name in self._policy.config.mutating_tools)
        if is_mutating and self._idempotency:
            idem_key = tool_args.get("idempotency_key")
            if not idem_key:
                safe_args = {k: v for k, v in tool_args.items() if k != "idempotency_key"}
                blob = json.dumps(safe_args, sort_keys=True, ensure_ascii=False)
                digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
                idem_key = f"{(request_ctx.request_id if request_ctx else 'req')}-{tool_name}-{digest}"
                tool_args["idempotency_key"] = idem_key

            hit = await self._idempotency.get(str(idem_key))
            if hit.hit and hit.result is not None:
                return {"idempotency": "hit", "key": idem_key, "result": hit.result}

        try:
            await self._bus.publish(
                EventType.ACTION_EXECUTING,
                {"skill": tool_name, "args": redact_secrets(str(tool_args)[:200])},
                source="reasoning.deliberate",
            )

            start = time.time()
            result = await tool.handler(**tool_args)
            _ = (time.time() - start) * 1000.0

            await self._bus.publish(
                EventType.ACTION_COMPLETE,
                {"skill": tool_name, "success": True},
                source="reasoning.deliberate",
            )

            if is_mutating and self._idempotency and idem_key:
                if not (isinstance(result, dict) and result.get("error")):
                    await self._idempotency.set(
                        str(idem_key),
                        result if isinstance(result, dict) else {"result": result},
                    )

            return result
        except Exception as e:
            await self._bus.publish(
                EventType.ACTION_COMPLETE,
                {"skill": tool_name, "success": False, "error": redact_secrets(str(e))[:200]},
                source="reasoning.deliberate",
            )
            return {"error": str(e)}

    # -- Confidence estimation ----------------------------------------------

    def _estimate_confidence(
        self,
        content: str,
        memory_ctx: MemoryContext,
        tool_calls: int,
    ) -> float:
        """Estimate confidence in the response."""
        base = 0.7

        # Tool-verified responses are higher confidence
        if tool_calls > 0:
            base = 0.85

        # Memory-backed responses
        if not memory_ctx.is_empty():
            base += 0.05

        # Uncertainty language lowers confidence
        uncertainty_words = ["maybe", "perhaps", "might", "not sure", "i think", "possibly"]
        lower = content.lower()
        for word in uncertainty_words:
            if word in lower:
                base -= 0.1
                break

        return round(max(0.1, min(1.0, base)), 2)

    def _detect_uncertainty(self, content: str) -> list[str]:
        """Detect uncertainty factors in the response."""
        factors = []
        lower = content.lower()
        if any(w in lower for w in ("maybe", "perhaps", "might", "possibly")):
            factors.append("hedging_language")
        if any(w in lower for w in ("not sure", "uncertain", "don't know")):
            factors.append("explicit_uncertainty")
        if "?" in content and content.count("?") > 1:
            factors.append("multiple_questions")
        return factors
