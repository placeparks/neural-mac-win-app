"""Adaptive control-plane primitives for proactive, teachable operation."""

from .control_plane import AdaptiveControlPlane
from .contracts import (
    AdaptiveSuggestion,
    ChangeReceipt,
    ConfidenceContract,
    LearningDiff,
    ProjectContextProfile,
    ProactiveRoutine,
    TeachingArtifact,
)
from .teaching import TeachingProcessor
from .sharing import DistilledSharingManager
from .multimodal import MultimodalRouter
from .compensating import CompensatingRollbackRegistry
from .intent import IntentPredictor
from .scheduler import RoutineScheduler
from .style import StyleAdapter
from .multimodal_processing import MultimodalProcessor

__all__ = [
    "AdaptiveControlPlane",
    "AdaptiveSuggestion",
    "ChangeReceipt",
    "ConfidenceContract",
    "TeachingProcessor",
    "DistilledSharingManager",
    "LearningDiff",
    "MultimodalRouter",
    "CompensatingRollbackRegistry",
    "IntentPredictor",
    "ProjectContextProfile",
    "ProactiveRoutine",
    "RoutineScheduler",
    "StyleAdapter",
    "TeachingArtifact",
    "MultimodalProcessor",
]
