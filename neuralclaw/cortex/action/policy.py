"""
Tool Policy Engine — Runtime enforcement of tool permissions.

Declarative policy model that controls what tools can do at runtime.
Loaded from the [policy] section in config.toml.

Every tool call is checked against the policy before execution.
Default: deny private networks, restrict filesystem to allowed roots.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from neuralclaw.config import PolicyConfig
from neuralclaw.cortex.action.network import validate_url, validate_url_with_dns


# ---------------------------------------------------------------------------
# Policy result
# ---------------------------------------------------------------------------

@dataclass
class PolicyResult:
    """Result of a policy check."""
    allowed: bool
    tool_name: str
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Request context (tracks per-request budgets)
# ---------------------------------------------------------------------------

@dataclass
class RequestContext:
    """Tracks per-request state for budget enforcement."""
    request_id: str = ""
    start_time: float = 0.0
    tool_calls: int = 0
    tool_denials: int = 0
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    memory_inject_chars: int = 0

    def __post_init__(self) -> None:
        if not self.start_time:
            self.start_time = time.time()

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    def increment_tool_calls(self) -> None:
        self.tool_calls += 1

    def increment_denials(self) -> None:
        self.tool_denials += 1

    def record_llm_usage(self, tokens_in: int = 0, tokens_out: int = 0) -> None:
        self.llm_calls += 1
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------

def resolve_and_validate_path(
    path: str | Path,
    allowed_roots: list[Path],
) -> tuple[Path, PolicyResult]:
    """
    Resolve a path and validate it against allowed roots.

    Resolves symlinks, checks against allowlist, blocks directory traversal.

    Returns:
        Tuple of (resolved_path, PolicyResult).
        If PolicyResult.allowed is False, the path must not be used.
    """
    try:
        resolved = Path(path).expanduser().resolve()
    except Exception as e:
        return Path(path), PolicyResult(
            allowed=False,
            tool_name="path_validation",
            reason=f"path_resolution_failed:{e}",
        )

    # Check if resolved path is under any allowed root
    for root in allowed_roots:
        try:
            # is_relative_to is Python 3.9+
            if resolved.is_relative_to(root):
                return resolved, PolicyResult(
                    allowed=True,
                    tool_name="path_validation",
                    details={"root": str(root)},
                )
        except (ValueError, TypeError):
            continue

    return resolved, PolicyResult(
        allowed=False,
        tool_name="path_validation",
        reason=f"path_outside_allowed_roots:{resolved}",
        details={
            "path": str(resolved),
            "allowed_roots": [str(r) for r in allowed_roots],
        },
    )


# ---------------------------------------------------------------------------
# Policy Engine
# ---------------------------------------------------------------------------

class PolicyEngine:
    """
    Runtime tool permission enforcement.

    Checks every tool call against the policy before execution.
    Integrates with the audit logger and neural bus for observability.
    """

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self._config = config or PolicyConfig()
        self._resolved_roots: list[Path] | None = None

    @property
    def config(self) -> PolicyConfig:
        return self._config

    def _get_roots(self) -> list[Path]:
        """Lazy-resolve filesystem roots."""
        if self._resolved_roots is None:
            roots: list[Path] = []
            for root in self._config.allowed_filesystem_roots:
                try:
                    p = Path(root).expanduser().resolve()
                    roots.append(p)
                except Exception:
                    continue
            self._resolved_roots = roots
        return self._resolved_roots

    def get_allowed_roots(self) -> list[Path]:
        """Public accessor for resolved allowed filesystem roots."""
        return self._get_roots()

    def check_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        request_ctx: RequestContext | None = None,
    ) -> PolicyResult:
        """
        Check whether a tool call is allowed by policy.

        Args:
            tool_name: Name of the tool being invoked.
            args: Arguments to the tool.
            request_ctx: Per-request context for budget tracking.

        Returns:
            PolicyResult indicating allow/deny.
        """
        # Default-deny allowlist for tools
        if self._config.allowed_tools and tool_name not in self._config.allowed_tools:
            if request_ctx:
                request_ctx.increment_denials()
            return PolicyResult(
                allowed=False,
                tool_name=tool_name,
                reason="tool_not_allowlisted",
                details={"allowed_tools": self._config.allowed_tools},
            )

        # Budget checks
        if request_ctx:
            # Tool call limit
            if request_ctx.tool_calls >= self._config.max_tool_calls_per_request:
                return PolicyResult(
                    allowed=False,
                    tool_name=tool_name,
                    reason=f"tool_call_limit_exceeded:{request_ctx.tool_calls}/{self._config.max_tool_calls_per_request}",
                )

            # Wall time limit
            if request_ctx.elapsed_seconds >= self._config.max_request_wall_seconds:
                return PolicyResult(
                    allowed=False,
                    tool_name=tool_name,
                    reason=f"request_timeout:{request_ctx.elapsed_seconds:.1f}s/{self._config.max_request_wall_seconds}s",
                )

        # Shell execution check
        if tool_name in ("code_exec", "shell_exec") and self._config.deny_shell_execution:
            return PolicyResult(
                allowed=False,
                tool_name=tool_name,
                reason="shell_execution_denied_by_policy",
            )

        # Path-based tools: validate filesystem access
        if tool_name in ("read_file", "write_file", "list_directory"):
            path_arg = args.get("path", ".")
            _, path_result = resolve_and_validate_path(path_arg, self._get_roots())
            if not path_result.allowed:
                return PolicyResult(
                    allowed=False,
                    tool_name=tool_name,
                    reason=path_result.reason,
                    details=path_result.details,
                )

        # Network tools: validate URL (static check here; DNS check should be done by caller via check_url_async)
        if tool_name in ("fetch_url",) and self._config.deny_private_networks:
            url = args.get("url", "")
            if url:
                static = validate_url(url)
                if not static.allowed:
                    if request_ctx:
                        request_ctx.increment_denials()
                    return PolicyResult(
                        allowed=False,
                        tool_name=tool_name,
                        reason=static.reason,
                    )

        # Track the call
        if request_ctx:
            request_ctx.increment_tool_calls()

        return PolicyResult(allowed=True, tool_name=tool_name)

    def check_path(self, path: str) -> PolicyResult:
        """Check if a filesystem path is allowed by policy."""
        _, result = resolve_and_validate_path(path, self._get_roots())
        return result

    def check_url(self, url: str) -> PolicyResult:
        """Check if a URL is allowed by policy."""
        result = validate_url(url)
        return PolicyResult(
            allowed=result.allowed,
            tool_name="url_validation",
            reason=result.reason,
        )

    async def check_url_async(self, url: str) -> PolicyResult:
        """Async URL validation with DNS resolution (recommended for fetch-like tools)."""
        result = await validate_url_with_dns(url)
        return PolicyResult(
            allowed=result.allowed,
            tool_name="url_validation",
            reason=result.reason,
            details={"resolved_ip": result.resolved_ip} if result.resolved_ip else {},
        )

    def check_request_budget(self, request_ctx: RequestContext) -> PolicyResult:
        """Check if the request is still within budget."""
        if request_ctx.tool_calls >= self._config.max_tool_calls_per_request:
            return PolicyResult(
                allowed=False,
                tool_name="budget_check",
                reason=f"tool_call_limit:{request_ctx.tool_calls}",
            )
        if request_ctx.elapsed_seconds >= self._config.max_request_wall_seconds:
            return PolicyResult(
                allowed=False,
                tool_name="budget_check",
                reason=f"wall_time_limit:{request_ctx.elapsed_seconds:.1f}s",
            )
        return PolicyResult(allowed=True, tool_name="budget_check")
