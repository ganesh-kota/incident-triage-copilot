"""
MCP Client — connects to multiple MCP servers, discovers tools,
and provides a unified interface for the agent to call any tool.

This is the "bridge" between the LLM agent and the tool servers.
"""

from __future__ import annotations

import asyncio
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger("mcp_client")

# ── Server registry ────────────────────────────────────────────────

SERVERS_DIR = Path(__file__).resolve().parent.parent / "mcp_servers"

# Map of server_name → script path
DEFAULT_SERVERS: dict[str, Path] = {
    "logs_server": SERVERS_DIR / "logs_server.py",
    "runbook_server": SERVERS_DIR / "runbook_server.py",
    "metrics_server": SERVERS_DIR / "metrics_server.py",
    "ticketing_server": SERVERS_DIR / "ticketing_server.py",
}


@dataclass
class ToolDefinition:
    """A discovered tool — ready to be presented to the LLM."""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    server_name: str  # which server owns this tool

    def to_openai_function(self) -> dict:
        """Convert to OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": f"{self.server_name}__{self.name}",
                "description": f"[{self.server_name}] {self.description}",
                "parameters": self.parameters,
            },
        }


@dataclass
class MCPClient:
    """
    Manages connections to multiple MCP servers.

    Lifecycle:
      1. connect()       — starts server processes, discovers tools
      2. call_tool()     — routes tool calls to the right server
      3. disconnect()    — cleanly shuts down all servers
    """

    _sessions: dict[str, tuple[ClientSession, Any]] = field(default_factory=dict)
    _tools: dict[str, ToolDefinition] = field(default_factory=dict)
    _contexts: dict[str, Any] = field(default_factory=dict)

    async def connect(self, servers: dict[str, Path] | None = None) -> list[ToolDefinition]:
        """
        Connect to all configured MCP servers and discover their tools.

        Returns the complete list of available tools.
        """
        servers = servers or DEFAULT_SERVERS
        all_tools: list[ToolDefinition] = []

        for server_name, script_path in servers.items():
            if not script_path.exists():
                logger.warning(f"Server script not found: {script_path}")
                continue

            try:
                tools = await self._connect_server(server_name, script_path)
                all_tools.extend(tools)
                logger.info(f"Connected to {server_name}: {len(tools)} tools discovered")
            except Exception as e:
                logger.error(f"Failed to connect to {server_name}: {e}")

        return all_tools

    async def _connect_server(self, server_name: str, script_path: Path) -> list[ToolDefinition]:
        """Connect to a single MCP server and discover its tools."""
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(script_path)],
        )

        # Create the stdio connection — we need to keep the context managers alive
        read_stream, write_stream = await self._start_server(server_name, server_params)
        session = ClientSession(read_stream, write_stream)
        await session.__aenter__()
        await session.initialize()

        self._sessions[server_name] = session

        # Discover tools
        tools_response = await session.list_tools()
        tools: list[ToolDefinition] = []

        for tool in tools_response.tools:
            td = ToolDefinition(
                name=tool.name,
                description=tool.description or "",
                parameters=tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}},
                server_name=server_name,
            )
            # Register with qualified name: server__toolname
            qualified_name = f"{server_name}__{tool.name}"
            self._tools[qualified_name] = td
            tools.append(td)

        return tools

    async def _start_server(self, server_name: str, params: StdioServerParameters):
        """Start a server process and return the streams."""
        ctx = stdio_client(params)
        transport = await ctx.__aenter__()
        self._contexts[server_name] = ctx
        return transport[0], transport[1]

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> str:
        """
        Call a tool by its qualified name (server_name__tool_name).

        Returns the tool result as a string.
        """
        tool_def = self._tools.get(qualified_name)
        if not tool_def:
            available = list(self._tools.keys())
            return json.dumps({"error": f"Tool '{qualified_name}' not found", "available_tools": available})

        session = self._sessions.get(tool_def.server_name)
        if not session:
            return json.dumps({"error": f"Server '{tool_def.server_name}' not connected"})

        try:
            result = await session.call_tool(tool_def.name, arguments)
            # MCP returns content as a list of content objects
            texts = []
            for content_item in result.content:
                if hasattr(content_item, "text"):
                    texts.append(content_item.text)
                else:
                    texts.append(str(content_item))
            return "\n".join(texts)
        except Exception as e:
            logger.error(f"Tool call failed: {qualified_name} — {e}")
            return json.dumps({"error": f"Tool call failed: {str(e)}"})

    def get_all_tools(self) -> list[ToolDefinition]:
        """Return all discovered tools."""
        return list(self._tools.values())

    def get_openai_tools(self) -> list[dict]:
        """Return tool definitions in OpenAI function-calling format."""
        return [t.to_openai_function() for t in self._tools.values()]

    async def disconnect(self):
        """Cleanly shut down all server connections."""
        # Close sessions first, then transports
        for server_name, session in list(self._sessions.items()):
            try:
                await session.__aexit__(None, None, None)
            except Exception:
                pass  # best effort

        for server_name, ctx in list(self._contexts.items()):
            try:
                await ctx.__aexit__(None, None, None)
            except (Exception, asyncio.CancelledError):
                pass  # best effort — stdio cleanup can raise CancelledError

        self._sessions.clear()
        self._contexts.clear()
        self._tools.clear()
        logger.info("All MCP server connections closed")
