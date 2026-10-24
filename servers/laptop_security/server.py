"""FastMCP Server: laptop_security

Exposes read-only Windows security tools over the Model Context Protocol (MCP)
using standard input/output (stdio) transport.

Compatible with both mcp 1.x (FastMCP) and mcp 2.x (MCPServer).
"""

import asyncio
import json

try:
    # mcp >= 2.0.0
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    # mcp < 2.0.0
    from mcp.server.fastmcp import FastMCP  # type: ignore

from servers.laptop_security.tools import (
    check_firewall_status as _check_firewall_status,
    check_defender_status as _check_defender_status,
)

# Initialize the FastMCP server with a human-readable identifier
mcp = FastMCP(name="laptop_security")


@mcp.tool()
async def check_firewall_status() -> str:
    """Check the current status of Windows Firewall profiles (Domain, Private, Public).

    Returns a JSON string containing whether each profile is enabled and its
    default inbound/outbound action (e.g. Block, Allow, NotConfigured).
    """
    # Run the blocking PowerShell command in a separate thread for concurrent execution
    result = await asyncio.to_thread(_check_firewall_status)
    return json.dumps(result, indent=2)


@mcp.tool()
async def check_defender_status() -> str:
    """Check Microsoft Defender antivirus status and signature definition updates.

    Returns a JSON string containing whether real-time protection, antivirus,
    and antispyware are active, along with the antivirus signature version
    and last updated timestamp.
    """
    # Run the blocking PowerShell command in a separate thread for concurrent execution
    result = await asyncio.to_thread(_check_defender_status)
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    # When run directly, start listening for JSON-RPC messages over stdio
    mcp.run(transport="stdio")
