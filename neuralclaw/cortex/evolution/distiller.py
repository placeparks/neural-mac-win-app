"""
Experience Distiller — Episode → knowledge extraction pipeline.

At configurable intervals, the distiller reviews episodic memory
and extracts recurring patterns into:
- Semantic knowledge (facts, entities, relationships)
- Procedural memory (repeated workflow patterns)
- Behavioral adjustments (communication preferences)

"I notice the user always asks me to format code in Python"
becomes a permanent behavioral adjustment, not just a memory.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.cortex.memory.episodic import EpisodicMemory
from neuralclaw.cortex.memory.procedural import ProceduralMemory, ProcedureStep
from neuralclaw.cortex.memory.semantic import SemanticMemory


# ---------------------------------------------------------------------------
# Distillation report
# ---------------------------------------------------------------------------

@dataclass
class DistillationReport:
    """Report from an experience distillation cycle."""
    facts_extracted: int = 0
    procedures_learned: int = 0
    patterns_found: int = 0
    episodes_reviewed: int = 0
    elapsed_ms: float = 0.0


# ---------------------------------------------------------------------------
# Experience Distiller
# ---------------------------------------------------------------------------

class ExperienceDistiller:
    """
    Extracts patterns from episodic memory into semantic and procedural stores.

    Runs periodically (e.g., after every 50 conversations or daily).
    """

    def __init__(
        self,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        procedural: ProceduralMemory,
        bus: NeuralBus | None = None,
        distill_interval: int = 50,  # Every N interactions
    ) -> None:
        self._episodic = episodic
        self._semantic = semantic
        self._procedural = procedural
        self._bus = bus
        self._distill_interval = distill_interval
        self._interaction_count = 0
        self._last_distill: float = 0.0

    @property
    def should_distill(self) -> bool:
        return self._interaction_count >= self._distill_interval

    def tick(self) -> None:
        """Record an interaction."""
        self._interaction_count += 1

    async def distill(self) -> DistillationReport:
        """
        Run a full distillation cycle.

        1. Review recent episodic memories
        2. Extract recurring patterns
        3. Create semantic entities from patterns
        4. Detect workflow patterns → procedural memory
        """
        start = time.time()
        report = DistillationReport()

        # Get recent episodes
        assert self._episodic._db is not None
        rows = await self._episodic._db.execute_fetchall(
            """SELECT id, content, source, importance, access_count, created_at
               FROM episodes
               WHERE created_at > ?
               ORDER BY created_at DESC
               LIMIT 200""",
            (self._last_distill or (time.time() - 86400 * 7),),  # Last 7 days or since last distill
        )
        report.episodes_reviewed = len(rows)

        if not rows:
            self._interaction_count = 0
            return report

        # Extract patterns
        patterns = self._find_patterns(rows)
        report.patterns_found = len(patterns)

        # Convert patterns to semantic knowledge
        for pattern in patterns:
            if pattern["type"] == "entity":
                try:
                    await self._semantic.upsert_entity(
                        name=pattern["name"],
                        entity_type="distilled_knowledge",
                        properties={
                            "source": "distillation",
                            "frequency": pattern["frequency"],
                            "context": pattern.get("context", ""),
                        },
                        confidence=min(0.9, 0.5 + pattern["frequency"] * 0.1),
                    )
                    report.facts_extracted += 1
                except Exception:
                    pass

            elif pattern["type"] == "workflow":
                try:
                    steps = [
                        ProcedureStep(
                            action=s.get("action", "unknown"),
                            description=s.get("description", ""),
                        )
                        for s in pattern.get("steps", [])
                    ]
                    if steps:
                        await self._procedural.store_procedure(
                            name=pattern["name"],
                            description=pattern.get("context", "Learned workflow"),
                            trigger_patterns=pattern.get("triggers", []),
                            steps=steps,
                        )
                        report.procedures_learned += 1
                except Exception:
                    pass

        report.elapsed_ms = (time.time() - start) * 1000

        # Reset
        self._interaction_count = 0
        self._last_distill = time.time()

        # Publish
        if self._bus:
            await self._bus.publish(
                EventType.EXPERIENCE_DISTILLED,
                {
                    "episodes_reviewed": report.episodes_reviewed,
                    "facts_extracted": report.facts_extracted,
                    "procedures_learned": report.procedures_learned,
                    "patterns_found": report.patterns_found,
                    "elapsed_ms": round(report.elapsed_ms, 1),
                },
                source="evolution.distiller",
            )

        return report

    def _find_patterns(self, rows: list[tuple]) -> list[dict[str, Any]]:
        """
        Find recurring patterns in episodic memories.

        Uses simple frequency analysis of n-grams and co-occurring words.
        """
        patterns: list[dict[str, Any]] = []

        # Word frequency analysis
        word_freq: dict[str, int] = {}
        bigram_freq: dict[str, int] = {}

        # Sequence detection
        action_sequences: list[list[str]] = []
        current_sequence: list[str] = []

        for row in rows:
            content = row[1].lower()
            source = row[2]
            words = content.split()

            # Word frequency
            for word in words:
                if len(word) > 3:
                    word_freq[word] = word_freq.get(word, 0) + 1

            # Bigram frequency
            for i in range(len(words) - 1):
                bigram = f"{words[i]} {words[i+1]}"
                if len(bigram) > 7:
                    bigram_freq[bigram] = bigram_freq.get(bigram, 0) + 1

            # Track action sequences
            if "NeuralClaw:" in row[1] and any(
                keyword in content for keyword in ("created", "searched", "executed", "listed")
            ):
                current_sequence.append(content[:80])
            else:
                if len(current_sequence) >= 2:
                    action_sequences.append(current_sequence)
                current_sequence = []

        # Convert high-frequency words to entity patterns
        for word, freq in sorted(word_freq.items(), key=lambda x: -x[1])[:10]:
            if freq >= 3:
                patterns.append({
                    "type": "entity",
                    "name": word,
                    "frequency": freq,
                    "context": f"Frequently mentioned: {word}",
                })

        # Convert high-frequency bigrams
        for bigram, freq in sorted(bigram_freq.items(), key=lambda x: -x[1])[:5]:
            if freq >= 2:
                patterns.append({
                    "type": "entity",
                    "name": bigram,
                    "frequency": freq,
                    "context": f"Common phrase: {bigram}",
                })

        # Convert action sequences to workflow patterns
        for seq in action_sequences[:3]:
            patterns.append({
                "type": "workflow",
                "name": f"learned_workflow_{len(patterns)}",
                "steps": [
                    {"action": step.split()[0] if step.split() else "unknown",
                     "description": step}
                    for step in seq
                ],
                "triggers": [seq[0][:40]],
                "context": f"Workflow with {len(seq)} steps",
            })

        return patterns
