"""
Project-level exception hierarchy for guided, catchable failures.
"""

from __future__ import annotations


class NeuralClawError(Exception):
    """Base class for application-specific failures."""


class ConfigurationError(NeuralClawError):
    """Config is missing, malformed, or has invalid values."""


class ProviderError(NeuralClawError):
    """LLM provider is unreachable, unauthorized, or returned bad data."""


class MemoryError(NeuralClawError):
    """Memory store initialization, read, or write failure."""


class ChannelError(NeuralClawError):
    """Channel adapter failed to connect or send."""


class SecurityError(NeuralClawError):
    """Security policy violation or safety block."""


class SkillError(NeuralClawError):
    """Skill registration, loading, or execution failure."""


class CircuitOpenError(ProviderError):
    """Provider circuit is open and requests should fail fast."""

