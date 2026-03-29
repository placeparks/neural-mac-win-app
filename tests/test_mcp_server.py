"""Tests for the MCP Server module."""

import asyncio
import json

import pytest

from neuralclaw.mcp_server import MCPServer, _jsonrpc_result, _jsonrpc_error


# ---------------------------------------------------------------------------
# Mock skill registry
# ---------------------------------------------------------------------------

class MockToolDef:
    def __init__(self, name, description, handler):
        self.name = name
        self.description = description
        self.handler = handler

    def to_json_schema(self):
        return {"parameters": {"type": "object", "properties": {}}}


class MockRegistry:
    def __init__(self):
        self._tools = []
        self._handlers = {}

    def add_tool(self, name, description, handler):
        self._tools.append(MockToolDef(name, description, handler))
        self._handlers[name] = handler

    def get_all_tool_defs(self):
        return self._tools

    def get_handler(self, name):
        return self._handlers.get(name)


# ---------------------------------------------------------------------------
# Mock knowledge base
# ---------------------------------------------------------------------------

class MockKBDocument:
    def __init__(self, id, filename, doc_type, chunk_count):
        self.id = id
        self.filename = filename
        self.doc_type = doc_type
        self.chunk_count = chunk_count


class MockKBChunk:
    def __init__(self, content):
        self.content = content


class MockKnowledgeBase:
    async def list_documents(self):
        return [MockKBDocument("doc1", "test.txt", "text", 2)]

    async def get_document_chunks(self, doc_id):
        if doc_id == "doc1":
            return [MockKBChunk("Chunk 1 content"), MockKBChunk("Chunk 2 content")]
        return []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMCPServerInit:
    def test_default_config(self):
        server = MCPServer()
        assert server._port == 3001
        assert server._bind_host == "127.0.0.1"
        assert not server.is_running

    def test_custom_config(self):
        server = MCPServer(port=4000, bind_host="0.0.0.0", auth_token="secret")
        assert server._port == 4000
        assert server._auth_token == "secret"


class TestMCPProtocolHandlers:
    def test_initialize(self):
        async def run():
            server = MCPServer()
            result = await server._handle_initialize({})
            assert result["protocolVersion"] == "2024-11-05"
            assert "capabilities" in result
            assert "serverInfo" in result
            assert result["serverInfo"]["name"] == "neuralclaw"
        asyncio.run(run())

    def test_initialize_with_all_features(self):
        async def run():
            server = MCPServer(expose_tools=True, expose_resources=True, expose_prompts=True)
            server.set_knowledge_base(MockKnowledgeBase())
            result = await server._handle_initialize({})
            caps = result["capabilities"]
            assert "tools" in caps
            assert "resources" in caps
            assert "prompts" in caps
        asyncio.run(run())

    def test_tools_list(self):
        async def run():
            server = MCPServer()
            registry = MockRegistry()

            async def echo(**kwargs):
                return {"echo": True}

            registry.add_tool("echo", "Echo tool", echo)
            server.set_skill_registry(registry)

            result = await server._handle_tools_list({})
            assert len(result["tools"]) == 1
            assert result["tools"][0]["name"] == "echo"
        asyncio.run(run())

    def test_tools_list_empty(self):
        async def run():
            server = MCPServer()
            result = await server._handle_tools_list({})
            assert result["tools"] == []
        asyncio.run(run())

    def test_tools_call_success(self):
        async def run():
            server = MCPServer()
            registry = MockRegistry()

            async def adder(a=0, b=0, **kwargs):
                return {"sum": a + b}

            registry.add_tool("adder", "Add numbers", adder)
            server.set_skill_registry(registry)

            result = await server._handle_tools_call({"name": "adder", "arguments": {"a": 3, "b": 4}})
            assert not result["isError"]
            content_text = result["content"][0]["text"]
            parsed = json.loads(content_text)
            assert parsed["sum"] == 7
        asyncio.run(run())

    def test_tools_call_not_found(self):
        async def run():
            server = MCPServer()
            server.set_skill_registry(MockRegistry())
            result = await server._handle_tools_call({"name": "nonexistent", "arguments": {}})
            assert result["isError"]
            assert "not found" in result["content"][0]["text"]
        asyncio.run(run())

    def test_tools_call_handler_error(self):
        async def run():
            server = MCPServer()
            registry = MockRegistry()

            async def broken(**kwargs):
                raise ValueError("Something broke")

            registry.add_tool("broken", "Broken tool", broken)
            server.set_skill_registry(registry)

            result = await server._handle_tools_call({"name": "broken", "arguments": {}})
            assert result["isError"]
            assert "Something broke" in result["content"][0]["text"]
        asyncio.run(run())


class TestMCPResources:
    def test_resources_list(self):
        async def run():
            server = MCPServer()
            server.set_knowledge_base(MockKnowledgeBase())
            result = await server._handle_resources_list({})
            assert len(result["resources"]) == 1
            assert result["resources"][0]["uri"] == "kb://doc1"
            assert result["resources"][0]["name"] == "test.txt"
        asyncio.run(run())

    def test_resources_list_no_kb(self):
        async def run():
            server = MCPServer()
            result = await server._handle_resources_list({})
            assert result["resources"] == []
        asyncio.run(run())

    def test_resources_read(self):
        async def run():
            server = MCPServer()
            server.set_knowledge_base(MockKnowledgeBase())
            result = await server._handle_resources_read({"uri": "kb://doc1"})
            assert len(result["contents"]) == 1
            assert "Chunk 1 content" in result["contents"][0]["text"]
            assert "Chunk 2 content" in result["contents"][0]["text"]
        asyncio.run(run())

    def test_resources_read_nonexistent(self):
        async def run():
            server = MCPServer()
            server.set_knowledge_base(MockKnowledgeBase())
            result = await server._handle_resources_read({"uri": "kb://nonexistent"})
            assert result["contents"] == []
        asyncio.run(run())


class TestMCPPrompts:
    def test_prompts_list(self):
        async def run():
            server = MCPServer()
            result = await server._handle_prompts_list({})
            assert len(result["prompts"]) == 1
            assert result["prompts"][0]["name"] == "neuralclaw-persona"
        asyncio.run(run())

    def test_prompts_get(self):
        async def run():
            server = MCPServer()
            server.set_persona("I am a test agent")
            result = await server._handle_prompts_get({"name": "neuralclaw-persona"})
            assert len(result["messages"]) == 1
            assert "test agent" in result["messages"][0]["content"]["text"]
        asyncio.run(run())

    def test_prompts_get_unknown(self):
        async def run():
            server = MCPServer()
            result = await server._handle_prompts_get({"name": "unknown"})
            assert result["messages"] == []
        asyncio.run(run())

    def test_prompts_disabled(self):
        async def run():
            server = MCPServer(expose_prompts=False)
            result = await server._handle_prompts_list({})
            assert result["prompts"] == []
        asyncio.run(run())


class TestMCPPing:
    def test_ping(self):
        async def run():
            server = MCPServer()
            result = await server._handle_ping({})
            assert result == {}
        asyncio.run(run())


class TestJSONRPCHelpers:
    def test_jsonrpc_result(self):
        resp = _jsonrpc_result(1, {"data": "test"})
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert resp["result"]["data"] == "test"

    def test_jsonrpc_error(self):
        resp = _jsonrpc_error(2, -32601, "Method not found")
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 2
        assert resp["error"]["code"] == -32601
        assert resp["error"]["message"] == "Method not found"
