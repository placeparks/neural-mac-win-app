from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from neuralclaw.bus.neural_bus import NeuralBus
from neuralclaw.cli import main
from neuralclaw.config import AuditConfig, NeuralClawConfig, ProviderConfig
from neuralclaw.cortex.action.audit import AuditLogger
from neuralclaw.cortex.action.policy import RequestContext
from neuralclaw.cortex.reasoning.deliberate import DeliberativeReasoner, ToolDef


@pytest.mark.asyncio
async def test_audit_search_by_tool_and_user_and_export(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(config=AuditConfig(jsonl_path=str(log_path)))
    await logger.initialize()

    await logger.log_action(
        skill_name="web_search",
        action="execute",
        args_preview='{"q":"alpha"}',
        result_preview='{"hits":1}',
        success=True,
        execution_time_ms=12.0,
        request_id="req-1",
        user_id="user-1",
    )
    await logger.log_action(
        skill_name="read_file",
        action="execute",
        args_preview='{"path":"secret.txt"}',
        result_preview="",
        success=False,
        execution_time_ms=0.0,
        request_id="req-2",
        user_id="user-2",
        allowed=False,
        denied_reason="tool_not_allowlisted",
    )

    by_tool = await logger.search(tool="web_search")
    by_user = await logger.search(user_id="user-2")
    denied = await logger.search(denied_only=True)
    trace = await logger.get_trace_actions("req-1")
    exported = await logger.export(str(tmp_path / "audit-export.jsonl"), format="jsonl")

    assert len(by_tool) == 1
    assert by_tool[0].skill_name == "web_search"
    assert len(by_user) == 1
    assert by_user[0].user_id == "user-2"
    assert len(denied) == 1
    assert denied[0].denied_reason == "tool_not_allowlisted"
    assert len(trace) == 1
    assert trace[0].request_id == "req-1"
    assert exported == 2

    with (tmp_path / "audit-export.jsonl").open("r", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    assert {row["request_id"] for row in rows} == {"req-1", "req-2"}


@pytest.mark.asyncio
async def test_deliberate_tool_execution_writes_audit_record(tmp_path):
    bus = NeuralBus()
    logger = AuditLogger(config=AuditConfig(jsonl_path=str(tmp_path / "audit.jsonl")), bus=bus)
    await logger.initialize()
    reasoner = DeliberativeReasoner(bus=bus, audit=logger)

    async def fake_tool(q: str) -> dict[str, int]:
        return {"hits": len(q)}

    tool = ToolDef(
        name="web_search",
        description="search",
        parameters={"type": "object"},
        handler=fake_tool,
    )
    tool_call = SimpleNamespace(name="web_search", arguments={"q": "alpha"})
    request_ctx = RequestContext(
        request_id="req-42",
        user_id="user-42",
        channel_id="cli",
        platform="cli",
    )

    result = await reasoner._execute_tool_call(tool_call, [tool], request_ctx)
    records = await logger.get_trace_actions("req-42")

    assert result == {"hits": 5}
    assert len(records) == 1
    assert records[0].skill_name == "web_search"
    assert records[0].user_id == "user-42"
    assert records[0].allowed


def test_audit_cli_stats_uses_configured_log(monkeypatch, tmp_path):
    config = NeuralClawConfig(
        primary_provider=ProviderConfig(name="local", model="qwen3.5:2b", base_url="http://localhost:11434/v1"),
    )
    config.audit = AuditConfig(jsonl_path=str(tmp_path / "audit.jsonl"))

    async def seed() -> None:
        logger = AuditLogger(config=config.audit)
        await logger.initialize()
        await logger.log_action(
            skill_name="web_search",
            action="execute",
            args_preview='{"q":"x"}',
            result_preview='{"hits":1}',
            success=True,
            execution_time_ms=10.0,
            request_id="req-cli",
            user_id="user-cli",
        )

    import asyncio

    asyncio.run(seed())
    monkeypatch.setattr("neuralclaw.cli.load_config", lambda: config)

    result = CliRunner().invoke(main, ["audit", "stats"])

    assert result.exit_code == 0
    assert "Audit Stats" in result.output
    assert "Total records" in result.output
