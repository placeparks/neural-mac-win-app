"""
MCP Server — Expose NeuralClaw as a Model Context Protocol provider.

Implements the MCP specification (2024-11-05) over HTTP + SSE transport,
allowing other agents, IDEs, and MCP clients to call NeuralClaw's tools,
read knowledge base documents as resources, and access prompt templates.

Protocol: JSON-RPC 2.0 over HTTP POST, with SSE for server notifications.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

log = logging.getLogger("neuralclaw.mcp_server")

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "neuralclaw"
SERVER_VERSION = "1.5.7"


class MCPServer:
    """
    MCP-compliant server using aiohttp.

    Exposes tools from SkillRegistry, knowledge base documents as resources,
    and agent persona as prompt templates.
    """

    def __init__(
        self,
        port: int = 3001,
        bind_host: str = "127.0.0.1",
        auth_token: str = "",
        expose_tools: bool = True,
        expose_resources: bool = True,
        expose_prompts: bool = True,
    ) -> None:
        self._port = port
        self._bind_host = bind_host
        self._auth_token = auth_token
        self._expose_tools = expose_tools
        self._expose_resources = expose_resources
        self._expose_prompts = expose_prompts
        self._app: Any = None
        self._runner: Any = None
        self._running = False
        self._skill_registry: Any = None
        self._knowledge_base: Any = None
        self._bus: Any = None
        self._persona: str = ""
        self._sse_clients: list[Any] = []

    # ------------------------------------------------------------------
    # Setters (called by gateway during wiring)
    # ------------------------------------------------------------------

    def set_skill_registry(self, registry: Any) -> None:
        self._skill_registry = registry

    def set_knowledge_base(self, kb: Any) -> None:
        self._knowledge_base = kb

    def set_bus(self, bus: Any) -> None:
        self._bus = bus

    def set_persona(self, persona: str) -> None:
        self._persona = persona

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the MCP HTTP server."""
        try:
            from aiohttp import web
        except ImportError:
            log.error("MCP Server requires aiohttp: pip install aiohttp")
            return

        self._app = web.Application(middlewares=[self._auth_middleware])
        self._app.router.add_post("/mcp", self._handle_jsonrpc)
        self._app.router.add_get("/mcp/sse", self._handle_sse)
        self._app.router.add_get("/mcp/health", self._handle_health)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._bind_host, self._port)
        await site.start()
        self._running = True
        log.info("MCP Server listening on %s:%d", self._bind_host, self._port)

    async def stop(self) -> None:
        """Stop the MCP server."""
        self._running = False
        # Close SSE clients
        for ws in self._sse_clients:
            try:
                await ws.write_eof()
            except Exception:
                pass
        self._sse_clients.clear()
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        self._app = None
        log.info("MCP Server stopped")

    # ------------------------------------------------------------------
    # Auth middleware
    # ------------------------------------------------------------------

    @staticmethod
    def _make_auth_middleware(auth_token: str) -> Any:
        """Create auth middleware checking Bearer token."""
        from aiohttp import web

        @web.middleware
        async def middleware(request: Any, handler: Any) -> Any:
            if auth_token:
                auth_header = request.headers.get("Authorization", "")
                if auth_header != f"Bearer {auth_token}":
                    return web.json_response(
                        _jsonrpc_error(None, -32000, "Unauthorized"),
                        status=401,
                    )
            return await handler(request)

        return middleware

    @property
    def _auth_middleware(self) -> Any:
        from aiohttp import web

        auth_token = self._auth_token
        _warned_no_auth = False

        @web.middleware
        async def middleware(request: Any, handler: Any) -> Any:
            nonlocal _warned_no_auth
            # Skip auth for health endpoint
            if request.path == "/mcp/health":
                return await handler(request)
            if not auth_token:
                # No token configured — log warning once and allow (local-only default)
                if not _warned_no_auth:
                    log.warning(
                        "MCP server has no auth_token configured — endpoints are unprotected. "
                        "Set [mcp_server] auth_token in config.toml for production use."
                    )
                    _warned_no_auth = True
            elif auth_token:
                auth_header = request.headers.get("Authorization", "")
                if auth_header != f"Bearer {auth_token}":
                    return web.json_response(
                        _jsonrpc_error(None, -32000, "Unauthorized"),
                        status=401,
                    )
            return await handler(request)

        return middleware

    # ------------------------------------------------------------------
    # JSON-RPC dispatcher
    # ------------------------------------------------------------------

    async def _handle_jsonrpc(self, request: Any) -> Any:
        """Handle JSON-RPC 2.0 requests."""
        from aiohttp import web

        try:
            body = await request.json()
        except Exception:
            return web.json_response(
                _jsonrpc_error(None, -32700, "Parse error"),
                status=400,
            )

        method = body.get("method", "")
        params = body.get("params", {})
        req_id = body.get("id")

        # Publish bus event
        if self._bus:
            try:
                from neuralclaw.bus.neural_bus import EventType
                await self._bus.publish(
                    EventType.MCP_TOOL_CALLED,
                    {"method": method, "client_ip": request.remote},
                    source="mcp_server",
                )
            except Exception:
                pass

        # Dispatch
        dispatch = {
            "initialize": self._handle_initialize,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
            "prompts/list": self._handle_prompts_list,
            "prompts/get": self._handle_prompts_get,
            "ping": self._handle_ping,
        }

        handler = dispatch.get(method)
        if not handler:
            return web.json_response(
                _jsonrpc_error(req_id, -32601, f"Method not found: {method}"),
            )

        try:
            result = await handler(params)
            return web.json_response(_jsonrpc_result(req_id, result))
        except Exception as exc:
            log.error("MCP handler error for %s: %s", method, exc)
            return web.json_response(
                _jsonrpc_error(req_id, -32603, str(exc)),
            )

    # ------------------------------------------------------------------
    # MCP method handlers
    # ------------------------------------------------------------------

    async def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return server capabilities."""
        capabilities: dict[str, Any] = {}
        if self._expose_tools:
            capabilities["tools"] = {"listChanged": False}
        if self._expose_resources and self._knowledge_base:
            capabilities["resources"] = {"subscribe": False, "listChanged": False}
        if self._expose_prompts:
            capabilities["prompts"] = {"listChanged": False}

        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": capabilities,
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
        }

    async def _handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """List all available tools."""
        if not self._expose_tools or not self._skill_registry:
            return {"tools": []}

        tools: list[dict[str, Any]] = []
        for tool_def in self._skill_registry.get_all_tool_defs():
            schema = tool_def.to_json_schema() if hasattr(tool_def, "to_json_schema") else {}
            tools.append({
                "name": tool_def.name,
                "description": getattr(tool_def, "description", ""),
                "inputSchema": schema.get("parameters", {
                    "type": "object",
                    "properties": {},
                }),
            })

        return {"tools": tools}

    async def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool call."""
        if not self._expose_tools or not self._skill_registry:
            return {"content": [{"type": "text", "text": "Tools not available"}], "isError": True}

        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        handler = self._skill_registry.get_handler(tool_name)
        if not handler:
            return {
                "content": [{"type": "text", "text": f"Tool not found: {tool_name}"}],
                "isError": True,
            }

        try:
            result = await handler(**arguments)
            text = json.dumps(result, indent=2, default=str) if isinstance(result, dict) else str(result)
            is_error = isinstance(result, dict) and "error" in result
            return {
                "content": [{"type": "text", "text": text}],
                "isError": is_error,
            }
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"Error: {exc}"}],
                "isError": True,
            }

    async def _handle_resources_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """List knowledge base documents as MCP resources."""
        if not self._expose_resources or not self._knowledge_base:
            return {"resources": []}

        try:
            docs = await self._knowledge_base.list_documents()
            return {
                "resources": [
                    {
                        "uri": f"kb://{d.id}",
                        "name": d.filename,
                        "description": f"{d.doc_type} document ({d.chunk_count} chunks)",
                        "mimeType": "text/plain",
                    }
                    for d in docs
                ],
            }
        except Exception as exc:
            log.error("resources/list error: %s", exc)
            return {"resources": []}

    async def _handle_resources_read(self, params: dict[str, Any]) -> dict[str, Any]:
        """Read a knowledge base document's content."""
        if not self._expose_resources or not self._knowledge_base:
            return {"contents": []}

        uri = params.get("uri", "")
        doc_id = uri.replace("kb://", "") if uri.startswith("kb://") else uri

        try:
            chunks = await self._knowledge_base.get_document_chunks(doc_id)
            if not chunks:
                return {"contents": []}

            full_text = "\n\n".join(c.content for c in chunks)
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "text/plain",
                        "text": full_text,
                    }
                ],
            }
        except Exception as exc:
            log.error("resources/read error: %s", exc)
            return {"contents": []}

    async def _handle_prompts_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """List available prompt templates."""
        if not self._expose_prompts:
            return {"prompts": []}

        prompts = [
            {
                "name": "neuralclaw-persona",
                "description": "The NeuralClaw agent persona and system prompt",
            },
        ]
        return {"prompts": prompts}

    async def _handle_prompts_get(self, params: dict[str, Any]) -> dict[str, Any]:
        """Get a specific prompt template."""
        if not self._expose_prompts:
            return {"messages": []}

        name = params.get("name", "")
        if name == "neuralclaw-persona":
            return {
                "description": "NeuralClaw agent persona",
                "messages": [
                    {
                        "role": "user",
                        "content": {"type": "text", "text": self._persona or "You are NeuralClaw."},
                    }
                ],
            }

        return {"messages": []}

    async def _handle_ping(self, params: dict[str, Any]) -> dict[str, Any]:
        """Respond to ping."""
        return {}

    # ------------------------------------------------------------------
    # SSE endpoint
    # ------------------------------------------------------------------

    async def _handle_sse(self, request: Any) -> Any:
        """Server-Sent Events stream for MCP notifications."""
        from aiohttp import web

        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)
        self._sse_clients.append(response)

        # Send initial connection event
        if self._bus:
            try:
                from neuralclaw.bus.neural_bus import EventType
                await self._bus.publish(
                    EventType.MCP_CLIENT_CONNECTED,
                    {"client_ip": request.remote},
                    source="mcp_server",
                )
            except Exception:
                pass

        # Send endpoint message
        endpoint_msg = json.dumps({
            "jsonrpc": "2.0",
            "method": "endpoint",
            "params": {"uri": f"http://{self._bind_host}:{self._port}/mcp"},
        })
        await response.write(f"event: endpoint\ndata: {endpoint_msg}\n\n".encode())

        # Keep alive
        try:
            while self._running:
                await asyncio.sleep(30)
                await response.write(b": keepalive\n\n")
        except (asyncio.CancelledError, ConnectionResetError, ConnectionError, OSError):
            pass
        finally:
            if response in self._sse_clients:
                self._sse_clients.remove(response)

        return response

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def _handle_health(self, request: Any) -> Any:
        from aiohttp import web

        initialized = bool(self._skill_registry and self._bus)
        status = "ok" if (self._running and initialized) else "degraded" if self._running else "stopped"
        resp = {
            "status": status,
            "server": SERVER_NAME,
            "version": SERVER_VERSION,
            "initialized": initialized,
            "tools_count": len(self._skill_registry.get_all_tool_defs()) if self._skill_registry else 0,
            "knowledge_base": self._knowledge_base is not None,
            "sse_clients": len(self._sse_clients),
        }
        code = 200 if status == "ok" else 503
        return web.json_response(resp, status=code)


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

def _jsonrpc_result(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
