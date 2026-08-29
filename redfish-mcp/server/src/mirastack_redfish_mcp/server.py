"""MCP server construction and registration."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import MCPServer

from mirastack_redfish_mcp import __version__
from mirastack_redfish_mcp.instructions import build_instructions
from mirastack_redfish_mcp.prompts import register_prompts
from mirastack_redfish_mcp.resources import register_resources
from mirastack_redfish_mcp.runtime import RedfishRuntime
from mirastack_redfish_mcp.tools import register_tools


async def _normalize_missing_params(
    ctx: ServerRequestContext[Any, Any], call_next: CallNext
) -> HandlerResult:
    if ctx.params is None:
        ctx = replace(ctx, params={})
    return await call_next(ctx)


def create_server(runtime: RedfishRuntime) -> MCPServer:
    """Create and configure an MCP server instance."""
    server = MCPServer(
        name="MIRASTACK Redfish MCP Server",
        version=__version__,
        instructions=build_instructions(runtime),
    )
    server._lowlevel_server.middleware.append(_normalize_missing_params)
    register_tools(server, runtime)
    register_prompts(server, runtime)
    register_resources(server, runtime)
    return server
