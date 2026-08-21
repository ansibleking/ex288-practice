from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, ListToolsResult, TextContent

from tams_mcp.auth import AuthConfig, TamsAuthManager
from tams_mcp.connectivity import check_tams_auth, get_session_client
from tams_mcp.config import get_settings
from tams_mcp.paths import resolve_swagger_path
from tams_mcp.swagger_loader import GeneratedTool, load_tools_from_swagger
from tams_mcp.tams_client import TamsClient
from tams_mcp.tools import (
    call_curated_tool,
    call_generated_tool,
    curated_tools,
    generated_tool_to_mcp,
)

_generated_tools: list[GeneratedTool] = []


def _resolve_spec_path(settings) -> Path:
    return resolve_swagger_path(settings.swagger_spec_path)


def _load_generated_tools() -> list[GeneratedTool]:
    settings = get_settings()
    include_tags = [t.strip() for t in settings.swagger_include_tags.split(",") if t.strip()]
    return load_tools_from_swagger(
        _resolve_spec_path(settings),
        max_tools=settings.swagger_max_tools,
        include_tags=include_tags,
    )


def build_client() -> TamsClient:
    settings = get_settings()
    auth = TamsAuthManager(
        AuthConfig(
            mode=settings.tams_auth_mode,  # type: ignore[arg-type]
            tenant_id=settings.azure_tenant_id,
            client_id=settings.azure_client_id,
            client_secret=settings.azure_client_secret,
            scope=settings.tams_api_scope,
            static_token=settings.tams_access_token,
        )
    )
    return TamsClient(settings.tams_base_url, auth)


async def handle_list_tools(_ctx, _params) -> ListToolsResult:
    tools = curated_tools()
    tools.extend(generated_tool_to_mcp(t) for t in _generated_tools)
    return ListToolsResult(tools=tools)


async def handle_call_tool(_ctx, params) -> CallToolResult:
    name = params.name
    args = params.arguments or {}
    client = get_session_client()

    try:
        if name.startswith("api_"):
            generated_name = name.removeprefix("api_")
            match = next((t for t in _generated_tools if t.name == generated_name), None)
            if not match:
                raise ValueError(f"Swagger tool not found: {name}")
            result = await call_generated_tool(client, match, args)
        else:
            result = await call_curated_tool(client, name, args)

        payload = json.dumps(result, indent=2, default=str)
        return CallToolResult(content=[TextContent(type="text", text=payload)])
    except Exception as exc:
        payload = json.dumps({"error": str(exc)}, indent=2)
        return CallToolResult(content=[TextContent(type="text", text=payload)], isError=True)


def create_server() -> Server:
    return Server(
        "tams-attendance",
        on_list_tools=handle_list_tools,
        on_call_tool=handle_call_tool,
    )


async def run_server() -> None:
    global _generated_tools
    load_dotenv()
    _generated_tools = _load_generated_tools()
    server = create_server()

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    parser = argparse.ArgumentParser(description="TAMS Attendance MCP Server")
    parser.add_argument("--list-tools", action="store_true", help="Print registered tools and exit")
    parser.add_argument("--check-tams", action="store_true", help="Test TAMS login and report API access")
    args = parser.parse_args()

    load_dotenv()
    global _generated_tools
    _generated_tools = _load_generated_tools()

    if args.list_tools:
        tools = curated_tools()
        tools.extend(generated_tool_to_mcp(t) for t in _generated_tools)
        print(f"Curated: {len(curated_tools())}, Swagger: {len(_generated_tools)}, Total: {len(tools)}")
        for tool in tools:
            print(f"- {tool.name}: {tool.description}")
        return

    if args.check_tams:
        raise SystemExit(asyncio.run(check_tams_auth()))

    asyncio.run(run_server())


if __name__ == "__main__":
    main()
