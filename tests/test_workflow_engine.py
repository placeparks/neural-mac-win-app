"""Tests for the Workflow Engine module."""

import asyncio
import json

import pytest

from neuralclaw.cortex.reasoning.workflow import WorkflowEngine, Workflow, WorkflowStep


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_workflows.db")


@pytest.fixture
def engine(db_path):
    return WorkflowEngine(db_path=db_path, step_timeout=5)


# ---------------------------------------------------------------------------
# Mock skill registry for tool execution tests
# ---------------------------------------------------------------------------

class MockRegistry:
    """Minimal SkillRegistry mock with a handler lookup."""

    def __init__(self):
        self._handlers = {}

    def add_handler(self, name, handler):
        self._handlers[name] = handler

    def get_handler(self, name):
        return self._handlers.get(name)


class TestWorkflowLifecycle:
    def test_init_and_ping(self, engine):
        async def run():
            await engine.initialize()
            assert await engine.ping()
            await engine.close()
            assert not await engine.ping()
        asyncio.run(run())


class TestWorkflowCRUD:
    def test_create_workflow(self, engine):
        async def run():
            await engine.initialize()
            wf = await engine.create_workflow(
                name="test_wf",
                steps=[
                    {"id": "s1", "name": "step one", "action": "echo", "action_type": "prompt"},
                ],
                description="A test workflow",
            )
            assert wf.id
            assert wf.name == "test_wf"
            assert len(wf.steps) == 1
            assert wf.status == "pending"
            await engine.close()
        asyncio.run(run())

    def test_list_workflows(self, engine):
        async def run():
            await engine.initialize()
            await engine.create_workflow("wf1", [{"id": "s1", "name": "s", "action": "x", "action_type": "prompt"}])
            await engine.create_workflow("wf2", [{"id": "s1", "name": "s", "action": "y", "action_type": "prompt"}])
            wfs = await engine.list_workflows()
            assert len(wfs) == 2
            await engine.close()
        asyncio.run(run())

    def test_delete_workflow(self, engine):
        async def run():
            await engine.initialize()
            wf = await engine.create_workflow("wf", [{"id": "s1", "name": "s", "action": "x", "action_type": "prompt"}])
            assert await engine.delete_workflow(wf.id)
            wfs = await engine.list_workflows()
            assert len(wfs) == 0
            await engine.close()
        asyncio.run(run())

    def test_delete_nonexistent(self, engine):
        async def run():
            await engine.initialize()
            assert not await engine.delete_workflow("missing")
            await engine.close()
        asyncio.run(run())

    def test_get_status(self, engine):
        async def run():
            await engine.initialize()
            wf = await engine.create_workflow("wf", [{"id": "s1", "name": "s", "action": "x", "action_type": "prompt"}])
            status = await engine.get_status(wf.id)
            assert status["name"] == "wf"
            assert status["status"] == "pending"
            await engine.close()
        asyncio.run(run())


class TestDAGValidation:
    def test_cycle_detection(self, engine):
        async def run():
            await engine.initialize()
            with pytest.raises(ValueError, match="cycle"):
                await engine.create_workflow("cyclic", [
                    {"id": "a", "name": "A", "action": "x", "depends_on": ["b"]},
                    {"id": "b", "name": "B", "action": "y", "depends_on": ["a"]},
                ])
            await engine.close()
        asyncio.run(run())

    def test_unknown_dependency(self, engine):
        async def run():
            await engine.initialize()
            with pytest.raises(ValueError, match="unknown step"):
                await engine.create_workflow("bad_dep", [
                    {"id": "a", "name": "A", "action": "x", "depends_on": ["nonexistent"]},
                ])
            await engine.close()
        asyncio.run(run())

    def test_max_steps_exceeded(self, db_path):
        async def run():
            engine = WorkflowEngine(db_path=db_path, max_steps=2)
            await engine.initialize()
            with pytest.raises(ValueError, match="max"):
                await engine.create_workflow("big", [
                    {"id": f"s{i}", "name": f"step{i}", "action": "x"} for i in range(5)
                ])
            await engine.close()
        asyncio.run(run())


