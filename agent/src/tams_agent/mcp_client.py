from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class TamsMcpClient:
    def __init__(self, server_command: list[str], env: dict[str, str] | None = None) -> None:
        self.server_command = server_command
        self.env = env or {}
        self._stack = AsyncExitStack()
        self.session: ClientSession | None = None

    async def connect(self) -> None:
        params = StdioServerParameters(
            command=self.server_command[0],
            args=self.server_command[1:],
            env={**os.environ, **self.env},
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()

    async def list_tools(self) -> list[dict[str, Any]]:
        assert self.session
        result = await self.session.list_tools()
        return [tool.model_dump() for tool in result.tools]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        assert self.session
        result = await self.session.call_tool(name, arguments)
        chunks = []
        for item in result.content:
            if hasattr(item, "text"):
                chunks.append(item.text)
        return "\n".join(chunks) or json.dumps({"status": "ok"})

    async def close(self) -> None:
        await self._stack.aclose()
