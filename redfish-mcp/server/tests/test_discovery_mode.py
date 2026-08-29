from __future__ import annotations

import asyncio
import json
import os
import select
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mcp import Client
from pytest import MonkeyPatch

from mirastack_redfish_mcp.runtime import NO_ENDPOINTS_CONFIGURED_MESSAGE, RedfishRuntime
from mirastack_redfish_mcp.server import create_server

REQUEST_LINES = (
    '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"scan","version":"1"}}}',
    '{"jsonrpc":"2.0","method":"notifications/initialized"}',
    '{"jsonrpc":"2.0","id":2,"method":"tools/list"}',
)


def _clear_redfish_env(monkeypatch: MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.startswith("MIRASTACK_REDFISH_") or key.startswith("REDFISH_"):
            monkeypatch.delenv(key, raising=False)


def _extract_tools_list(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {message.get("id"): message for message in messages if "id" in message}
    initialize = by_id.get(1)
    assert isinstance(initialize, dict), f"missing initialize response: {messages}"
    assert "error" not in initialize, initialize
    tools_response = by_id.get(2)
    assert isinstance(tools_response, dict), f"missing tools/list response: {messages}"
    assert "error" not in tools_response, tools_response
    result = tools_response.get("result")
    assert isinstance(result, dict), tools_response
    tools = result.get("tools")
    assert isinstance(tools, list), tools_response
    return tools


def _run_stdio(repo_root: Path, env: Mapping[str, str]) -> tuple[list[dict[str, Any]], str]:
    child_env = {"PYTHONPATH": str(repo_root / "src")}
    child_env.update(env)
    process = subprocess.Popen(
        [sys.executable, "-m", "mirastack_redfish_mcp", "--transport", "stdio"],
        cwd=repo_root,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=child_env,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    for request_line in REQUEST_LINES:
        process.stdin.write(f"{request_line}\n")
    process.stdin.flush()

    messages: list[dict[str, Any]] = []
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        ready, _, _ = select.select([process.stdout], [], [], 0.5)
        if not ready:
            if process.poll() is not None:
                break
            continue
        line = process.stdout.readline()
        if not line:
            if process.poll() is not None:
                break
            continue
        payload_obj = json.loads(line)
        assert isinstance(payload_obj, dict), payload_obj
        messages.append(payload_obj)
        if payload_obj.get("id") == 2:
            break

    process.stdin.close()
    process.stdin = None
    stdout_tail, stderr = process.communicate(timeout=20)
    assert process.returncode == 0, stdout_tail + stderr
    for line in stdout_tail.splitlines():
        if not line.strip():
            continue
        payload_obj = json.loads(line)
        assert isinstance(payload_obj, dict), payload_obj
        messages.append(payload_obj)
    return messages, stderr


def test_stdio_tools_list_with_empty_env_matches_read_only_profile(repo_root: Path) -> None:
    empty_messages, empty_stderr = _run_stdio(repo_root, env={})
    configured_messages, _ = _run_stdio(
        repo_root,
        env={
            "MIRASTACK_REDFISH_HOST": "https://127.0.0.1",
            "MIRASTACK_REDFISH_USERNAME": "user",
            "MIRASTACK_REDFISH_PASSWORD": "pass",
            "MIRASTACK_REDFISH_WRITE_MODE": "off",
        },
    )
    empty_tools = _extract_tools_list(empty_messages)
    configured_tools = _extract_tools_list(configured_messages)
    assert len(empty_tools) == len(configured_tools)
    assert [tool["name"] for tool in empty_tools] == [tool["name"] for tool in configured_tools]
    assert (
        "No Redfish endpoints configured. Serving tool discovery only.\n"
        "Set MIRASTACK_REDFISH_HOST/USERNAME/PASSWORD or provide an endpoints\n"
        "file to enable BMC operations.\n"
    ) in empty_stderr


def test_stdio_tools_list_with_missing_endpoints_file_matches_read_only_profile(
    repo_root: Path, tmp_path: Path
) -> None:
    # Mirrors the container build spec that passes MIRASTACK_REDFISH_ENDPOINTS=<path that was
    # never created>. Inspection must still get the full read-only tool surface.
    missing = tmp_path / "redfish-endpoints.json"
    placeholder_messages, placeholder_stderr = _run_stdio(
        repo_root, env={"MIRASTACK_REDFISH_ENDPOINTS": str(missing)}
    )
    configured_messages, _ = _run_stdio(
        repo_root,
        env={
            "MIRASTACK_REDFISH_HOST": "https://127.0.0.1",
            "MIRASTACK_REDFISH_USERNAME": "user",
            "MIRASTACK_REDFISH_PASSWORD": "pass",
            "MIRASTACK_REDFISH_WRITE_MODE": "off",
        },
    )
    placeholder_tools = _extract_tools_list(placeholder_messages)
    configured_tools = _extract_tools_list(configured_messages)
    assert len(placeholder_tools) == len(configured_tools)
    assert [tool["name"] for tool in placeholder_tools] == [
        tool["name"] for tool in configured_tools
    ]
    assert (
        "No Redfish endpoints configured. Serving tool discovery only.\n"
        "Set MIRASTACK_REDFISH_HOST/USERNAME/PASSWORD or provide an endpoints\n"
        "file to enable BMC operations.\n"
    ) in placeholder_stderr


def test_bmc_tool_returns_structured_error_when_no_endpoints(monkeypatch: MonkeyPatch) -> None:
    _clear_redfish_env(monkeypatch)
    runtime = RedfishRuntime()
    server = create_server(runtime)

    async def run() -> Any:
        async with Client(server) as client:
            return await client.call_tool("service_info", {})

    result = asyncio.run(run())
    assert result.is_error is True
    text = " ".join(str(getattr(block, "text", "")) for block in result.content)
    assert NO_ENDPOINTS_CONFIGURED_MESSAGE in text


def test_schema_tool_succeeds_without_endpoints(monkeypatch: MonkeyPatch) -> None:
    _clear_redfish_env(monkeypatch)
    runtime = RedfishRuntime()
    server = create_server(runtime)

    async def run() -> Any:
        async with Client(server) as client:
            return await client.call_tool("redfish_describe_schema", {"resource_type": "ComputerSystem"})

    result = asyncio.run(run())
    assert result.is_error is False
    assert result.structured_content["resource_type"] == "ComputerSystem"
