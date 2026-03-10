"""
Capabilities — Capability-based permission model and verification pipeline.

Every skill declares what it needs. Every action is verified against its grants.
Principle of least privilege: a weather skill cannot read your emails.

Pipeline: SkillRequest → CapabilityCheck → Sandbox → Execute → OutputSanitize → Result
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from neuralclaw.bus.neural_bus import EventType, NeuralBus


# ---------------------------------------------------------------------------
# Capability model
# ---------------------------------------------------------------------------

class Capability(Enum):
    """Available capability types."""
    FILESYSTEM_READ = auto()
    FILESYSTEM_WRITE = auto()
    NETWORK_HTTP = auto()
    NETWORK_WEBSOCKET = auto()
    SHELL_EXECUTE = auto()
    MESSAGING_READ = auto()
    MESSAGING_WRITE = auto()
    CALENDAR_READ = auto()
    CALENDAR_WRITE = auto()
    MEMORY_READ = auto()
    MEMORY_WRITE = auto()


@dataclass
class CapabilityGrant:
    """A scoped permission grant for a skill."""
    capability: Capability
    scope: str = "*"  # e.g. "~/Documents/*" for filesystem, "api.example.com" for network
    granted: bool = True


@dataclass
class CapabilityRequest:
    """A skill's request for a specific capability."""
    skill_name: str
    capability: Capability
    scope: str = "*"
    reason: str = ""


@dataclass
class VerificationResult:
    """Result of capability verification."""
    allowed: bool
    skill_name: str
    requested: list[CapabilityRequest]
    denied: list[CapabilityRequest]
    reason: str = ""


# ---------------------------------------------------------------------------
# Capability Verifier
# ---------------------------------------------------------------------------

class CapabilityVerifier:
    """
    Verifies that skills have the required capabilities before execution.

    Default policy: DENY ALL. Skills must declare capabilities in their
    manifest, and the verifier checks each request against the grants.
    """

    def __init__(
        self,
        bus: NeuralBus | None = None,
        allow_shell: bool = False,
    ) -> None:
        self._bus = bus
        self._allow_shell = allow_shell

        # Default grants for built-in skills
        self._grants: dict[str, list[CapabilityGrant]] = {
            "web_search": [
                CapabilityGrant(Capability.NETWORK_HTTP, scope="*"),
            ],
            "file_ops": [
                CapabilityGrant(Capability.FILESYSTEM_READ, scope="*"),
                CapabilityGrant(Capability.FILESYSTEM_WRITE, scope="*"),
            ],
            "code_exec": [
                CapabilityGrant(Capability.SHELL_EXECUTE, scope="python"),
            ],
            "calendar": [
                CapabilityGrant(Capability.CALENDAR_READ, scope="*"),
                CapabilityGrant(Capability.CALENDAR_WRITE, scope="*"),
                CapabilityGrant(Capability.MEMORY_READ, scope="*"),
                CapabilityGrant(Capability.MEMORY_WRITE, scope="*"),
            ],
        }

    def register_grants(self, skill_name: str, grants: list[CapabilityGrant]) -> None:
        """Register capability grants for a skill."""
        self._grants[skill_name] = grants

    async def verify(self, requests: list[CapabilityRequest]) -> VerificationResult:
        """Verify a list of capability requests."""
        denied: list[CapabilityRequest] = []
        skill_name = requests[0].skill_name if requests else "unknown"

        for req in requests:
            # Shell execution requires explicit config opt-in
            if req.capability == Capability.SHELL_EXECUTE and not self._allow_shell:
                denied.append(req)
                continue

            # Check if skill has the grant
            grants = self._grants.get(req.skill_name, [])
            has_grant = any(
                g.capability == req.capability and g.granted
                for g in grants
            )

            if not has_grant:
                denied.append(req)

        allowed = len(denied) == 0

        result = VerificationResult(
            allowed=allowed,
            skill_name=skill_name,
            requested=requests,
            denied=denied,
            reason="" if allowed else f"Denied capabilities: {[d.capability.name for d in denied]}",
        )

        # Publish event
        if self._bus:
            event_type = EventType.ACTION_REQUESTED if allowed else EventType.ACTION_DENIED
            await self._bus.publish(
                event_type,
                {
                    "skill": skill_name,
                    "allowed": allowed,
                    "capability": [r.capability.name for r in requests],
                    "denied": [d.capability.name for d in denied],
                    "reason": result.reason,
                },
                source="action.capabilities",
            )

        return result
