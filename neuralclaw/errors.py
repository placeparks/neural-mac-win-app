"""
Project-level exception hierarchy and structured error codes.

The exception hierarchy provides catchable failures.  The ``ErrorCode``
enum and ``StructuredError`` dataclass provide machine-readable error
classification that gives LLMs actionable information (recoverable?
what to try instead?) rather than opaque free-form strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class NeuralClawError(Exception):
    """Base class for application-specific failures."""


class ConfigurationError(NeuralClawError):
    """Config is missing, malformed, or has invalid values."""


class ProviderError(NeuralClawError):
    """LLM provider is unreachable, unauthorized, or returned bad data."""


class MemoryStoreError(NeuralClawError):
    """Memory store initialization, read, or write failure."""


class ChannelError(NeuralClawError):
    """Channel adapter failed to connect or send."""


class SecurityError(NeuralClawError):
    """Security policy violation or safety block."""


class SkillError(NeuralClawError):
    """Skill registration, loading, or execution failure."""


class CircuitOpenError(ProviderError):
    """Provider circuit is open and requests should fail fast."""


# ---------------------------------------------------------------------------
# Structured error codes
# ---------------------------------------------------------------------------

class ErrorCode(Enum):
    """Machine-readable error categories across the framework."""

    # Tool errors
    TOOL_NOT_FOUND = "tool_not_found"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_INVALID_PARAMS = "tool_invalid_params"

    # Policy errors
    POLICY_TOOL_NOT_ALLOWED = "policy_tool_not_allowed"
    POLICY_BUDGET_EXCEEDED = "policy_budget_exceeded"
    POLICY_PATH_DENIED = "policy_path_denied"
    POLICY_NETWORK_DENIED = "policy_network_denied"
    POLICY_SHELL_DENIED = "policy_shell_denied"

    # Sandbox errors
    SANDBOX_TIMEOUT = "sandbox_timeout"
    SANDBOX_PATH_DENIED = "sandbox_path_denied"
    SANDBOX_CRASH = "sandbox_crash"

    # Provider errors
    PROVIDER_UNREACHABLE = "provider_unreachable"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_CIRCUIT_OPEN = "provider_circuit_open"

    # Delegation errors
    DELEGATION_DEPTH_EXCEEDED = "delegation_depth_exceeded"
    DELEGATION_CONCURRENCY_EXCEEDED = "delegation_concurrency_exceeded"
    DELEGATION_AGENT_NOT_FOUND = "delegation_agent_not_found"
    DELEGATION_TIMEOUT = "delegation_timeout"


@dataclass
class StructuredError:
    """
    A structured error that gives the LLM actionable information.

    The ``recoverable`` flag tells the agent whether retrying or adjusting
    is worthwhile.  The ``suggestion`` field tells it *what* to try instead.
    """

    code: ErrorCode
    message: str
    recoverable: bool
    suggestion: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_tool_result(self) -> dict[str, Any]:
        """Format for consumption by the LLM in a tool-call result."""
        d: dict[str, Any] = {
            "error": self.message,
            "error_code": self.code.value,
            "recoverable": self.recoverable,
        }
        if self.suggestion:
            d["suggestion"] = self.suggestion
        if self.details:
            d["details"] = self.details
        return d

