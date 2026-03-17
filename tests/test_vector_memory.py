"""Tests for vector memory and its memory-cortex integrations."""

import pytest

from neuralclaw.bus.neural_bus import NeuralBus
from neuralclaw.cortex.memory.episodic import EpisodicMemory
from neuralclaw.cortex.memory.metabolism import MemoryMetabolism
from neuralclaw.cortex.memory.retrieval import MemoryRetriever
from neuralclaw.cortex.memory.semantic import SemanticMemory
from neuralclaw.cortex.memory.vector import VectorMemory


class TestVectorMemory:
    @pytest.fixture(autouse=True)
    async def setup(self, db_path):
        self.bus = NeuralBus()
        self.mem = VectorMemory(db_path, embedding_provider="fallback", dimension=64, bus=self.bus)
        await self.mem.initialize()
        yield
        await self.mem.close()

    @pytest.mark.asyncio
    async def test_embed_and_similarity_search(self):
        first_id = await self.mem.embed_and_store(
            "python async sqlite memory retrieval",
            "ep1",
        )
        second_id = await self.mem.embed_and_store(
            "gardening soil and tomato plants",
            "ep2",
        )

        assert first_id
        assert second_id

        results = await self.mem.similarity_search("python sqlite retrieval", top_k=2)

        assert len(results) == 2
        assert results[0].ref_id == "ep1"
        assert results[0].score >= results[1].score

    @pytest.mark.asyncio
    async def test_delete_by_ref(self):
        await self.mem.embed_and_store("vector content for deletion", "ep1")
        await self.mem.delete_by_ref("ep1")

        rows = await self.mem._db.execute_fetchall(  # type: ignore[union-attr]
            "SELECT COUNT(*) FROM vec_embeddings WHERE ref_id = ?",
            ("ep1",),
        )
        assert rows[0][0] == 0


class TestVectorMemoryIntegration:
    @pytest.fixture(autouse=True)
    async def setup(self, db_path):
        self.bus = NeuralBus()
        self.vec = VectorMemory(db_path, embedding_provider="fallback", dimension=64, bus=self.bus)
        await self.vec.initialize()
        self.ep = EpisodicMemory(db_path, vector_memory=self.vec, bus=self.bus)
        self.sem = SemanticMemory(db_path)
        await self.ep.initialize()
        await self.sem.initialize()
        yield
        await self.ep.close()
        await self.sem.close()
        await self.vec.close()

    @pytest.mark.asyncio
    async def test_episodic_store_indexes_vector(self):
        episode = await self.ep.store("python callback orchestration", source="test")

        rows = await self.vec._db.execute_fetchall(  # type: ignore[union-attr]
            "SELECT COUNT(*) FROM vec_embeddings WHERE ref_id = ?",
            (episode.id,),
        )
        assert rows[0][0] == 1

    @pytest.mark.asyncio
    async def test_retriever_uses_vector_memory(self):
        await self.ep.store("python callback orchestration", source="test")
        retriever = MemoryRetriever(
            self.ep,
            self.sem,
            self.bus,
            vector_memory=self.vec,
            vector_top_k=5,
        )

        ctx = await retriever.retrieve("python orchestration", include_recent=False)

        assert any("callback orchestration" in episode.content for episode in ctx.episodes)

    @pytest.mark.asyncio
    async def test_metabolism_prune_deletes_vector_rows(self):
        episode = await self.ep.store("obsolete low-priority note", source="test", importance=0.01)
        metabolism = MemoryMetabolism(
            self.ep,
            self.sem,
            self.bus,
            vector_memory=self.vec,
            cycle_interval=1,
            prune_threshold=0.05,
        )

        metabolism.tick()
        report = await metabolism.run_cycle()

        assert report.pruned >= 1
        results = await self.vec.similarity_search("obsolete low-priority", top_k=5)
        assert all(result.ref_id != episode.id for result in results)
