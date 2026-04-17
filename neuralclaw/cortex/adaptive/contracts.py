from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


SuggestionCategory = Literal[
    "approval",
    "self_correction",
    "intent_prediction",
    "project_context",
    "teaching",
    "general",
]
RiskLevel = Literal["low", "medium", "high"]
SuggestionState = Literal["pending", "reviewed", "accepted", "dismissed"]
ReviewState = Literal["pending", "probation", "approved", "rejected"]
AutonomyMode = Literal[
    "observe-only",
    "suggest-first",
    "auto-run-low-risk",
    "policy-driven-autonomous",
]


@dataclass(slots=True)
class AdaptiveSuggestion:
    suggestion_id: str
    category: SuggestionCategory
    title: str
    summary: str
    confidence: float
    rationale: str
    proposed_action: str
    risk_level: RiskLevel
    project_scope: str | None = None
    requires_approval: bool = False
    state: SuggestionState = "pending"
    score: float = 0.0
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LearningDiff:
    cycle_id: str
    behavior_change_summary: str
    probation_status: ReviewState = "pending"
    approval_status: ReviewState = "pending"
    impacted_artifacts: list[str] = field(default_factory=list)
    source_events: list[str] = field(default_factory=list)
    reviewer_note: str = ""
    last_error: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ChangeReceipt:
    receipt_id: str
    task_id: str
    operation_list: list[str] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    integrations_touched: list[str] = field(default_factory=list)
    memory_updated: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    rollback_token: str | None = None
    rollback_available: bool = False
    snapshot_id: str | None = None
    summary: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProjectContextProfile:
    project_id: str
    title: str
    paths: list[str]
    agents_md_summary: str
    active_skills: list[str] = field(default_factory=list)
    preferred_provider: str = "primary"
    preferred_model: str = "auto"
    recent_tasks: list[dict[str, Any]] = field(default_factory=list)
    last_known_open_work: list[str] = field(default_factory=list)
    connected_integrations: list[str] = field(default_factory=list)
    running_agents: list[str] = field(default_factory=list)
    autonomy_mode: str = "suggest-first"
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TeachingArtifact:
    entry_id: str
    title: str
    transcript: str
    template_candidate: str = ""
    workflow_candidate: dict[str, Any] = field(default_factory=dict)
    skill_candidate: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    promotion_state: ReviewState = "pending"
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProactiveRoutine:
    routine_id: str
    title: str
    trigger_pattern: str
    action_template: str
    risk_level: RiskLevel = "low"
    autonomy_class: AutonomyMode = "suggest-first"
    probation_status: ReviewState = "pending"
    success_count: int = 0
    failure_count: int = 0
    last_run_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ConfidenceContract:
    confidence: float | None = None
    source: str = ""
    uncertainty_factors: list[str] = field(default_factory=list)
    evidence_sources: list[str] = field(default_factory=list)
    escalation_recommendation: str = "none"
    retry_rationale: str = ""
    tool_calls_made: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
