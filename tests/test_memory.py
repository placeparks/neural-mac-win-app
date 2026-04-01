"""Tests for Memory Cortex."""
import time
import aiosqlite

import pytest
from neuralclaw.cortex.memory.episodic import EpisodicMemory, Episode
from neuralclaw.cortex.memory.semantic import SemanticMemory
from neuralclaw.cortex.memory.procedural import ProceduralMemory, ProcedureStep
from neuralclaw.cortex.memory.metabolism import MemoryMetabolism
from neuralclaw.cortex.memory.retrieval import MemoryRetriever
from neuralclaw.bus.neural_bus import NeuralBus


class TestEpisodicMemory:
    @pytest.fixture(autouse=True)
    async def setup(self, db_path):
        self.mem = EpisodicMemory(db_path)
        await self.mem.initialize()
        yield
        await self.mem.close()

    @pytest.mark.asyncio
    async def test_store_and_search(self):
        await self.mem.store("Python is a great programming language", source="test", importance=0.7)
        results = await self.mem.search("Python programming")
        assert len(results) > 0
        assert "Python" in results[0].episode.content

    @pytest.mark.asyncio
    async def test_store_returns_episode(self):
        ep = await self.mem.store("Test event", source="test")
        assert isinstance(ep, Episode)
        assert ep.id is not None

    @pytest.mark.asyncio
    async def test_search_empty_db(self):
        results = await self.mem.search("nonexistent topic")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_store_with_all_fields(self):
        ep = await self.mem.store(
            content="User felt happy about the result",
            source="conversation", author="testuser",
            importance=0.8, emotional_valence=0.9, tags=["feedback", "positive"],
        )
        assert isinstance(ep, Episode)

    @pytest.mark.asyncio
    async def test_get_recent(self):
        for i in range(5):
            await self.mem.store(f"Event number {i}", source="test")
        recent = await self.mem.get_recent(limit=3)
        assert len(recent) == 3

    @pytest.mark.asyncio
    async def test_importance_scoring(self):
        await self.mem.store("Very important", source="test", importance=0.95)
        await self.mem.store("Not important", source="test", importance=0.1)
        results = await self.mem.get_recent(limit=10)
        importances = [r.importance for r in results]
        assert max(importances) >= 0.9

    @pytest.mark.asyncio
    async def test_multiple_stores_searchable(self):
        await self.mem.store("The cat sat on the mat", source="test")
        await self.mem.store("A dog played in the park", source="test")
        cat_results = await self.mem.search("cat mat")
        assert len(cat_results) >= 1

    @pytest.mark.asyncio
    async def test_get_important(self):
        await self.mem.store("Low importance", source="test", importance=0.1)
        await self.mem.store("High importance", source="test", importance=0.95)
        important = await self.mem.get_important(min_importance=0.8)
        assert len(important) >= 1

    @pytest.mark.asyncio
    async def test_count(self):
        for i in range(3):
            await self.mem.store(f"Event {i}", source="test")
        count = await self.mem.count()
        assert count >= 3

    @pytest.mark.asyncio
    async def test_prune_old_episodes(self):
        old = await self.mem.store("Old event", source="test")
        await self.mem.store("Fresh event", source="test")
        assert self.mem._db is not None
        await self.mem._db.execute(
            "UPDATE episodes SET timestamp = ? WHERE id = ?",
            (time.time() - 40 * 86400, old.id),
        )
        await self.mem._db.commit()

        deleted = await self.mem.prune(keep_days=30)
        deleted_episode = await self.mem.get_by_id(old.id)
        count = await self.mem.count()

        assert deleted == 1
        assert deleted_episode is None
        assert count == 1


class TestSemanticMemory:
    @pytest.fixture(autouse=True)
    async def setup(self, db_path):
        self.mem = SemanticMemory(db_path)
        await self.mem.initialize()
        yield
        await self.mem.close()

    @pytest.mark.asyncio
    async def test_upsert_and_query_entity(self):
        await self.mem.upsert_entity("Python", "programming_language", {"paradigm": "multi"})
        entity = await self.mem.query_entity("Python")
        assert entity is not None
        assert entity.name == "Python"

    @pytest.mark.asyncio
    async def test_add_relationship(self):
        await self.mem.upsert_entity("Mirac", "person")
        await self.mem.upsert_entity("Cardify", "company")
        await self.mem.add_relationship("Mirac", "works_at", "Cardify", confidence=0.95)
        rels = await self.mem.get_relationships("Mirac")
        assert len(rels) > 0
        assert any(r.predicate == "works_at" for r in rels)

    @pytest.mark.asyncio
    async def test_search_entities(self):
        await self.mem.upsert_entity("NeuralClaw", "framework")
        results = await self.mem.search_entities("NeuralClaw")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_upsert_duplicate(self):
        await self.mem.upsert_entity("Python", "language")
        await self.mem.upsert_entity("Python", "language")
        entity = await self.mem.query_entity("Python")
        assert entity is not None

    @pytest.mark.asyncio
    async def test_empty_search(self):
        results = await self.mem.search_entities("nonexistent_xyz")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_get_all_triples(self):
        await self.mem.upsert_entity("A", "type_a")
        await self.mem.upsert_entity("B", "type_b")
        await self.mem.add_relationship("A", "related_to", "B", confidence=0.8)
        triples = await self.mem.get_all_triples()
        assert len(triples) >= 1

    @pytest.mark.asyncio
    async def test_initialize_migrates_legacy_namespace_schema(self, tmp_path):
        legacy_db = str(tmp_path / "semantic-legacy.db")
        async with aiosqlite.connect(legacy_db) as conn:
            await conn.executescript("""
                CREATE TABLE entities (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    entity_type TEXT NOT NULL DEFAULT 'unknown',
                    attributes_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE relationships (
                    id TEXT PRIMARY KEY,
                    from_entity_id TEXT NOT NULL,
                    to_entity_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.8,
                    source_event_id TEXT,
                    created_at REAL NOT NULL DEFAULT 0
                );
            """)
            await conn.commit()

        legacy = SemanticMemory(legacy_db)
        await legacy.initialize()
        await legacy.upsert_entity("Legacy", "concept")
        entity = await legacy.query_entity("Legacy")
        assert entity is not None
        await legacy.close()


