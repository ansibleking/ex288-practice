from __future__ import annotations

import asyncio
import re
from typing import Any

import pytest
from mcp import Client
from mcp.types import Tool
from pytest import MonkeyPatch

from mirastack_redfish_mcp.runtime import RedfishRuntime
from mirastack_redfish_mcp.server import create_server
from mirastack_redfish_mcp.tools import advertised_tool_names


def _list_tools(
    monkeypatch: MonkeyPatch,
    *,
    write_mode: str | None,
    tool_profile: str = "full",
) -> list[Tool]:
    monkeypatch.setenv("MIRASTACK_REDFISH_HOST", "https://127.0.0.1")
    monkeypatch.setenv("MIRASTACK_REDFISH_USERNAME", "user")
    monkeypatch.setenv("MIRASTACK_REDFISH_PASSWORD", "pass")
    monkeypatch.setenv("MIRASTACK_REDFISH_TOOL_PROFILE", tool_profile)
    if write_mode is None:
        monkeypatch.delenv("MIRASTACK_REDFISH_WRITE_MODE", raising=False)
    else:
        monkeypatch.setenv("MIRASTACK_REDFISH_WRITE_MODE", write_mode)

    runtime = RedfishRuntime()
    server = create_server(runtime)

    async def collect() -> list[Tool]:
        async with Client(server) as client:
            return list((await client.list_tools()).tools)

    return asyncio.run(collect())


def test_tool_metadata_in_full_mode(monkeypatch: MonkeyPatch) -> None:
    tools = _list_tools(monkeypatch, write_mode="full")
    assert len(tools) == 40
    missing_titles = [tool.name for tool in tools if not tool.title]
    missing_descriptions = [tool.name for tool in tools if not tool.description]
    missing_annotations = [tool.name for tool in tools if tool.annotations is None]
    assert missing_titles == []
    assert missing_descriptions == []
    assert missing_annotations == []

    missing_param_descriptions: list[tuple[str, str]] = []
    destructive: set[str] = set()
    read_only = 0
    for tool in tools:
        if tool.annotations and tool.annotations.destructive_hint:
            destructive.add(tool.name)
        if tool.annotations and tool.annotations.read_only_hint:
            read_only += 1
        description = tool.description or ""
        assert "Returns:" in description
        assert "Example:" in description
        properties = (tool.input_schema or {}).get("properties", {})
        if isinstance(properties, dict):
            for param_name, schema in properties.items():
                if not isinstance(schema, dict) or not schema.get("description"):
                    missing_param_descriptions.append((tool.name, param_name))
    assert missing_param_descriptions == []
    assert read_only == 25
    assert destructive == {
        "cancel_task",
        "clear_logs",
        "manage_account",
        "redfish_delete",
        "redfish_invoke_action",
        "redfish_patch",
        "redfish_post",
        "reset_manager",
        "reset_to_defaults",
        "set_bios_attributes",
        "set_power_state",
        "simple_update",
    }


def test_tool_metadata_in_default_off_mode(monkeypatch: MonkeyPatch) -> None:
    tools = _list_tools(monkeypatch, write_mode=None)
    assert len(tools) == 25
    assert all(tool.title for tool in tools)
    assert all(tool.description for tool in tools)
    assert all(tool.annotations is not None for tool in tools)


def test_reset_type_description_lists_all_values(monkeypatch: MonkeyPatch) -> None:
    tools = _list_tools(monkeypatch, write_mode="full")
    set_power_state = next(tool for tool in tools if tool.name == "set_power_state")
    schema = set_power_state.input_schema or {}
    properties = schema.get("properties", {})
    assert isinstance(properties, dict)
    reset_type = properties.get("reset_type")
    assert isinstance(reset_type, dict)
    description = str(reset_type.get("description") or "")
    enum_values = reset_type.get("enum")
    assert isinstance(enum_values, list)
    for value in enum_values:
        assert isinstance(value, str)
        assert value in description
    assert not description.rstrip().endswith("...")


def test_enum_param_descriptions_are_not_truncated(monkeypatch: MonkeyPatch) -> None:
    tools = _list_tools(monkeypatch, write_mode="full")
    for tool in tools:
        properties = (tool.input_schema or {}).get("properties", {})
        if not isinstance(properties, dict):
            continue
        for schema in properties.values():
            if not isinstance(schema, dict):
                continue
            if schema.get("enum") is None:
                continue
            description = schema.get("description")
            assert isinstance(description, str)
            assert not description.rstrip().endswith("...")


def test_core_profile_registers_small_surface(monkeypatch: MonkeyPatch) -> None:
    tools = _list_tools(monkeypatch, write_mode="full", tool_profile="core")
    names = {tool.name for tool in tools}
    for required in {
        "list_systems",
        "get_system",
        "get_health_summary",
        "get_thermal",
        "get_power",
        "get_component_inventory",
        "get_log_entries",
        "get_firmware_inventory",
        "redfish_list_available_actions",
        "set_power_state",
        "set_boot_override",
    }:
        assert required in names
    for excluded in {
        "manage_account",
        "set_bios_attributes",
        "list_accounts",
        "redfish_post",
        "redfish_get",
        "simple_update",
        "clear_logs",
        "reset_manager",
    }:
        assert excluded not in names
    assert len(names) == 15


