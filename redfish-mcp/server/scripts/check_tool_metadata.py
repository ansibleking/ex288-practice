#!/usr/bin/env python3
"""Fail if MCP-advertised tool metadata is incomplete."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from mcp import Client

from mirastack_redfish_mcp.config import ALL_TOOLSETS
from mirastack_redfish_mcp.runtime import RedfishRuntime
from mirastack_redfish_mcp.server import create_server
from mirastack_redfish_mcp.tools.registration import _default_param_description

# Ceilings are the measured payload size plus roughly 8 percent headroom.
# Measured at the time of writing: core 19106, standard 41558, full 52634.
# Ceilings are the measured tools/list payload plus roughly 5% headroom, so ordinary wording
# edits pass but a new tool or a verbose description trips the gate. Re-measure with
# `python3 scripts/check_tool_metadata.py --sizes` after intentional growth.
# Measured: core 20795 (15 tools), standard 43669 (33 tools), full 54745 (40 tools).
PROFILE_SIZE_LIMITS: dict[str, int] = {
    "core": 22000,
    "standard": 46000,
    "full": 57500,
}
EXAMPLE_MAX_CHARS = 110


@contextmanager
def _patched_env(values: dict[str, str]) -> Iterator[None]:
    previous: dict[str, str | None] = {key: os.environ.get(key) for key in values}
    for key, value in values.items():
        os.environ[key] = value
    try:
        yield
    finally:
        for key, old_value in previous.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def _collect_enum_values(param_schema: dict[str, object]) -> tuple[set[str], bool]:
    enum_values: set[str] = set()
    allows_null = False

    enum_payload = param_schema.get("enum")
    if isinstance(enum_payload, list):
        enum_values.update(value for value in enum_payload if isinstance(value, str))

    any_of = param_schema.get("anyOf")
    if isinstance(any_of, list):
        for branch in any_of:
            if not isinstance(branch, dict):
                continue
            branch_type = branch.get("type")
            if branch_type == "null":
                allows_null = True
            branch_enum = branch.get("enum")
            if isinstance(branch_enum, list):
                enum_values.update(value for value in branch_enum if isinstance(value, str))
    return enum_values, allows_null


async def _list_tools(
    *, profile: str = "full", write_mode: str = "full", toolsets: str = ""
) -> tuple[Any, list[Any], int]:
    with _patched_env(
        {
            "MIRASTACK_REDFISH_HOST": os.getenv("MIRASTACK_REDFISH_HOST", "https://127.0.0.1"),
            "MIRASTACK_REDFISH_USERNAME": os.getenv("MIRASTACK_REDFISH_USERNAME", "user"),
            "MIRASTACK_REDFISH_PASSWORD": os.getenv("MIRASTACK_REDFISH_PASSWORD", "pass"),
            "MIRASTACK_REDFISH_WRITE_MODE": write_mode,
            "MIRASTACK_REDFISH_TOOL_PROFILE": profile,
            "MIRASTACK_REDFISH_TOOLSETS": toolsets,
        }
    ):
        runtime = RedfishRuntime()
        server = create_server(runtime)
        async with Client(server) as client:
            tools = list((await client.list_tools()).tools)
        payload = json.dumps(
            [tool.model_dump(by_alias=True, exclude_none=True) for tool in tools],
            separators=(",", ":"),
        )
        return server, tools, len(payload)


async def _list_tools_for_profile(profile: str) -> tuple[Any, list[Any], int]:
    return await _list_tools(profile=profile)


def _advertised_texts(server: Any, tools: list[Any]) -> list[tuple[str, str]]:
    """Every model-facing string this configuration advertises, with a label for errors."""
    texts: list[tuple[str, str]] = [("server instructions", str(getattr(server, "instructions", "")))]
    for tool in tools:
        texts.append((f"tool '{tool.name}' description", tool.description or ""))
        properties = (tool.input_schema or {}).get("properties", {})
        if isinstance(properties, dict):
            for param_name, param_schema in properties.items():
                if isinstance(param_schema, dict):
                    texts.append(
                        (
                            f"tool '{tool.name}' parameter '{param_name}'",
                            str(param_schema.get("description") or ""),
                        )
                    )
    return texts


async def _check_no_dangling_tool_references() -> list[str]:
    """No advertised text may tell the model to call a tool this configuration does not expose."""
    errors: list[str] = []
    _, all_tools, _ = await _list_tools(profile="full", write_mode="full")
    universe = {tool.name for tool in all_tools}

    scopes: list[tuple[str, dict[str, str]]] = []
    for profile in sorted(PROFILE_SIZE_LIMITS):
        for write_mode in ("off", "full"):
            scopes.append(
                (
                    f"profile={profile} write_mode={write_mode}",
                    {"profile": profile, "write_mode": write_mode},
                )
            )
    for toolset in sorted(ALL_TOOLSETS):
        scopes.append(
            (
                f"toolsets={toolset}",
                {"profile": "full", "write_mode": "full", "toolsets": toolset},
            )
        )

    for label, kwargs in scopes:
        server, tools, _ = await _list_tools(**kwargs)
        advertised = {tool.name for tool in tools}
        absent = universe - advertised
        if not absent:
            continue
        for source, text in _advertised_texts(server, tools):
            if not text:
                continue
            for candidate in sorted(absent):
                if re.search(rf"\b{re.escape(candidate)}\b", text):
                    errors.append(
                        f"{label}: {source} references tool '{candidate}', "
                        "which is not advertised in this configuration"
                    )
    return errors


async def _check_metadata() -> list[str]:
    errors: list[str] = []
    for profile, size_limit in PROFILE_SIZE_LIMITS.items():
        server, tools, payload_len = await _list_tools_for_profile(profile)

        instructions = getattr(server, "instructions", None)
        if not isinstance(instructions, str) or not instructions.strip():
            errors.append(f"profile '{profile}': server instructions are empty")

        for tool in tools:
            if not tool.title:
                errors.append(f"profile '{profile}': tool '{tool.name}' is missing title")
            if not tool.description:
                errors.append(f"profile '{profile}': tool '{tool.name}' is missing description")
            if "Returns:" not in tool.description:
                errors.append(f"profile '{profile}': tool '{tool.name}' description missing Returns:")
            if "Example:" not in tool.description:
                errors.append(f"profile '{profile}': tool '{tool.name}' description missing Example:")
            else:
                example = tool.description.split("Example:", 1)[1].strip()
                if len(example) > EXAMPLE_MAX_CHARS:
                    errors.append(
                        f"profile '{profile}': tool '{tool.name}' Example line is "
                        f"{len(example)} chars (max {EXAMPLE_MAX_CHARS})"
                    )
            if tool.annotations is None:
                errors.append(f"profile '{profile}': tool '{tool.name}' is missing annotations")
            schema = tool.input_schema or {}
            properties = schema.get("properties", {})
            if isinstance(properties, dict):
                for param_name, param_schema in properties.items():
                    if not isinstance(param_schema, dict):
                        errors.append(
                            f"profile '{profile}': tool '{tool.name}' parameter '{param_name}' schema is not an object"
                        )
                        continue
                    description = param_schema.get("description")
                    if not isinstance(description, str) or not description.strip():
                        errors.append(
                            f"profile '{profile}': tool '{tool.name}' parameter '{param_name}' missing description"
                        )
                    elif description.strip() == _default_param_description(param_name):
                        errors.append(
                            f"profile '{profile}': tool '{tool.name}' parameter '{param_name}' "
                            "uses the generic placeholder description"
                        )
                    enum_values, allows_null = _collect_enum_values(param_schema)
                    if enum_values and isinstance(description, str) and description.rstrip().endswith("..."):
                        errors.append(
                            f"profile '{profile}': tool '{tool.name}' parameter '{param_name}' has truncated enum description"
                        )
                    has_default = "default" in param_schema
                    default = param_schema.get("default")
                    if enum_values and has_default and default is not None and not isinstance(default, str):
                        errors.append(
                            f"profile '{profile}': tool '{tool.name}' parameter '{param_name}' enum default must be string or null"
                        )
                    if enum_values and has_default and isinstance(default, str) and default not in enum_values:
                        errors.append(
                            f"profile '{profile}': tool '{tool.name}' parameter '{param_name}' default {default!r} not in enum {sorted(enum_values)}"
                        )
                    if enum_values and has_default and default is None and not allows_null:
                        errors.append(
                            f"profile '{profile}': tool '{tool.name}' parameter '{param_name}' has null default but schema does not allow null"
                        )
        if payload_len > size_limit:
            errors.append(
                f"profile '{profile}': tool schema payload {payload_len} exceeds limit {size_limit}"
            )
    errors.extend(await _check_no_dangling_tool_references())
    return errors


async def _report_sizes() -> None:
    for profile in ("core", "standard", "full"):
        _, tools, payload_len = await _list_tools_for_profile(profile)
        print(f"{profile:9} tools={len(tools):3} payload={payload_len} bytes")


def main() -> None:
    if "--sizes" in sys.argv[1:]:
        asyncio.run(_report_sizes())
        return
    errors = asyncio.run(_check_metadata())
    if errors:
        print("Tool metadata check failed:")
        for error in errors:
            print(f"- {error}")
        sys.exit(1)
    print("Tool metadata check passed.")


if __name__ == "__main__":
    main()
