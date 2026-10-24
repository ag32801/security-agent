"""Model Context Protocol (MCP) Client Manager.

Manages connections to one or more MCP servers over stdio,
discovers available tools, and executes tool calls requested by Gemini.
"""

import asyncio
from contextlib import AsyncExitStack
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent.config import AgentConfig, MCPServerConfig, PROJECT_ROOT, load_config


class MCPClientManager:
    """Orchestrates connections to multiple MCP servers and exposes unified tool calls."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.exit_stack = AsyncExitStack()
        # Maps tool_name -> (server_name, ClientSession, tool_info)
        self.tools: Dict[str, Tuple[str, ClientSession, Any]] = {}
        # Maps server_name -> ClientSession
        self.sessions: Dict[str, ClientSession] = {}

    async def connect_all(self) -> None:
        """Starts subprocesses for all configured MCP servers and fetches available tools."""
        for server_name, server_cfg in self.config.servers.items():
            await self._connect_server(server_name, server_cfg)

    async def _connect_server(
        self, server_name: str, server_cfg: MCPServerConfig
    ) -> None:
        """Connects to a single MCP server via stdio transport."""
        # Inherit current environment so Windows PATH, SystemRoot, etc. are preserved
        env = dict(os.environ)
        env.update(server_cfg.env)
        # Ensure PYTHONPATH includes project root so modules can be imported
        pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{PROJECT_ROOT}{os.pathsep}{pythonpath}" if pythonpath else str(PROJECT_ROOT)
        )

        params = StdioServerParameters(
            command=server_cfg.command,
            args=server_cfg.args,
            env=env,
        )

        try:
            # Enter stdio transport context
            read_stream, write_stream = await self.exit_stack.enter_async_context(
                stdio_client(params)
            )
            # Enter MCP client session context
            session: ClientSession = await self.exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )

            # Initialize protocol handshake
            await session.initialize()
            self.sessions[server_name] = session

            # List and register tools advertised by this server
            tools_response = await session.list_tools()
            for tool in tools_response.tools:
                self.tools[tool.name] = (server_name, session, tool)
                print(f"[MCP] Discovered tool '{tool.name}' from server '{server_name}'")

        except Exception as e:
            print(f"[MCP Error] Failed to connect to server '{server_name}': {e}")

    def get_gemini_tools(self) -> List[types.Tool]:
        """Converts registered MCP tools into Google GenAI FunctionDeclarations.

        Returns:
            A list containing a types.Tool configured with all discovered functions.
        """
        function_declarations: List[types.FunctionDeclaration] = []

        for tool_name, (_, _, tool_info) in self.tools.items():
            # Extract description and schema (supports both mcp 1.x and 2.x)
            desc = tool_info.description or f"Tool: {tool_name}"
            raw_schema = getattr(
                tool_info, "input_schema", getattr(tool_info, "inputSchema", None)
            )

            # Convert JSON schema if present
            params = None
            if raw_schema and isinstance(raw_schema, dict):
                props = raw_schema.get("properties", {})
                if props:
                    params = raw_schema

            fn_decl = types.FunctionDeclaration(
                name=tool_name,
                description=desc,
                parameters=params,
            )
            function_declarations.append(fn_decl)

        if not function_declarations:
            return []

        return [types.Tool(function_declarations=function_declarations)]

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Executes a tool call on the corresponding MCP server.

        Args:
            tool_name: The name of the tool to invoke.
            arguments: The arguments dictionary provided by Gemini.

        Returns:
            String output from the tool execution.
        """
        if tool_name not in self.tools:
            return f"Error: Tool '{tool_name}' is not registered with any MCP server."

        server_name, session, _ = self.tools[tool_name]

        try:
            result = await session.call_tool(tool_name, arguments or {})

            # MCP tool results contain a list of content blocks (text, image, etc.)
            output_parts: List[str] = []
            for item in result.content:
                if hasattr(item, "text"):
                    output_parts.append(item.text)
                else:
                    output_parts.append(str(item))

            return "\n".join(output_parts) if output_parts else "Tool returned empty response."

        except Exception as e:
            return f"Error executing tool '{tool_name}' on server '{server_name}': {str(e)}"

    async def close(self) -> None:
        """Closes all active MCP client sessions and terminates subprocesses."""
        await self.exit_stack.aclose()


# Diagnostic test routine
async def _test_runner() -> None:
    config = load_config()
    print(f"Connecting to servers configured in servers.json...")
    manager = MCPClientManager(config)
    try:
        await manager.connect_all()
        print(f"\nDiscovered {len(manager.tools)} total tool(s).")
        gemini_tools = manager.get_gemini_tools()
        print(f"Generated Gemini Tool declarations: {gemini_tools}")

        if "check_firewall_status" in manager.tools:
            print("\nExecuting test call for 'check_firewall_status'...")
            res = await manager.execute_tool("check_firewall_status", {})
            print("Result:\n" + res)

        if "check_defender_status" in manager.tools:
            print("\nExecuting test call for 'check_defender_status'...")
            res = await manager.execute_tool("check_defender_status", {})
            print("Result:\n" + res)

    finally:
        await manager.close()
        print("\nAll MCP sessions cleanly closed.")


if __name__ == "__main__":
    asyncio.run(_test_runner())
