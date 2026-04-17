import pytest

from neuralclaw.skills.builtins import agent_orchestration as skill


class FakeGateway:
    def __init__(self) -> None:
        self._shared_bridge = object()
        self.created = []
        self.updated = []
        self.spawned_ids = []
        self.delegated = []
        self.auto_routed = []
        self.consensus = []
        self.pipeline = []
        self.shared_tasks = []
        self.definitions = [
            {"agent_id": "a1", "name": "researcher", "provider": "venice", "model": "llama", "capabilities": ["research"]},
            {"agent_id": "a2", "name": "builder", "provider": "venice", "model": "llama", "capabilities": ["code"]},
        ]
        self.running = [{"name": "researcher"}]

    async def _dashboard_list_definitions(self):
        return list(self.definitions)

    def _dashboard_get_running_agents(self):
        return list(self.running)

    async def _dashboard_create_definition(self, payload):
        self.created.append(payload)
        return {"ok": True, "agent_id": "a3"}

    async def _dashboard_update_definition(self, agent_id, payload):
        self.updated.append((agent_id, payload))
        return {"ok": True}

    async def _dashboard_spawn_definition(self, agent_id):
        self.spawned_ids.append(agent_id)
        if agent_id == "a2":
            self.running.append({"name": "builder"})
        return {"ok": True, "name": agent_id}

    async def _dashboard_despawn_definition(self, agent_id):
        return {"ok": True, "agent_id": agent_id}

    async def _dashboard_create_shared_task(self, agent_names):
        self.shared_tasks.append(agent_names)
        return {"ok": True, "task_id": "shared-1"}

    async def _dashboard_delegate_task(self, payload):
        self.delegated.append(payload)
        return {"ok": True, "result": "manual"}

    async def _dashboard_auto_route_task(self, payload):
        self.auto_routed.append(payload)
        return {"ok": True, "result": "auto-route", "routed_to": ["researcher"]}

    async def _dashboard_seek_consensus(self, payload):
        self.consensus.append(payload)
        return {"ok": True, "result": "consensus"}

    async def _dashboard_pipeline_task(self, payload):
        self.pipeline.append(payload)
        return {"ok": True, "final_result": "pipeline"}


@pytest.fixture(autouse=True)
def reset_binding():
    previous = skill._gateway_ref
    skill.set_gateway(None)
    yield
    skill.set_gateway(previous)


@pytest.mark.asyncio
async def test_create_agent_definition_can_spawn_immediately():
    gateway = FakeGateway()
    skill.set_gateway(gateway)

    result = await skill.create_agent_definition(
        name="reviewer",
        model="gpt-4.1",
        provider="venice",
        capabilities=["review", "qa"],
        spawn_now=True,
    )

    assert result["ok"] is True
    assert gateway.created[0]["capabilities"] == ["review", "qa"]
    assert gateway.spawned_ids == ["a3"]


@pytest.mark.asyncio
async def test_create_agent_definition_defaults_to_primary_provider_route():
    gateway = FakeGateway()
    skill.set_gateway(gateway)

    result = await skill.create_agent_definition(
        name="planner",
        model="gpt-5.4",
    )

    assert result["ok"] is True
    assert gateway.created[0]["provider"] == "primary"


@pytest.mark.asyncio
async def test_orchestrate_agent_task_auto_spawns_saved_workers_for_manual_mode():
    gateway = FakeGateway()
    skill.set_gateway(gateway)

    result = await skill.orchestrate_agent_task(
        task="Ship the feature",
        mode="manual",
        agent_names=["researcher", "builder"],
        create_shared_task=True,
    )

    assert result["ok"] is True
    assert result["mode"] == "manual"
    assert result["spawned_agents"] == ["builder"]
    assert gateway.shared_tasks == [["researcher", "builder"]]
    assert gateway.delegated[0]["shared_task_id"] == "shared-1"


@pytest.mark.asyncio
async def test_orchestrate_agent_task_auto_mode_prefers_pipeline_for_shared_handoff():
    gateway = FakeGateway()
    skill.set_gateway(gateway)

    result = await skill.orchestrate_agent_task(
        task="Research then implement",
        mode="auto",
        agent_names=["researcher", "builder"],
        shared_handoff=True,
    )

    assert result["ok"] is True
    assert result["mode"] == "pipeline"
    assert gateway.pipeline[0]["agent_names"] == ["researcher", "builder"]


@pytest.mark.asyncio
async def test_orchestrate_agent_task_auto_mode_prefers_auto_route_without_targets():
    gateway = FakeGateway()
    skill.set_gateway(gateway)

    result = await skill.orchestrate_agent_task(
        task="Choose the best available specialist",
        mode="auto",
        max_agents=2,
    )

    assert result["ok"] is True
    assert result["mode"] == "auto-route"
    assert gateway.auto_routed[0]["max_agents"] == 2
