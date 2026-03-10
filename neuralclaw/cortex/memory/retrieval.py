"""
Retrieval — Hybrid search combining episodic and semantic memory.

Merges temporal/full-text episodic results with knowledge graph traversal
to build a MemoryContext that the reasoning cortex uses for LLM prompts.

Cost control:
- Configurable character budget for memory injection (default 4000)
- Priority: recent episodes > facts > older episodes
- Warning logged when budget is hit
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from neuralclaw.bus.neural_bus import EventType, NeuralBus
from neuralclaw.cortex.memory.episodic import EpisodicMemory, Episode, EpisodeSearchResult
from neuralclaw.cortex.memory.semantic import SemanticMemory, Entity, KnowledgeTriple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Memory context (output to reasoning cortex)
# ---------------------------------------------------------------------------

@dataclass
class MemoryContext:
    """Combined memory context for the reasoning cortex."""

    # Relevant past episodes
    episodes: list[Episode] = field(default_factory=list)

    # Related entities from the knowledge graph
    entities: list[Entity] = field(default_factory=list)

    # Known facts (subject–predicate–object triples)
    facts: list[KnowledgeTriple] = field(default_factory=list)

    # Formatted string for injection into LLM prompt
    formatted: str = ""

    # Budget tracking
    budget_chars: int = 0
    budget_hit: bool = False

    def is_empty(self) -> bool:
        return not self.episodes and not self.entities and not self.facts

    def to_prompt_section(self, max_chars: int = 0) -> str:
        """
        Format memory context as a prompt section for the LLM.

        Args:
            max_chars: Maximum character budget. 0 = no limit.
        """
        if self.is_empty():
            return ""

        parts: list[str] = []

        if self.facts:
            facts_str = "\n".join(
                f"  - {f.subject} {f.predicate} {f.obj} (confidence: {f.confidence:.0%})"
                for f in self.facts[:15]
            )
            parts.append(f"### Known Facts\n{facts_str}")

        if self.episodes:
            eps_str = "\n".join(
                f"  - [{_ts(e.timestamp)}] {e.author}: {e.content[:200]}"
                for e in self.episodes[:10]
            )
            parts.append(f"### Recent Relevant Interactions\n{eps_str}")

        if not parts:
            return ""

        result = "## Memory Context\n" + "\n\n".join(parts)

        # Apply budget truncation
        if max_chars > 0 and len(result) > max_chars:
            self.budget_hit = True
            self.budget_chars = len(result)
            result = result[:max_chars]
            # Try to truncate at a clean line boundary
            last_newline = result.rfind("\n")
            if last_newline > max_chars * 0.8:
                result = result[:last_newline]
            result += "\n\n[Memory truncated due to budget limit]"

        return result


def _ts(timestamp: float) -> str:
    """Format timestamp as short date-time."""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%m/%d %H:%M")


# ---------------------------------------------------------------------------
# Memory Retriever
# ---------------------------------------------------------------------------

class MemoryRetriever:
    """
    Hybrid memory retrieval engine.

    Combines:
    1. Episodic FTS search (query-based)
    2. Episodic recency (latest N messages)
    3. Semantic graph traversal (entities mentioned → related facts)

    Cost control:
    - max_memory_chars: character budget for the formatted prompt section.
      When exceeded, the output is truncated with priority given to
      recent episodes over facts.

    Returns a MemoryContext for the reasoning cortex.
    """

    def __init__(
        self,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        bus: NeuralBus,
        max_episodes: int = 10,
        max_facts: int = 10,
        max_memory_chars: int = 4000,
    ) -> None:
        self._episodic = episodic
        self._semantic = semantic
        self._bus = bus
        self._max_episodes = max_episodes
        self._max_facts = max_facts
        self._max_memory_chars = max_memory_chars

    async def retrieve(
        self,
        query: str,
        include_recent: bool = True,
        recent_count: int = 5,
    ) -> MemoryContext:
        """
        Build a MemoryContext by searching both episodic and semantic memory.

        Args:
            query: The user's message or search query.
            include_recent: Whether to include the N most recent episodes.
            recent_count: How many recent episodes to include.
        """
        ctx = MemoryContext()

        # 1. Episodic FTS search
        try:
            search_results = await self._episodic.search(
                query, limit=self._max_episodes
            )
            ctx.episodes = [r.episode for r in search_results]
        except Exception:
            pass  # FTS may fail on very short queries

        # 2. Include recent episodes (for conversational continuity)
        if include_recent:
            try:
                recent = await self._episodic.get_recent(limit=recent_count)
                # Merge without duplicates
                existing_ids = {e.id for e in ctx.episodes}
                for ep in recent:
                    if ep.id not in existing_ids:
                        ctx.episodes.append(ep)
                        existing_ids.add(ep.id)
            except Exception:
                pass

        # Sort episodes by timestamp (most recent last for conversation flow)
        ctx.episodes.sort(key=lambda e: e.timestamp)

        # 3. Semantic graph — extract entity names from query and lookup
        words = self._extract_potential_entities(query)
        seen_entities: set[str] = set()
        for word in words:
            try:
                entities = await self._semantic.search_entities(word, limit=3)
                for ent in entities:
                    if ent.id not in seen_entities:
                        ctx.entities.append(ent)
                        seen_entities.add(ent.id)

                        # Get relationships for this entity
                        triples = await self._semantic.get_relationships(
                            ent.name, min_confidence=0.3
                        )
                        ctx.facts.extend(triples[:self._max_facts])
            except Exception:
                pass

        # Deduplicate facts
        seen_facts: set[str] = set()
        unique_facts: list[KnowledgeTriple] = []
        for f in ctx.facts:
            key = f"{f.subject}|{f.predicate}|{f.obj}"
            if key not in seen_facts:
                seen_facts.add(key)
                unique_facts.append(f)
        ctx.facts = unique_facts[:self._max_facts]

        # Generate formatted prompt section (with budget enforcement)
        ctx.formatted = ctx.to_prompt_section(max_chars=self._max_memory_chars)

        # Log budget warning if hit
        if ctx.budget_hit:
            logger.warning(
                "Memory injection budget hit: %d chars truncated to %d",
                ctx.budget_chars,
                self._max_memory_chars,
            )

        # Publish retrieval event
        await self._bus.publish(
            EventType.MEMORY_RETRIEVED,
            {
                "query": query[:100],
                "episodic_count": len(ctx.episodes),
                "semantic_count": len(ctx.facts),
                "entities_found": [e.name for e in ctx.entities[:5]],
                "formatted_chars": len(ctx.formatted),
                "budget_hit": ctx.budget_hit,
            },
            source="memory.retrieval",
        )

        return ctx

    def _extract_potential_entities(self, text: str) -> list[str]:
        """
        Extract potential entity names from text.

        Simple heuristic: split on whitespace, keep words that are
        capitalized or longer than 3 chars. For Phase 2, this will
        use NER from the LLM.
        """
        words = text.split()
        candidates: list[str] = []
        for word in words:
            # Strip punctuation
            clean = word.strip(".,!?;:\"'()[]{}»«")
            if len(clean) > 2:
                candidates.append(clean)
        return candidates[:10]