def test_core_tools_allowlist_names_are_real_tools(monkeypatch: MonkeyPatch) -> None:
    from mirastack_redfish_mcp.config import CORE_TOOLS

    full_names = {tool.name for tool in _list_tools(monkeypatch, write_mode="full")}
    assert CORE_TOOLS - full_names == set()


def test_full_tier_tools_are_not_registered_in_config_mode(monkeypatch: MonkeyPatch) -> None:
    config_mode_names = {tool.name for tool in _list_tools(monkeypatch, write_mode="config")}
    assert "set_bios_attributes" in config_mode_names
    assert "eject_virtual_media" in config_mode_names
    assert "insert_virtual_media" not in config_mode_names
    assert "clear_logs" not in config_mode_names
    assert "manage_account" not in config_mode_names

    full_mode_names = {tool.name for tool in _list_tools(monkeypatch, write_mode="full")}
    assert {"insert_virtual_media", "clear_logs", "manage_account"} <= full_mode_names


def _build_server(
    monkeypatch: MonkeyPatch, *, write_mode: str, tool_profile: str, toolsets: str | None = None
) -> tuple[RedfishRuntime, Any, list[Tool]]:
    monkeypatch.setenv("MIRASTACK_REDFISH_HOST", "https://127.0.0.1")
    monkeypatch.setenv("MIRASTACK_REDFISH_USERNAME", "user")
    monkeypatch.setenv("MIRASTACK_REDFISH_PASSWORD", "pass")
    monkeypatch.setenv("MIRASTACK_REDFISH_WRITE_MODE", write_mode)
    monkeypatch.setenv("MIRASTACK_REDFISH_TOOL_PROFILE", tool_profile)
    if toolsets is None:
        monkeypatch.delenv("MIRASTACK_REDFISH_TOOLSETS", raising=False)
    else:
        monkeypatch.setenv("MIRASTACK_REDFISH_TOOLSETS", toolsets)

    runtime = RedfishRuntime()
    server = create_server(runtime)

    async def collect() -> list[Tool]:
        async with Client(server) as client:
            return list((await client.list_tools()).tools)

    return runtime, server, asyncio.run(collect())


CONFIGURATIONS = [
    ("full", "full", None),
    ("off", "full", None),
    ("full", "core", None),
    ("full", "standard", None),
    ("power", "standard", None),
    ("full", "full", "write"),
    ("full", "full", "discovery"),
    ("full", "full", "inventory,health"),
]


@pytest.mark.parametrize(("write_mode", "profile", "toolsets"), CONFIGURATIONS)
def test_advertised_tool_names_matches_registration(
    monkeypatch: MonkeyPatch, write_mode: str, profile: str, toolsets: str | None
) -> None:
    """The name resolver used to build instructions must agree with actual registration."""
    runtime, _, tools = _build_server(
        monkeypatch, write_mode=write_mode, tool_profile=profile, toolsets=toolsets
    )
    assert advertised_tool_names(runtime) == {tool.name for tool in tools}


@pytest.mark.parametrize(("write_mode", "profile", "toolsets"), CONFIGURATIONS)
def test_instructions_only_reference_advertised_tools(
    monkeypatch: MonkeyPatch, write_mode: str, profile: str, toolsets: str | None
) -> None:
    _, server, tools = _build_server(
        monkeypatch, write_mode=write_mode, tool_profile=profile, toolsets=toolsets
    )
    advertised = {tool.name for tool in tools}
    instructions = server.instructions or ""
    full_names = {tool.name for tool in _list_tools(monkeypatch, write_mode="full")}
    for absent in full_names - advertised:
        assert not re.search(rf"\b{re.escape(absent)}\b", instructions), (
            f"instructions name unavailable tool {absent}"
        )


def test_log_entry_severity_is_bound_to_the_corpus_enum(monkeypatch: MonkeyPatch) -> None:
    tools = _list_tools(monkeypatch, write_mode="off")
    get_log_entries = next(tool for tool in tools if tool.name == "get_log_entries")
    severity = (get_log_entries.input_schema or {})["properties"]["severity"]
    enum_values = severity.get("enum") or severity.get("anyOf", [{}])[0].get("enum")
    assert enum_values == ["OK", "Warning", "Critical"]
    assert "Allowed values:" in severity["description"]


def test_example_lines_are_within_budget(monkeypatch: MonkeyPatch) -> None:
    tools = _list_tools(monkeypatch, write_mode="full")
    for tool in tools:
        description = tool.description or ""
        assert "Example:" in description
        example = description.split("Example:", 1)[1].strip()
        assert len(example) <= 110, f"{tool.name} example is {len(example)} chars"