class TestProceduralMemory:
    @pytest.fixture(autouse=True)
    async def setup(self, db_path):
        self.mem = ProceduralMemory(db_path)
        await self.mem.initialize()
        yield
        await self.mem.close()

    @pytest.mark.asyncio
    async def test_store_and_find(self):
        pid = await self.mem.store_procedure(
            name="web_research", description="Search and summarize",
            trigger_patterns=["research", "search for", "find info"],
            steps=[ProcedureStep(action="web_search", description="Search"), ProcedureStep(action="summarize", description="Summarize")],
        )
        assert pid is not None
        matches = await self.mem.find_matching("can you research AI agents?")
        assert len(matches) > 0

    @pytest.mark.asyncio
    async def test_record_outcome_success(self):
        pid = await self.mem.store_procedure(name="t", description="T", trigger_patterns=["t"], steps=[ProcedureStep(action="t", description="t")])
        await self.mem.record_outcome(pid, True)
        procs = await self.mem.get_all()
        assert any(p.success_count >= 1 for p in procs if p.id == pid)

    @pytest.mark.asyncio
    async def test_get_all(self):
        for i in range(3):
            await self.mem.store_procedure(name=f"p{i}", description=f"P{i}", trigger_patterns=[f"t{i}"], steps=[ProcedureStep(action=f"a{i}", description=f"s{i}")])
        assert len(await self.mem.get_all()) >= 3

    @pytest.mark.asyncio
    async def test_initialize_migrates_legacy_namespace_schema(self, tmp_path):
        legacy_db = str(tmp_path / "procedural-legacy.db")
        async with aiosqlite.connect(legacy_db) as conn:
            await conn.executescript("""
                CREATE TABLE procedures (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    trigger_patterns_json TEXT DEFAULT '[]',
                    steps_json TEXT DEFAULT '[]',
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    last_used REAL DEFAULT 0,
                    created_at REAL DEFAULT 0
                );
            """)
            await conn.commit()

        legacy = ProceduralMemory(legacy_db)
        await legacy.initialize()
        await legacy.store_procedure(
            name="legacy",
            description="Legacy procedure",
            trigger_patterns=["legacy"],
            steps=[ProcedureStep(action="check", description="Check legacy")],
        )
        procs = await legacy.get_all()
        assert any(proc.name == "legacy" for proc in procs)
        await legacy.close()


class TestMemoryMetabolism:
    @pytest.fixture(autouse=True)
    async def setup(self, db_path):
        self.ep = EpisodicMemory(db_path)
        self.sem = SemanticMemory(db_path)
        await self.ep.initialize()
        await self.sem.initialize()
        self.met = MemoryMetabolism(self.ep, self.sem, cycle_interval=1)
        yield
        await self.ep.close()
        await self.sem.close()

    @pytest.mark.asyncio
    async def test_should_run(self):
        self.met.tick()
        assert self.met.should_run

    @pytest.mark.asyncio
    async def test_run_cycle_empty(self):
        self.met.tick()
        r = await self.met.run_cycle()
        assert r is not None

    @pytest.mark.asyncio
    async def test_run_cycle_with_data(self):
        for i in range(10):
            await self.ep.store(f"Python topic {i}", source="test", importance=0.7)
        self.met.tick()
        r = await self.met.run_cycle()
        assert r is not None


class TestMemoryRetriever:
    @pytest.fixture(autouse=True)
    async def setup(self, db_path):
        self.bus = NeuralBus()
        self.ep = EpisodicMemory(db_path)
        self.sem = SemanticMemory(db_path)
        await self.ep.initialize()
        await self.sem.initialize()
        self.ret = MemoryRetriever(self.ep, self.sem, self.bus)
        yield
        await self.ep.close()
        await self.sem.close()

    @pytest.mark.asyncio
    async def test_retrieve_empty(self):
        ctx = await self.ret.retrieve("hello")
        assert ctx is not None
        assert isinstance(ctx.episodes, list)

    @pytest.mark.asyncio
    async def test_retrieve_with_data(self):
        await self.ep.store("Python is a great language", source="test")
        await self.sem.upsert_entity("Python", "programming_language")
        ctx = await self.ret.retrieve("Tell me about Python")
        assert ctx is not None
