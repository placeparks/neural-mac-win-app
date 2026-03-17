"""Tests for persistent user identity."""

import pytest

from neuralclaw.cortex.memory.episodic import EpisodicMemory
from neuralclaw.cortex.memory.identity import UserIdentityStore
from neuralclaw.cortex.memory.semantic import SemanticMemory


class TestUserIdentityStore:
    @pytest.fixture(autouse=True)
    async def setup(self, db_path):
        self.ep = EpisodicMemory(db_path)
        self.sem = SemanticMemory(db_path)
        await self.ep.initialize()
        await self.sem.initialize()
        self.store = UserIdentityStore(db_path, episodic=self.ep, semantic=self.sem)
        await self.store.initialize()
        yield
        await self.store.close()
        await self.ep.close()
        await self.sem.close()

    @pytest.mark.asyncio
    async def test_get_or_create_reuses_canonical_user(self):
        first = await self.store.get_or_create("telegram", "123", "Alice")
        second = await self.store.get_or_create("telegram", "123", "Alice")

        assert first.user_id == second.user_id
        assert second.message_count >= 2
        assert second.platform_aliases["telegram"] == "123"

    @pytest.mark.asyncio
    async def test_update_merges_dicts_and_lists(self):
        model = await self.store.get_or_create("telegram", "123", "Alice")

        await self.store.update(
            model.user_id,
            {
                "preferences": {"tone": "concise"},
                "active_projects": ["neuralclaw"],
                "notes": "Prefers direct answers.",
            },
        )

        refreshed = await self.store.get(model.user_id)
        assert refreshed is not None
        assert refreshed.preferences["tone"] == "concise"
        assert "neuralclaw" in refreshed.active_projects
        assert refreshed.notes == "Prefers direct answers."

    @pytest.mark.asyncio
    async def test_merge_aliases_links_second_platform(self):
        model = await self.store.get_or_create("telegram", "123", "Alice")

        await self.store.merge_aliases(model.user_id, "discord", "456")
        alias = await self.store.get_or_create("discord", "456", "Alice D")

        assert alias.user_id == model.user_id
        assert alias.platform_aliases["discord"] == "456"

    @pytest.mark.asyncio
    async def test_to_prompt_section_synthesizes_topics_and_domains(self):
        model = await self.store.get_or_create("telegram", "123", "Alice")
        await self.ep.store(
            "Alice: I need help with python trading automation and neuralclaw memory",
            source="conversation",
            author="Alice",
            tags=[f"user_id:{model.user_id}"],
        )
        await self.ep.store(
            "Alice: python debugging for trading agents",
            source="conversation",
            author="Alice",
            tags=[f"user_id:{model.user_id}"],
        )
        await self.sem.upsert_entity("python", "language")
        await self.sem.upsert_entity("trading", "domain")

        section = await self.store.to_prompt_section(model.user_id)

        assert "Who I'm Talking To" in section
        assert "Alice" in section
        assert "python" in section.lower()
        assert "language" in section.lower() or "domain" in section.lower()
