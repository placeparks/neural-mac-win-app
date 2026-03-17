from __future__ import annotations

import asyncio
import json
import time

import pytest

from neuralclaw.bus.neural_bus import NeuralBus
from neuralclaw.config import PolicyConfig
from neuralclaw.cortex.action.policy import PolicyEngine
from neuralclaw.cortex.memory.retrieval import MemoryContext
from neuralclaw.cortex.perception.intake import ChannelType, Signal
from neuralclaw.cortex.reasoning.deliberate import DeliberativeReasoner, ToolDef
from neuralclaw.providers.router import LLMResponse, ToolCall


class FakeToolProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.last_messages = []

    async def complete(self, messages, tools=None, temperature=0.7, max_tokens=4096):
        self.calls += 1
        self.last_messages = messages
        if self.calls == 1:
            return LLMResponse(
                tool_calls=[
                    ToolCall(id="call-1", name="slow_one", arguments={}),
                    ToolCall(id="call-2", name="slow_two", arguments={}),
                ],
                model="fake",
            )
        return LLMResponse(content="done", model="fake")


@pytest.mark.asyncio
async def test_deliberative_reasoner_executes_tool_calls_in_parallel():
    provider = FakeToolProvider()
    reasoner = DeliberativeReasoner(
        bus=NeuralBus(),
        policy=PolicyEngine(PolicyConfig(allowed_tools=["slow_one", "slow_two"])),
    )
    reasoner.set_provider(provider)

    async def slow_one():
        await asyncio.sleep(0.12)
        return {"tool": "one"}

    async def slow_two():
        await asyncio.sleep(0.12)
        return {"tool": "two"}

    tools = [
        ToolDef(name="slow_one", description="slow tool 1", parameters={"type": "object", "properties": {}}, handler=slow_one),
        ToolDef(name="slow_two", description="slow tool 2", parameters={"type": "object", "properties": {}}, handler=slow_two),
    ]

    start = time.perf_counter()
    envelope = await reasoner.reason(
        signal=Signal(content="run both", author_id="u1", channel_type=ChannelType.CLI),
        memory_ctx=MemoryContext(),
        tools=tools,
    )
    elapsed = time.perf_counter() - start

    assert envelope.response == "done"
    assert elapsed < 0.22
    tool_messages = [msg for msg in provider.last_messages if msg["role"] == "tool"]
    assert [msg["tool_call_id"] for msg in tool_messages] == ["call-1", "call-2"]


@pytest.mark.asyncio
async def test_deliberative_reasoner_keeps_other_tool_results_when_one_fails():
    provider = FakeToolProvider()
    reasoner = DeliberativeReasoner(
        bus=NeuralBus(),
        policy=PolicyEngine(PolicyConfig(allowed_tools=["slow_one", "slow_two"])),
    )
    reasoner.set_provider(provider)

    async def slow_one():
        await asyncio.sleep(0.02)
        raise RuntimeError("boom")

    async def slow_two():
        await asyncio.sleep(0.02)
        return {"tool": "two"}

    tools = [
        ToolDef(name="slow_one", description="slow tool 1", parameters={"type": "object", "properties": {}}, handler=slow_one),
        ToolDef(name="slow_two", description="slow tool 2", parameters={"type": "object", "properties": {}}, handler=slow_two),
    ]

    envelope = await reasoner.reason(
        signal=Signal(content="run both", author_id="u1", channel_type=ChannelType.CLI),
        memory_ctx=MemoryContext(),
        tools=tools,
    )

    assert envelope.response == "done"
    tool_messages = [msg for msg in provider.last_messages if msg["role"] == "tool"]
    first_result = json.loads(tool_messages[0]["content"])
    second_result = json.loads(tool_messages[1]["content"])
    assert first_result["error"] == "boom"
    assert second_result == {"tool": "two"}
