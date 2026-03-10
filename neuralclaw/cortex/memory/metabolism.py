"""
Memory Metabolism — Biological memory lifecycle management.

Implements the three pillars of memory health:
- Consolidation: Merge related episodic memories → semantic knowledge
- Decay: Reduce importance of stale, low-access memories
- Strengthening: Boost frequently accessed, high-value memories

Runs on a configurable schedule (every N interactions or time-based).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.cortex.memory.episodic import EpisodicMemory
from neuralclaw.cortex.memory.semantic import SemanticMemory


# ---------------------------------------------------------------------------
# Metabolism stats
# ---------------------------------------------------------------------------

@dataclass
class MetabolismReport:
    """Report from a metabolism cycle."""
    consolidated: int = 0
    decayed: int = 0
    strengthened: int = 0
    pruned: int = 0
    elapsed_ms: float = 0.0
    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# Memory Metabolism Engine
# ---------------------------------------------------------------------------

class MemoryMetabolism:
    """
    Biological memory lifecycle engine.

    Call `run_cycle()` periodically (every N interactions or on schedule)
    to maintain memory health. This prevents unbounded growth while
    ensuring important memories get stronger over time.
    """

    def __init__(
        self,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        bus: NeuralBus | None = None,
        decay_rate: float = 0.02,
        consolidation_threshold: int = 3,
        prune_threshold: float = 0.05,
        cycle_interval: int = 100,  # Run every N interactions
    ) -> None:
        self._episodic = episodic
        self._semantic = semantic
        self._bus = bus
        self._decay_rate = decay_rate
        self._consolidation_threshold = consolidation_threshold
        self._prune_threshold = prune_threshold
        self._cycle_interval = cycle_interval

        self._interaction_count = 0
        self._last_cycle: float = 0.0

    @property
    def should_run(self) -> bool:
        """Check if a metabolism cycle should run."""
        return self._interaction_count >= self._cycle_interval

    def tick(self) -> None:
        """Record an interaction. Call after each message processed."""
        self._interaction_count += 1

    async def run_cycle(self) -> MetabolismReport:
        """Run a full metabolism cycle: consolidation → decay → strengthening → prune."""
        start = time.time()
        report = MetabolismReport(timestamp=start)

        # 1. Consolidation — frequent patterns → semantic knowledge
        report.consolidated = await self._consolidate()

        # 2. Decay — reduce importance of stale memories
        report.decayed = await self._decay()

        # 3. Strengthening — boost frequently accessed memories
        report.strengthened = await self._strengthen()

        # 4. Prune — remove memories below threshold
        report.pruned = await self._prune()

        report.elapsed_ms = (time.time() - start) * 1000

        # Reset counter
        self._interaction_count = 0
        self._last_cycle = time.time()

        # Publish report
        if self._bus:
            await self._bus.publish(
                EventType.MEMORY_CONSOLIDATED,
                {
                    "consolidated": report.consolidated,
                    "decayed": report.decayed,
                    "strengthened": report.strengthened,
                    "pruned": report.pruned,
                    "elapsed_ms": round(report.elapsed_ms, 1),
                },
                source="memory.metabolism",
            )

        return report

    async def _consolidate(self) -> int:
        """
        Consolidation: Extract entities from high-frequency episodic memories
        and store them as semantic knowledge.
        """
        assert self._episodic._db is not None
        consolidated = 0

        # Find frequently accessed episodes (access_count >= threshold)
        rows = await self._episodic._db.execute_fetchall(
            """SELECT id, content, source, importance, access_count
               FROM episodes
               WHERE access_count >= ?
               ORDER BY access_count DESC
               LIMIT 50""",
            (self._consolidation_threshold,),
        )

        for row in rows:
            content = row[1]
            importance = row[3]

            # Extract key phrases as potential entities
            # Simple extraction: sentences with high info density
            words = content.split()
            if len(words) >= 3:
                # Create a semantic entity from frequently accessed content
                entity_name = " ".join(words[:5]).strip(".,!?:;")
                try:
                    await self._semantic.upsert_entity(
                        name=entity_name,
                        entity_type="consolidated_memory",
                        properties={"source": "consolidation", "original_importance": importance},
                        confidence=min(0.9, importance + 0.1),
                    )
                    consolidated += 1
                except Exception:
                    pass

        return consolidated

    async def _decay(self) -> int:
        """
        Decay: Reduce importance of old, low-access memories.

        Uses exponential decay based on age and access frequency.
        """
        assert self._episodic._db is not None
        now = time.time()
        decayed = 0

        rows = await self._episodic._db.execute_fetchall(
            """SELECT id, importance, access_count, created_at
               FROM episodes
               WHERE importance > ?""",
            (self._prune_threshold,),
        )

        for row in rows:
            ep_id, importance, access_count, created_at = row
            age_days = (now - created_at) / 86400

            # Decay formula: importance *= e^(-decay_rate * age_days / (1 + access_count))
            # Higher access count = slower decay
            protection_factor = 1 + (access_count * 0.5)
            new_importance = importance * math.exp(
                -self._decay_rate * age_days / protection_factor
            )
            new_importance = max(self._prune_threshold * 0.5, new_importance)

            if new_importance < importance - 0.01:
                await self._episodic._db.execute(
                    "UPDATE episodes SET importance = ? WHERE id = ?",
                    (round(new_importance, 4), ep_id),
                )
                decayed += 1

        if decayed > 0:
            await self._episodic._db.commit()
            if self._bus:
                await self._bus.publish(
                    EventType.MEMORY_DECAYED,
                    {"decayed_count": decayed},
                    source="memory.metabolism",
                )

        return decayed

    async def _strengthen(self) -> int:
        """
        Strengthening: Boost importance of frequently accessed memories.
        """
        assert self._episodic._db is not None
        strengthened = 0

        # Find memories accessed more than average
        avg_row = await self._episodic._db.execute_fetchall(
            "SELECT AVG(access_count) FROM episodes",
        )
        avg_access = avg_row[0][0] if avg_row and avg_row[0][0] else 1.0

        rows = await self._episodic._db.execute_fetchall(
            """SELECT id, importance, access_count
               FROM episodes
               WHERE access_count > ?
               AND importance < 0.95""",
            (avg_access * 1.5,),
        )

        for row in rows:
            ep_id, importance, access_count = row
            boost = min(0.05, (access_count / (avg_access * 10)) * 0.03)
            new_importance = min(0.95, importance + boost)

            if new_importance > importance + 0.005:
                await self._episodic._db.execute(
                    "UPDATE episodes SET importance = ? WHERE id = ?",
                    (round(new_importance, 4), ep_id),
                )
                strengthened += 1

        if strengthened > 0:
            await self._episodic._db.commit()
            if self._bus:
                await self._bus.publish(
                    EventType.MEMORY_STRENGTHENED,
                    {"strengthened_count": strengthened},
                    source="memory.metabolism",
                )

        return strengthened

    async def _prune(self) -> int:
        """
        Prune: Remove memories with importance below threshold.
        Keeps the memory store lean and relevant.
        """
        assert self._episodic._db is not None

        cursor = await self._episodic._db.execute(
            "SELECT COUNT(*) FROM episodes WHERE importance < ?",
            (self._prune_threshold,),
        )
        row = await cursor.fetchone()
        count = row[0] if row else 0

        if count > 0:
            await self._episodic._db.execute(
                "DELETE FROM episodes WHERE importance < ?",
                (self._prune_threshold,),
            )
            await self._episodic._db.commit()

        return count