class TestWorkflowExecution:
    def test_linear_execution(self, db_path):
        async def run():
            registry = MockRegistry()

            async def tool_a(**kwargs):
                return {"value": "result_a"}

            async def tool_b(**kwargs):
                return {"value": f"got_{kwargs.get('input', '')}"}

            registry.add_handler("tool_a", tool_a)
            registry.add_handler("tool_b", tool_b)

            engine = WorkflowEngine(db_path=db_path, skill_registry=registry, step_timeout=5)
            await engine.initialize()

            wf = await engine.create_workflow("linear", [
                {"id": "s1", "name": "First", "action": "tool_a", "action_type": "tool", "action_params": {}},
                {"id": "s2", "name": "Second", "action": "tool_b", "action_type": "tool",
                 "action_params": {"input": "test"}, "depends_on": ["s1"]},
            ])

            result = await engine.execute_workflow(wf.id)
            assert result["success"]

            # Wait for async execution
            await asyncio.sleep(0.5)

            status = await engine.get_status(wf.id)
            assert status["status"] == "completed"
            assert status["variables"]["s1"] == {"value": "result_a"}
            await engine.close()
        asyncio.run(run())

    def test_parallel_execution(self, db_path):
        async def run():
            registry = MockRegistry()
            call_order = []

            async def tool_a(**kwargs):
                call_order.append("a")
                return {"step": "a"}

            async def tool_b(**kwargs):
                call_order.append("b")
                return {"step": "b"}

            async def tool_c(**kwargs):
                call_order.append("c")
                return {"step": "c"}

            registry.add_handler("tool_a", tool_a)
            registry.add_handler("tool_b", tool_b)
            registry.add_handler("tool_c", tool_c)

            engine = WorkflowEngine(db_path=db_path, skill_registry=registry, step_timeout=5)
            await engine.initialize()

            # s1 and s2 are parallel, s3 depends on both
            wf = await engine.create_workflow("parallel", [
                {"id": "s1", "name": "A", "action": "tool_a", "action_type": "tool", "action_params": {}},
                {"id": "s2", "name": "B", "action": "tool_b", "action_type": "tool", "action_params": {}},
                {"id": "s3", "name": "C", "action": "tool_c", "action_type": "tool",
                 "action_params": {}, "depends_on": ["s1", "s2"]},
            ])

            await engine.execute_workflow(wf.id)
            await asyncio.sleep(0.5)

            status = await engine.get_status(wf.id)
            assert status["status"] == "completed"
            # c should come after a and b
            assert "c" in call_order
            assert call_order.index("c") > call_order.index("a")
            assert call_order.index("c") > call_order.index("b")
            await engine.close()
        asyncio.run(run())

    def test_condition_skip(self, db_path):
        async def run():
            registry = MockRegistry()

            async def tool_a(**kwargs):
                return {"value": 5}

            async def tool_b(**kwargs):
                return {"skipped": False}

            registry.add_handler("tool_a", tool_a)
            registry.add_handler("tool_b", tool_b)

            engine = WorkflowEngine(db_path=db_path, skill_registry=registry, step_timeout=5)
            await engine.initialize()

            wf = await engine.create_workflow(
                "conditional",
                [
                    {"id": "s1", "name": "A", "action": "tool_a", "action_type": "tool", "action_params": {}},
                    {"id": "s2", "name": "B", "action": "tool_b", "action_type": "tool",
                     "action_params": {}, "depends_on": ["s1"],
                     "condition": "s1.get('value', 0) > 100"},  # Will be False
                ],
            )

            await engine.execute_workflow(wf.id)
            await asyncio.sleep(0.5)

            status = await engine.get_status(wf.id)
            assert status["status"] == "completed"
            # s2 should be skipped
            s2 = [s for s in status["steps"] if s["id"] == "s2"][0]
            assert s2["status"] == "skipped"
            await engine.close()
        asyncio.run(run())

    def test_prompt_type_step(self, engine):
        async def run():
            await engine.initialize()
            wf = await engine.create_workflow("prompt_wf", [
                {"id": "s1", "name": "Prompt", "action": "Hello {name}!",
                 "action_type": "prompt", "action_params": {}},
            ], variables={"name": "World"})

            await engine.execute_workflow(wf.id)
            await asyncio.sleep(0.5)

            status = await engine.get_status(wf.id)
            assert status["status"] == "completed"
            assert "Hello World!" in str(status["variables"]["s1"])
            await engine.close()
        asyncio.run(run())


class TestVariableInterpolation:
    def test_interpolate_string(self):
        engine = WorkflowEngine.__new__(WorkflowEngine)
        result = engine._interpolate_string("Hello {name}, you are {age}!", {"name": "Alice", "age": "30"})
        assert result == "Hello Alice, you are 30!"

    def test_interpolate_params(self):
        engine = WorkflowEngine.__new__(WorkflowEngine)
        params = {"query": "Search for {topic}", "limit": 5}
        result = engine._interpolate(params, {"topic": "python"})
        assert result["query"] == "Search for python"
        assert result["limit"] == 5


class TestConditionEvaluation:
    def test_true_condition(self):
        assert WorkflowEngine._evaluate_condition("x > 5", {"x": 10})

    def test_false_condition(self):
        assert not WorkflowEngine._evaluate_condition("x > 5", {"x": 3})

    def test_invalid_condition(self):
        assert not WorkflowEngine._evaluate_condition("import os", {})

    def test_no_builtins_access(self):
        assert not WorkflowEngine._evaluate_condition("__import__('os')", {})


class TestWorkflowSerialization:
    def test_workflow_to_dict(self):
        wf = Workflow(
            id="test",
            name="Test WF",
            steps=[WorkflowStep(id="s1", name="Step 1", action="echo")],
            variables={"key": "value"},
        )
        d = wf.to_dict()
        assert d["id"] == "test"
        assert d["name"] == "Test WF"
        assert len(d["steps"]) == 1
        assert d["variables"]["key"] == "value"

    def test_workflow_from_dict(self):
        data = {
            "id": "w1",
            "name": "Test",
            "steps": [{"id": "s1", "name": "S1", "action": "a"}],
            "variables": {"x": 1},
        }
        wf = Workflow.from_dict(data)
        assert wf.id == "w1"
        assert len(wf.steps) == 1
        assert wf.variables["x"] == 1
