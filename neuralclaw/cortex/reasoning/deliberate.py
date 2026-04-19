"""
Deliberate — Standard LLM-powered reasoning with tool use and confidence signaling.

This is Layer 2 of the reasoning cortex — the standard path for requests
that need the language model. Builds a prompt from memory context + tools,
runs a tool-use loop, and wraps every response in a ConfidenceEnvelope.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time

logger = logging.getLogger("neuralclaw.cortex.reasoning.deliberate")
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.cortex.action.audit import AuditLogger
from neuralclaw.cortex.action.idempotency import IdempotencyStore
from neuralclaw.cortex.action.param_validator import validate_tool_params
from neuralclaw.cortex.action.policy import DenialContext, PolicyEngine, RequestContext
from neuralclaw.cortex.reasoning.checkpoint import CheckpointStore
from neuralclaw.cortex.memory.retrieval import MemoryContext
from neuralclaw.cortex.perception.intake import Signal, sanitize_content
from neuralclaw.errors import ErrorCode, StructuredError
from neuralclaw.security.redaction import redact_secrets


def _error_detail(exc: Exception) -> str:
    """Return a stable, non-empty error detail for logs, events, and users."""
    return str(exc).strip() or repr(exc).strip() or type(exc).__name__


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
    evidence_sources: list[str] = field(default_factory=list)
    escalation_recommendation: str = "none"
    retry_rationale: str = ""
    media: list[dict[str, Any]] = field(default_factory=list)  # e.g. [{"type": "image", "data": b"...", "mime": "image/png"}]

    def to_dict(self) -> dict[str, Any]:
        return {
            "response": self.response,
            "confidence": self.confidence,
            "source": self.source,
            "alternatives_considered": self.alternatives_considered,
            "uncertainty_factors": self.uncertainty_factors,
            "tool_calls_made": self.tool_calls_made,
            "evidence_sources": self.evidence_sources,
            "escalation_recommendation": self.escalation_recommendation,
            "retry_rationale": self.retry_rationale,
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
    TOOL_RECOVERY_RETRY_THRESHOLD = 2
    TOOL_FALLBACK_THRESHOLD = 4

    def __init__(
        self,
        bus: NeuralBus,
        persona: str = "You are NeuralClaw, a helpful AI assistant.",
        policy: PolicyEngine | None = None,
        idempotency: IdempotencyStore | None = None,
        audit: AuditLogger | None = None,
        checkpoint: CheckpointStore | None = None,
    ) -> None:
        self._bus = bus
        self._persona = persona
        self._provider: Any = None  # Set via set_provider()
        self._role_router: Any = None  # Optional role-based model router
        self._policy = policy
        self._idempotency = idempotency
        self._audit = audit
        self._checkpoint = checkpoint

    def set_provider(self, provider: Any) -> None:
        """Set the LLM provider for reasoning."""
        self._provider = provider

    def set_role_router(self, role_router: Any) -> None:
        """Set the role-based model router for smart model dispatch."""
        self._role_router = role_router

    async def _complete(
        self,
        role: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> Any:
        """Route completion through role router if available, else use default provider.

        Roles: primary (user-facing), fast (tool loops), micro (classification).
        """
        if self._role_router:
            return await self._role_router.complete(
                role=role,
                messages=messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        return await self._provider.complete(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def reason(
        self,
        signal: Signal,
        memory_ctx: MemoryContext,
        tools: list[ToolDef] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        extra_system_sections: list[str] | None = None,
        dry_run: bool = False,
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
        messages = self._build_messages(
            signal,
            memory_ctx,
            conversation_history,
            extra_system_sections=extra_system_sections,
        )

        # Build tool defs for the provider
        tool_defs = [t.to_openai_format() for t in (tools or [])] if tools else None

        tool_calls_made = 0
        iterations = 0
        captured_media: list[dict[str, Any]] = []
        consecutive_errors = 0
        corrective_retry_used = False
        recovery_strategy_prompted = False
        signal_context = getattr(signal, "context", {}) or {}
        request_ctx = RequestContext(
            request_id=signal.id,
            user_id=str(signal_context.get("user_id", signal.author_id) or signal.author_id),
            channel_id=signal.channel_id,
            platform=signal.channel_type.name.lower(),
        )
        denial_ctx = DenialContext()

        while iterations < self.MAX_ITERATIONS:
            # Inject denial guidance if tools were previously denied
            if denial_ctx.has_denials:
                guidance = denial_ctx.to_system_guidance()
                if guidance and (not messages or messages[-1].get("content") != guidance):
                    messages.append({"role": "system", "content": guidance})
            iterations += 1

            # Role dispatch: first iteration uses primary (user-facing reasoning),
            # subsequent iterations (tool-result processing) use fast model
            role = "primary" if iterations == 1 else "fast"

            try:
                response = await self._complete(
                    role=role,
                    messages=messages,
                    tools=tool_defs,
                )
            except Exception as e:
                # Some httpx/aiohttp exceptions stringify to "" — fall back to
                # the type name and repr so the user sees an actionable message
                # instead of a bare "I encountered an error:".
                detail = _error_detail(e)
                logger.exception("DeliberateReasoner._complete failed: %s", detail)
                return ConfidenceEnvelope(
                    response=f"I encountered an error: {detail}",
                    confidence=0.0,
                    source="error",
                    uncertainty_factors=["provider_error"],
                )

            # Check if LLM wants to call tools
            if response.tool_calls and tools:
                if self._policy and not self._policy.config.parallel_tool_execution:
                    tool_results = [
                        await self._execute_tool_call(tc, tools, request_ctx, dry_run=dry_run)
                        for tc in response.tool_calls
                    ]
                else:
                    tool_results = await asyncio.gather(*[
                        self._execute_tool_call(tc, tools, request_ctx, dry_run=dry_run)
                        for tc in response.tool_calls
                    ], return_exceptions=True)
                tool_calls_made += len(response.tool_calls)

                # Track consecutive errors — bail early if tools keep failing
                all_errors = True
                for tc, result in zip(response.tool_calls, tool_results):
                    if isinstance(result, Exception):
                        result = {"error": _error_detail(result)}

                    # Capture screenshot media for sending to user AND for LLM vision
                    screenshot_b64_for_vision: str | None = None
                    if isinstance(result, dict) and result.get("screenshot_b64"):
                        import base64 as _b64
                        screenshot_b64_for_vision = result["screenshot_b64"]
                        try:
                            img_bytes = _b64.b64decode(screenshot_b64_for_vision)
                            captured_media.append({
                                "type": "image",
                                "data": img_bytes,
                                "mime": "image/png",
                                "width": result.get("width", 0),
                                "height": result.get("height", 0),
                            })
                        except Exception:
                            pass
                        # Remove raw b64 from JSON result (will be sent as vision content instead)
                        result = {
                            k: v for k, v in result.items() if k != "screenshot_b64"
                        }
                        result["screenshot_captured"] = True

                    result_str = json.dumps(result)
                    if "error" not in result_str.lower()[:100]:
                        all_errors = False

                    # Track policy denials for guardrail feedback loop
                    if isinstance(result, dict) and result.get("error_code", "").startswith("policy_"):
                        denial_ctx.record(tc.name, result.get("error", "policy_denied"))
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [tc.to_dict()],
                    })

                    # For screenshots, send the image as vision content so LLM can analyze it
                    if screenshot_b64_for_vision:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": [
                                {"type": "text", "text": result_str},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{screenshot_b64_for_vision}",
                                        "detail": "low",  # low-res to save tokens
                                    },
                                },
                            ],
                        })
                    else:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result_str,
                        })

                if all_errors:
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0

                if (
                    consecutive_errors >= self.TOOL_RECOVERY_RETRY_THRESHOLD
                    and not recovery_strategy_prompted
                ):
                    recovery_strategy_prompted = True
                    messages.append({
                        "role": "user",
                        "content": (
                            "The recent tool attempts mostly failed. Change strategy now: "
                            "use fewer tool calls, prefer a different tool if one exists, "
                            "narrow the task, or answer directly from the evidence already gathered. "
                            "Do not repeat the same failing action."
                        ),
                    })
                    continue

                # If repeated rounds of nothing but errors continue, force a text-only response
                if consecutive_errors >= self.TOOL_FALLBACK_THRESHOLD:
                    try:
                        fallback = await self._complete(
                            role="primary",  # Final user-facing answer
                            messages=messages + [{
                                "role": "user",
                                "content": (
                                    "The tools you tried are failing or denied. "
                                    "Please answer the user directly with what you know, "
                                    "explain what you tried and why it didn't work, "
                                    "and suggest what they could do instead."
                                ),
                            }],
                            tools=None,  # No tools — force text response
                        )
                        content = fallback.content or "I tried several approaches but they all failed. Could you try a different request?"
                    except Exception:
                        content = "I tried several tools but they kept failing. Could you try rephrasing your request?"
                    return ConfidenceEnvelope(
                        response=content,
                        confidence=0.3,
                        source="tool_fallback",
                        uncertainty_factors=["tools_failed_repeatedly"],
                        tool_calls_made=tool_calls_made,
                        evidence_sources=["tool_execution", "fallback_synthesis"],
                        escalation_recommendation="ask_user_or_change_strategy",
                        retry_rationale="Repeated tool failures forced a text-only fallback.",
                        media=captured_media,
                    )

                # Checkpoint after each tool-use iteration for crash recovery
                if self._checkpoint:
                    try:
                        await self._checkpoint.save(
                            session_id=signal.id,
                            step_index=iterations,
                            messages=messages,
                            tool_calls_made=tool_calls_made,
                        )
                    except Exception:
                        pass  # Checkpoint failure must not break reasoning

                continue  # Let LLM process tool results

            # No tool calls — we have our final response
            content = response.content or "I'm not sure how to respond to that."

            if (
                tools
                and not corrective_retry_used
                and self._should_retry_for_actionable_request(signal=signal, content=content)
            ):
                corrective_retry_used = True
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": (
                        "Do not stop at describing a plan or asking for permission when the task is already requested "
                        "and your available tools can execute it. Use the appropriate tools now if they apply. "
                        "If execution is blocked, explain the exact blocker and the clearest next action."
                    ),
                })
                continue

            # Compute confidence
            confidence = self._estimate_confidence(content, memory_ctx, tool_calls_made)
            source = "tool_verified" if tool_calls_made > 0 else "llm"

            envelope = ConfidenceEnvelope(
                response=content,
                confidence=confidence,
                source=source,
                tool_calls_made=tool_calls_made,
                uncertainty_factors=self._detect_uncertainty(content),
                evidence_sources=self._build_evidence_sources(memory_ctx, tool_calls_made, source),
                escalation_recommendation=self._recommend_escalation(confidence, content, tool_calls_made),
                retry_rationale=(
                    "Corrective retry was used because the initial answer stopped at planning."
                    if corrective_retry_used else ""
                ),
                media=captured_media,
            )

            # Clear checkpoint on successful completion
            if self._checkpoint:
                try:
                    await self._checkpoint.clear_session(signal.id)
                except Exception:
                    pass

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

        # Max iterations reached — still give a useful answer instead of a useless cop-out
        try:
            fallback = await self._complete(
                role="primary",  # Final user-facing synthesis
                messages=messages + [{
                    "role": "user",
                    "content": (
                        "You've been working on this for a while. "
                        "Please give the user a final answer now based on everything you've gathered so far. "
                        "Summarize what you found, what worked, what didn't, and any next steps."
                    ),
                }],
                tools=None,  # Force text-only
            )
            content = fallback.content or ""
        except Exception:
            content = ""

        if not content:
            content = "I've been working on this but hit my limit. Here's what I tried so far — could you break this into smaller steps?"

        return ConfidenceEnvelope(
            response=content,
            confidence=0.2,
            source="max_iterations",
            uncertainty_factors=["max_iterations_reached"],
            tool_calls_made=tool_calls_made,
            evidence_sources=["tool_execution", "partial_synthesis"] if tool_calls_made else ["partial_synthesis"],
            escalation_recommendation="review_or_split_request",
            retry_rationale="The bounded reasoning loop exhausted its iteration limit.",
            media=captured_media,
        )

    async def reason_stream(
        self,
        signal: Signal,
        memory_ctx: MemoryContext,
        tools: list[ToolDef] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        extra_system_sections: list[str] | None = None,
    ) -> AsyncIterator[str]:
        """Yield response chunks for simple streaming delivery."""
        if not self._provider:
            for chunk in self._chunk_text(
                "I'm not configured with an LLM provider yet. Run `neuralclaw init` to set up."
            ):
                yield chunk
            return

        # Tool-use loops are not stream-safe yet. Fall back to buffered reasoning.
        if tools:
            envelope = await self.reason(
                signal=signal,
                memory_ctx=memory_ctx,
                tools=tools,
                conversation_history=conversation_history,
                extra_system_sections=extra_system_sections,
            )
            for chunk in self._chunk_text(envelope.response):
                yield chunk
            return

        await self._bus.publish(
            EventType.REASONING_STARTED,
            {"signal_id": signal.id, "path": "deliberative_stream", "tools_available": 0},
            source="reasoning.deliberate",
        )

        messages = self._build_messages(
            signal,
            memory_ctx,
            conversation_history,
            extra_system_sections=extra_system_sections,
        )

        try:
            # Streaming uses primary model (user-facing response)
            if self._role_router:
                stream = self._role_router.stream_complete(
                    role="primary", messages=messages, tools=None,
                )
            else:
                stream = self._provider.stream_complete(messages=messages, tools=None)
            async for chunk in stream:
                if chunk:
                    yield chunk
        except Exception as exc:
            detail = _error_detail(exc)
            await self._bus.publish(
                EventType.ERROR,
                {
                    "component": "deliberative_reasoner",
                    "operation": "reason_stream",
                    "error": detail,
                },
                source="reasoning.deliberate",
            )
            for chunk in self._chunk_text(f"I encountered an error: {detail}"):
                yield chunk

    def wrap_streamed_response(
        self,
        content: str,
        memory_ctx: MemoryContext,
        tool_calls_made: int = 0,
    ) -> ConfidenceEnvelope:
        """Wrap a streamed final response in the normal confidence envelope."""
        confidence = self._estimate_confidence(content, memory_ctx, tool_calls_made)
        source = "tool_verified" if tool_calls_made > 0 else "llm"
        return ConfidenceEnvelope(
            response=content,
            confidence=confidence,
            source=source,
            tool_calls_made=tool_calls_made,
            uncertainty_factors=self._detect_uncertainty(content),
        )

    # -- Prompt construction ------------------------------------------------

    def _build_messages(
        self,
        signal: Signal,
        memory_ctx: MemoryContext,
        history: list[dict[str, str]] | None = None,
        extra_system_sections: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Build the message list for the LLM."""
        system_prompt = self._persona

        # Append memory context if available
        mem_section = memory_ctx.to_prompt_section()
        if mem_section:
            system_prompt += f"\n\n{mem_section}"

        if extra_system_sections:
            for section in extra_system_sections:
                if section:
                    system_prompt += f"\n\n{section}"

        # Only append minimal guidelines if the persona doesn't already contain them
        if "## Guidelines" not in system_prompt and "## Your Capabilities" not in system_prompt:
            system_prompt += (
                "\n\n## Guidelines\n"
                "- Answer the user's actual request directly before adding extra commentary\n"
                "- Use tools when they materially improve accuracy or let you execute the task\n"
                "- If a tool fails, adapt your plan instead of repeating the same failing action\n"
                "- Reference memory context only when it is genuinely relevant\n"
                "- State uncertainty explicitly and separate facts from inference\n"
                "- Keep the response specific, grounded, and actionable\n"
            )

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        # Add conversation history (sanitize content to prevent injection via history)
        if history:
            for msg in history:
                if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                    sanitized, _, _ = sanitize_content(msg["content"], max_chars=8000)
                    messages.append({**msg, "content": sanitized})
                else:
                    messages.append(msg)

        # Add current user message
        messages.append({"role": "user", "content": signal.content})

        return messages

    def _chunk_text(self, text: str, chunk_size: int = 24) -> list[str]:
        if not text:
            return []
        parts: list[str] = []
        cursor = 0
        while cursor < len(text):
            end = min(len(text), cursor + chunk_size)
            if end < len(text):
                split = text.rfind(" ", cursor, end)
                if split > cursor:
                    end = split + 1
            parts.append(text[cursor:end])
            cursor = end
        return parts

    # -- Tool execution -----------------------------------------------------

    async def _execute_tool_call(
        self,
        tool_call: Any,
        tools: list[ToolDef],
        request_ctx: RequestContext | None,
        dry_run: bool = False,
    ) -> Any:
        """Execute a tool call with policy + idempotency enforcement."""
        tool_name = tool_call.name
        tool_args = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
        args_preview = json.dumps(tool_args, ensure_ascii=False, sort_keys=True, default=str)

        # Find the tool
        tool = next((t for t in tools if t.name == tool_name), None)
        if not tool or not tool.handler:
            await self._log_audit(
                tool_name=tool_name,
                args_preview=args_preview,
                result_preview="tool_not_found",
                success=False,
                execution_time_ms=0.0,
                request_ctx=request_ctx,
                allowed=False,
                denied_reason="tool_not_found",
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
                await self._log_audit(
                    tool_name=tool_name,
                    args_preview=args_preview,
                    result_preview=param_err.message,
                    success=False,
                    execution_time_ms=0.0,
                    request_ctx=request_ctx,
                    allowed=False,
                    denied_reason=f"invalid_params:{param_err.message}",
                )
                return param_err.to_tool_result()

        # Policy enforcement (default-deny allowlist)
        if self._policy:
            pol = self._policy.check_tool_call(tool_name, tool_args, request_ctx=request_ctx)
            if not pol.allowed:
                await self._bus.publish(
                    EventType.ACTION_DENIED,
                    {
                        "signal_id": request_ctx.request_id if request_ctx else "",
                        "user_id": request_ctx.user_id if request_ctx else "",
                        "channel_id": request_ctx.channel_id if request_ctx else "",
                        "platform": request_ctx.platform if request_ctx else "",
                        "skill": tool_name,
                        "reason": redact_secrets(pol.reason)[:200],
                        "args": redact_secrets(args_preview[:200]),
                    },
                    source="reasoning.deliberate",
                )
                await self._log_audit(
                    tool_name=tool_name,
                    args_preview=args_preview,
                    result_preview=f"Denied by policy: {pol.reason}",
                    success=False,
                    execution_time_ms=0.0,
                    request_ctx=request_ctx,
                    allowed=False,
                    denied_reason=pol.reason,
                )
                return StructuredError(
                    code=pol.error_code or ErrorCode.POLICY_TOOL_NOT_ALLOWED,
                    message=f"Denied by policy: {pol.reason}",
                    recoverable=False,
                    suggestion="This tool is blocked by security policy. Try a different approach or answer from your knowledge.",
                    details=pol.details,
                ).to_tool_result()

            # DNS-rebinding resistant validation for fetch-like tools
            if tool_name in ("fetch_url", "clone_repo", "api_request") and self._policy.config.deny_private_networks:
                url = str(tool_args.get("url", ""))
                if url:
                    url_pol = await self._policy.check_url_async(url)
                    if not url_pol.allowed:
                        if request_ctx:
                            request_ctx.increment_denials()
                        await self._bus.publish(
                            EventType.ACTION_DENIED,
                            {
                                "signal_id": request_ctx.request_id if request_ctx else "",
                                "user_id": request_ctx.user_id if request_ctx else "",
                                "channel_id": request_ctx.channel_id if request_ctx else "",
                                "platform": request_ctx.platform if request_ctx else "",
                                "skill": tool_name,
                                "reason": redact_secrets(url_pol.reason)[:200],
                                "args": redact_secrets(args_preview[:200]),
                            },
                            source="reasoning.deliberate",
                        )
                        await self._log_audit(
                            tool_name=tool_name,
                            args_preview=args_preview,
                            result_preview=f"Denied by policy: {url_pol.reason}",
                            success=False,
                            execution_time_ms=0.0,
                            request_ctx=request_ctx,
                            allowed=False,
                            denied_reason=url_pol.reason,
                        )
                        return StructuredError(
                            code=ErrorCode.POLICY_NETWORK_DENIED,
                            message=f"Denied by policy: {url_pol.reason}",
                            recoverable=False,
                            suggestion="This URL is blocked by network policy. Try a different URL or answer from your knowledge.",
                        ).to_tool_result()

        # Dry-run: return a preview instead of executing
        is_mutating = bool(self._policy and tool_name in self._policy.config.mutating_tools)
        if dry_run:
            return {
                "dry_run": True,
                "tool": tool_name,
                "args": tool_args,
                "preview": f"Would execute {tool_name} with {len(tool_args)} parameters",
                "risk": "mutating" if is_mutating else "read-only",
            }

        # Idempotency for mutating tools
        idem_key: str | None = None
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
                {
                    "signal_id": request_ctx.request_id if request_ctx else "",
                    "user_id": request_ctx.user_id if request_ctx else "",
                    "channel_id": request_ctx.channel_id if request_ctx else "",
                    "platform": request_ctx.platform if request_ctx else "",
                    "skill": tool_name,
                    "args": redact_secrets(str(tool_args)[:200]),
                },
                source="reasoning.deliberate",
            )

            start = time.time()
            result = await asyncio.wait_for(
                tool.handler(**tool_args),
                timeout=30.0,
            )
            elapsed_ms = (time.time() - start) * 1000.0

            await self._bus.publish(
                EventType.ACTION_COMPLETE,
                {
                    "signal_id": request_ctx.request_id if request_ctx else "",
                    "user_id": request_ctx.user_id if request_ctx else "",
                    "channel_id": request_ctx.channel_id if request_ctx else "",
                    "platform": request_ctx.platform if request_ctx else "",
                    "skill": tool_name,
                    "success": True,
                    "result_preview": redact_secrets(str(result)[:200]),
                },
                source="reasoning.deliberate",
            )
            await self._log_audit(
                tool_name=tool_name,
                args_preview=args_preview,
                result_preview=str(result),
                success=True,
                execution_time_ms=elapsed_ms,
                request_ctx=request_ctx,
            )

            if is_mutating and self._idempotency and idem_key:
                if not (isinstance(result, dict) and result.get("error")):
                    await self._idempotency.set(
                        str(idem_key),
                        result if isinstance(result, dict) else {"result": result},
                    )

            return result
        except Exception as e:
            detail = _error_detail(e)
            elapsed_ms = 0.0
            await self._bus.publish(
                EventType.ACTION_COMPLETE,
                {
                    "signal_id": request_ctx.request_id if request_ctx else "",
                    "user_id": request_ctx.user_id if request_ctx else "",
                    "channel_id": request_ctx.channel_id if request_ctx else "",
                    "platform": request_ctx.platform if request_ctx else "",
                    "skill": tool_name,
                    "success": False,
                    "error": redact_secrets(detail)[:200],
                },
                source="reasoning.deliberate",
            )
            await self._log_audit(
                tool_name=tool_name,
                args_preview=args_preview,
                result_preview=detail,
                success=False,
                execution_time_ms=elapsed_ms,
                request_ctx=request_ctx,
            )
            return StructuredError(
                code=ErrorCode.TOOL_EXECUTION_FAILED,
                message=detail,
                recoverable=True,
                suggestion="The tool crashed. Try with different arguments or use an alternative tool.",
            ).to_tool_result()

    async def _log_audit(
        self,
        *,
        tool_name: str,
        args_preview: str,
        result_preview: str,
        success: bool,
        execution_time_ms: float,
        request_ctx: RequestContext | None,
        allowed: bool = True,
        denied_reason: str = "",
    ) -> None:
        if not self._audit:
            return
        normalized_preview = result_preview
        if not success:
            normalized_preview = result_preview.strip() or denied_reason.strip() or "unknown_error"
        await self._audit.log_action(
            skill_name=tool_name,
            action="execute",
            args_preview=args_preview,
            result_preview=normalized_preview,
            success=success,
            execution_time_ms=execution_time_ms,
            request_id=request_ctx.request_id if request_ctx else "",
            user_id=request_ctx.user_id if request_ctx else "",
            channel_id=request_ctx.channel_id if request_ctx else "",
            platform=request_ctx.platform if request_ctx else "",
            allowed=allowed,
            denied_reason=denied_reason,
            signal_id=request_ctx.request_id if request_ctx else "",
            correlation_id=request_ctx.request_id if request_ctx else "",
        )

    # -- Confidence estimation ----------------------------------------------

    def _should_retry_for_actionable_request(self, signal: Signal, content: str) -> bool:
        request = str(getattr(signal, "content", "") or "").strip().lower()
        reply = (content or "").strip().lower()
        if not request or not reply:
            return False
        if not self._looks_actionable_request(request):
            return False
        return self._is_action_deferring_reply(reply)

    def _looks_actionable_request(self, request: str) -> bool:
        action_phrases = (
            "create",
            "build",
            "write",
            "fix",
            "change",
            "update",
            "enable",
            "disable",
            "set ",
            "run",
            "check",
            "inspect",
            "look at",
            "debug",
            "investigate",
            "search",
            "find",
            "test",
            "verify",
            "install",
            "configure",
        )
        return any(phrase in request for phrase in action_phrases)

    def _is_action_deferring_reply(self, reply: str) -> bool:
        deferring_markers = (
            "would you like me to",
            "i can do that for you",
            "i can help you",
            "i'll create",
            "i will create",
            "i'll first",
            "i will first",
            "here's the plan",
            "here is the plan",
            "i have a plan",
            "my plan is",
            "the next step would be",
            "you should",
            "you can run",
            "you can enable",
        )
        if any(marker in reply for marker in deferring_markers):
            return True
        return "plan" in reply and "execute" not in reply and "executed" not in reply

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

    def _build_evidence_sources(
        self,
        memory_ctx: MemoryContext,
        tool_calls: int,
        source: str,
    ) -> list[str]:
        evidence: list[str] = []
        if not memory_ctx.is_empty():
            evidence.append("memory")
        if tool_calls > 0:
            evidence.append("tool_execution")
        if source:
            evidence.append(source)
        return evidence or ["llm"]

    def _recommend_escalation(self, confidence: float, content: str, tool_calls: int) -> str:
        if confidence < 0.45:
            return "ask_user_for_clarification"
        if tool_calls == 0 and self._is_action_deferring_reply((content or "").lower()):
            return "execute_or_explain_blocker"
        if confidence < 0.7:
            return "operator_review_recommended"
        return "none"
