from __future__ import annotations

import pytest

from neuralclaw.swarm.federation import FederationProtocol


def test_agent_card_contains_skills():
    protocol = FederationProtocol(
        "agent-a",
        port=8123,
        bind_host="127.0.0.1",
        description="Helpful agent",
        skills_provider=lambda: [{"name": "search", "description": "Search docs"}],
        a2a_enabled=True,
    )

    card = protocol.get_agent_card()

    assert card["name"] == "agent-a"
    assert card["description"] == "Helpful agent"
    assert card["url"] == "http://127.0.0.1:8123"
    assert card["skills"][0]["name"] == "search"


@pytest.mark.asyncio
async def test_a2a_message_send_roundtrip_and_task_lookup():
    protocol = FederationProtocol("agent-a", a2a_enabled=True)

    async def handler(content: str, from_name: str) -> str:
        return f"{from_name}:{content.upper()}"

    protocol.set_message_handler(handler)

    response = await protocol.handle_a2a_payload(
        {
            "jsonrpc": "2.0",
            "id": "req-1",
            "method": "message/send",
            "params": {
                "from": "peer-1",
                "ttl": 3,
                "message": {
                    "message_id": "msg-1",
                    "role": "user",
                    "parts": [{"kind": "text", "text": "hello"}],
                },
            },
        }
    )

    assert response["result"]["message"]["parts"][0]["text"] == "peer-1:HELLO"
    task_id = response["result"]["task"]["task_id"]

    lookup = await protocol.handle_a2a_payload(
        {
            "jsonrpc": "2.0",
            "id": "req-2",
            "method": "tasks/get",
            "params": {"task_id": task_id},
        }
    )

    assert lookup["result"]["status"] == "completed"
    assert len(lookup["result"]["history"]) == 2


@pytest.mark.asyncio
async def test_a2a_ttl_enforcement():
    protocol = FederationProtocol("agent-a", a2a_enabled=True)

    response = await protocol.handle_a2a_payload(
        {
            "jsonrpc": "2.0",
            "id": "req-3",
            "method": "message/send",
            "params": {
                "ttl": 0,
                "message": {
                    "message_id": "msg-2",
                    "role": "user",
                    "parts": [{"kind": "text", "text": "hello"}],
                },
            },
        }
    )

    assert response["error"]["message"] == "TTL expired"


@pytest.mark.asyncio
async def test_a2a_task_cancel_updates_status():
    protocol = FederationProtocol("agent-a", a2a_enabled=True)

    created = await protocol.handle_a2a_payload(
        {
            "jsonrpc": "2.0",
            "id": "req-4",
            "method": "message/send",
            "params": {
                "ttl": 2,
                "message": {
                    "message_id": "msg-3",
                    "role": "user",
                    "parts": [{"kind": "text", "text": "hello"}],
                },
            },
        }
    )
    task_id = created["result"]["task"]["task_id"]

    cancelled = await protocol.handle_a2a_payload(
        {
            "jsonrpc": "2.0",
            "id": "req-5",
            "method": "tasks/cancel",
            "params": {"task_id": task_id},
        }
    )

    assert cancelled["result"]["status"] == "cancelled"
