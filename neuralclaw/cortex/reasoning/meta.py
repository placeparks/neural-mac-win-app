"""
Meta-Cognitive Reasoning — Layer 4: The Evolution Path.

Periodically analyzes agent performance, identifies failure patterns,
detects capability gaps, and triggers self-improvement through the
Evolution Cortex (synthesizer + calibrator).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from neuralclaw.bus.neural_bus import NeuralBus, EventType


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PerformanceRecord:
    """Tracks success/failure for a task category."""
    category: str
    total: int = 0
    successes: int = 0
    failures: int = 0
    avg_confidence: float = 0.0
    last_failure_reason: str = ""

    @property
    def success_rate(self) -> float:
        return self.successes / self.total if self.total > 0 else 0.0


@dataclass
class CapabilityGap:
    """An identified gap in the agent's capabilities."""
    category: str
    failure_rate: float
    occurrence_count: int
    common_errors: list[str]
    suggested_skill: str
    severity: float  # 0.0 - 1.0


@dataclass
class MetaCognitiveReport:
    """Report from a meta-cognitive analysis cycle."""
    timestamp: float = field(default_factory=time.time)
    total_interactions: int = 0
    overall_success_rate: float = 0.0
    performance_by_category: list[PerformanceRecord] = field(default_factory=list)
    capability_gaps: list[CapabilityGap] = field(default_factory=list)
    behavioral_insights: list[str] = field(default_factory=list)
    actions_taken: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Meta-Cognitive Reasoner
# ---------------------------------------------------------------------------

class MetaCognitive:
    """
    Layer 4 reasoning — the agent periodically reflects on its own performance.

    Asks:
    - What tasks am I failing at?
    - What patterns do I see in user corrections?
    - What skills am I missing?
    - How can I improve?

    Feeds insights into the Evolution Cortex for automatic improvement.
    """

    ANALYSIS_INTERVAL = 25   # Run every N interactions
    FAILURE_THRESHOLD = 0.4  # Flag categories with > 40% failure rate
    MIN_SAMPLES = 3          # Need at least N samples to analyze a category

    def __init__(self, bus: NeuralBus | None = None) -> None:
        self._bus = bus
        self._interaction_count = 0
        self._performance: dict[str, PerformanceRecord] = {}
        self._correction_history: list[dict[str, Any]] = []
        self._reports: list[MetaCognitiveReport] = []

    @property
    def should_analyze(self) -> bool:
        return self._interaction_count >= self.ANALYSIS_INTERVAL

    @property
    def latest_report(self) -> MetaCognitiveReport | None:
        return self._reports[-1] if self._reports else None

    def tick(self) -> None:
        """Count an interaction."""
        self._interaction_count += 1

    def record_interaction(
        self,
        category: str,
        success: bool,
        confidence: float = 0.5,
        error: str = "",
    ) -> None:
        """
        Record the outcome of an interaction for performance tracking.

        Args:
            category: Task category (e.g. "calendar", "code", "research").
            success: Whether the task was completed successfully.
            confidence: Agent's confidence in the response.
            error: Error description if failed.
        """
        if category not in self._performance:
            self._performance[category] = PerformanceRecord(category=category)

        record = self._performance[category]
        record.total += 1
        if success:
            record.successes += 1
        else:
            record.failures += 1
            record.last_failure_reason = error

        # Running average of confidence
        n = record.total
        record.avg_confidence = (
            record.avg_confidence * (n - 1) + confidence
        ) / n

        self.tick()

    def record_correction(self, original: str, correction: str, category: str = "general") -> None:
        """Record a user correction for behavioral analysis."""
        self._correction_history.append({
            "original": original,
            "correction": correction,
            "category": category,
            "timestamp": time.time(),
        })

    async def analyze(self) -> MetaCognitiveReport:
        """
        Run a full meta-cognitive analysis cycle.

        Analyzes performance by category, identifies capability gaps,
        extracts behavioral insights, and generates recommendations.
        """
        self._interaction_count = 0
        report = MetaCognitiveReport()

        # Overall statistics
        total = sum(r.total for r in self._performance.values())
        successes = sum(r.successes for r in self._performance.values())
        report.total_interactions = total
        report.overall_success_rate = successes / total if total > 0 else 1.0

        # Performance by category
        report.performance_by_category = list(self._performance.values())

        # Identify capability gaps
        report.capability_gaps = self._identify_gaps()

        # Extract behavioral insights from corrections
        report.behavioral_insights = self._extract_insights()

        # Log actions
        for gap in report.capability_gaps:
            report.actions_taken.append(
                f"Flagged capability gap: {gap.category} "
                f"(failure rate: {gap.failure_rate:.0%}, {gap.occurrence_count} occurrences)"
            )

        self._reports.append(report)

        # Emit event
        if self._bus:
            self._bus.emit(EventType.EXPERIENCE_DISTILLED, {
                "meta_cognitive": True,
                "gaps_found": len(report.capability_gaps),
                "overall_success_rate": report.overall_success_rate,
                "insights": len(report.behavioral_insights),
            })

        return report

    def _identify_gaps(self) -> list[CapabilityGap]:
        """Find categories where the agent is underperforming."""
        gaps = []
        for record in self._performance.values():
            if record.total < self.MIN_SAMPLES:
                continue

            failure_rate = 1.0 - record.success_rate
            if failure_rate >= self.FAILURE_THRESHOLD:
                # Collect common errors for this category
                errors = [record.last_failure_reason] if record.last_failure_reason else []

                gaps.append(CapabilityGap(
                    category=record.category,
                    failure_rate=failure_rate,
                    occurrence_count=record.failures,
                    common_errors=errors,
                    suggested_skill=f"{record.category}_specialist",
                    severity=min(1.0, failure_rate * (record.failures / max(record.total, 1))),
                ))

        # Sort by severity (worst gaps first)
        gaps.sort(key=lambda g: g.severity, reverse=True)
        return gaps

    def _extract_insights(self) -> list[str]:
        """Extract behavioral insights from correction history."""
        insights = []
        recent = self._correction_history[-20:]  # Last 20 corrections

        if not recent:
            return ["No corrections recorded — agent behavior appears aligned."]

        # Count correction categories
        categories: dict[str, int] = {}
        for c in recent:
            cat = c.get("category", "general")
            categories[cat] = categories.get(cat, 0) + 1

        for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
            if count >= 2:
                insights.append(
                    f"Received {count} corrections in '{cat}' — "
                    f"behavioral calibration recommended."
                )

        # Check correction frequency trend
        if len(recent) >= 5:
            recent_timestamps = [c["timestamp"] for c in recent[-5:]]
            time_span = recent_timestamps[-1] - recent_timestamps[0]
            if time_span > 0 and time_span < 300:  # 5 corrections in < 5 minutes
                insights.append(
                    "High correction frequency detected — "
                    "agent may be misaligned with user expectations."
                )

        return insights or ["Agent performance is within normal parameters."]

    def get_performance_summary(self) -> dict[str, Any]:
        """Get a quick summary of agent performance."""
        total = sum(r.total for r in self._performance.values())
        successes = sum(r.successes for r in self._performance.values())

        return {
            "total_interactions": total,
            "success_rate": successes / total if total > 0 else 1.0,
            "categories_tracked": len(self._performance),
            "active_gaps": len(self._identify_gaps()),
            "corrections_recorded": len(self._correction_history),
            "analyses_completed": len(self._reports),
        }
