from __future__ import annotations

import ast
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from mcp import Client
from pytest import MonkeyPatch

from mirastack_redfish_mcp.render import (
    COMPONENT_DESCRIPTOR_KEYS,
    COMPONENT_IDENTITY_KEYS,
    compact_component,
)
from mirastack_redfish_mcp.runtime import RedfishRuntime
from mirastack_redfish_mcp.schema.describe import (
    describe_action,
    describe_property,
    describe_resource,
    list_actions,
)
from mirastack_redfish_mcp.schema.index import SchemaIndex
from mirastack_redfish_mcp.server import create_server
from mirastack_redfish_mcp.tools.read import LIST_ENVELOPE, READ_TOOL_RETURNS

SYSTEM_URI = "/redfish/v1/Systems/1"

FAKE_SERVICE: dict[str, dict[str, Any]] = {
    "/redfish/v1": {"Systems": {"@odata.id": "/redfish/v1/Systems"}},
    "/redfish/v1/Systems": {"Members": [{"@odata.id": SYSTEM_URI}]},
    SYSTEM_URI: {
        "@odata.id": SYSTEM_URI,
        "Processors": {"@odata.id": f"{SYSTEM_URI}/Processors"},
    },
    f"{SYSTEM_URI}/Processors": {"Members": [{"@odata.id": f"{SYSTEM_URI}/Processors/CPU1"}]},
    f"{SYSTEM_URI}/Processors/CPU1": {
        "@odata.id": f"{SYSTEM_URI}/Processors/CPU1",
        "Id": "CPU1",
        "Name": "Processor 1",
        "Model": "Xeon Platinum 8480+",
        "Manufacturer": "Intel",
        "SerialNumber": "SN-CPU-0001",
        "TotalCores": 56,
        "Status": {"Health": "OK", "State": "Enabled"},
        "Oem": {"Vendor": {"NoiseField": "x" * 500}},
        "ProcessorId": {"IdentificationRegisters": "0x00"},
    },
}


class _FakeClient:
    def __init__(self, payloads: dict[str, dict[str, Any]]) -> None:
        self._payloads = payloads
        self.endpoint = SimpleNamespace(name="default")
        self.requested: list[str] = []

    async def get_json(self, uri: str, **_: Any) -> dict[str, Any]:
        self.requested.append(uri)
        return self._payloads[uri]


def _call_tool(
    monkeypatch: MonkeyPatch,
    name: str,
    arguments: dict[str, Any],
    payloads: dict[str, dict[str, Any]] | None = None,
) -> Any:
    monkeypatch.setenv("MIRASTACK_REDFISH_HOST", "https://127.0.0.1")
    monkeypatch.setenv("MIRASTACK_REDFISH_USERNAME", "user")
    monkeypatch.setenv("MIRASTACK_REDFISH_PASSWORD", "pass")
    monkeypatch.setenv("MIRASTACK_REDFISH_WRITE_MODE", "off")
    monkeypatch.setenv("MIRASTACK_REDFISH_TOOL_PROFILE", "full")
    monkeypatch.delenv("MIRASTACK_REDFISH_TOOLSETS", raising=False)

    fake = _FakeClient(FAKE_SERVICE if payloads is None else payloads)

    @asynccontextmanager
    async def fake_client_for(
        self: RedfishRuntime, endpoint_name: str | None = None
    ) -> AsyncIterator[_FakeClient]:
        yield fake

    monkeypatch.setattr(RedfishRuntime, "client_for", fake_client_for)
    server = create_server(RedfishRuntime())

    async def run() -> Any:
        async with Client(server) as client:
            return await client.call_tool(name, arguments)

    return asyncio.run(run())


def test_compact_component_keeps_descriptors_and_drops_noise() -> None:
    resource = FAKE_SERVICE[f"{SYSTEM_URI}/Processors/CPU1"]
    compact = compact_component(resource)
    assert compact["Model"] == "Xeon Platinum 8480+"
    assert compact["SerialNumber"] == "SN-CPU-0001"
    assert compact["TotalCores"] == 56
    assert compact["Status"] == {"Health": "OK", "State": "Enabled"}
    assert "Oem" not in compact
    assert "ProcessorId" not in compact
    assert set(compact) <= set(COMPONENT_IDENTITY_KEYS) | set(COMPONENT_DESCRIPTOR_KEYS)


def test_component_inventory_details_are_returned(monkeypatch: MonkeyPatch) -> None:
    result = _call_tool(
        monkeypatch,
        "get_component_inventory",
        {"system_uri": SYSTEM_URI, "include_details": True},
    )
    assert result.is_error is False
    members = result.structured_content["components"]["Processors"]["members"]
    assert members[0]["Model"] == "Xeon Platinum 8480+"
    assert members[0]["SerialNumber"] == "SN-CPU-0001"
    assert result.structured_content["components"]["Processors"]["count"] == 1
    assert result.structured_content["components"]["Processors"]["details_truncated"] is False


def test_component_inventory_bounds_detail_fanout(monkeypatch: MonkeyPatch) -> None:
    """Detail fetches must not scale with collection size against a slow BMC."""
    from mirastack_redfish_mcp.tools.read import COMPONENT_DETAIL_LIMIT

    oversized = COMPONENT_DETAIL_LIMIT + 10
    payloads = dict(FAKE_SERVICE)
    uris = [f"{SYSTEM_URI}/Processors/CPU{n}" for n in range(oversized)]
    payloads[f"{SYSTEM_URI}/Processors"] = {"Members": [{"@odata.id": u} for u in uris]}
    for index, uri in enumerate(uris):
        payloads[uri] = {"@odata.id": uri, "Id": f"CPU{index}", "Model": "Xeon"}

    result = _call_tool(
        monkeypatch,
        "get_component_inventory",
        {"system_uri": SYSTEM_URI, "include_details": True},
        payloads=payloads,
    )
    processors = result.structured_content["components"]["Processors"]
    assert processors["count"] == oversized
    assert len(processors["members"]) == COMPONENT_DETAIL_LIMIT
    assert processors["details_truncated"] is True


def test_component_inventory_without_details_returns_uri_stubs(monkeypatch: MonkeyPatch) -> None:
    result = _call_tool(
        monkeypatch,
        "get_component_inventory",
        {"system_uri": SYSTEM_URI, "include_details": False},
    )
    assert result.is_error is False
    members = result.structured_content["components"]["Processors"]["members"]
    assert members == [{"@odata.id": f"{SYSTEM_URI}/Processors/CPU1"}]


def test_walk_nodes_use_the_documented_type_key(monkeypatch: MonkeyPatch) -> None:
    from mirastack_redfish_mcp.tools.raw_schema import RAW_SCHEMA_TOOL_SPECS

    returns = RAW_SCHEMA_TOOL_SPECS["redfish_walk"].returns
    result = _call_tool(monkeypatch, "redfish_walk", {"start_uri": SYSTEM_URI, "max_depth": 0})
    assert result.is_error is False
    node = result.structured_content["nodes"][0]
    for key in node:
        assert f"`{key}`" in returns, f"redfish_walk emits undocumented node key {key!r}"


def test_describe_schema_narrowing(schema_index: SchemaIndex) -> None:
    narrowed = describe_property(schema_index, "ComputerSystem", "PowerState")
    assert narrowed is not None
    assert narrowed["property"] == "PowerState"
    assert "On" in narrowed["summary"]["enum_values"]
    assert describe_property(schema_index, "ComputerSystem", "NotAProperty") is None

    action = describe_action(schema_index, "ComputerSystem", "ComputerSystem.Reset")
    assert action is not None
    assert action["action"] == "#ComputerSystem.Reset"
    assert "ResetType" in action["definition"]["parameter_names"]
    # The leading hash is optional for callers.
    assert describe_action(schema_index, "ComputerSystem", "#ComputerSystem.Reset") == action
    assert describe_action(schema_index, "ComputerSystem", "Nope") is None


def test_describe_resource_unnarrowed_output_is_unchanged(schema_index: SchemaIndex) -> None:
    summary = describe_resource(schema_index, "ComputerSystem")
    assert summary is not None
    assert summary["properties"]["PowerState"] == {
        "description": "The current power state of the system.",
        "type": "string",
        "readonly": True,
        "enum_ref": "Resource.json#/definitions/PowerState",
        "enum_values": summary["properties"]["PowerState"]["enum_values"],
        "enum_descriptions": summary["properties"]["PowerState"]["enum_descriptions"],
    }
    # describe_resource lists action names only; full definitions come from list_actions.
    assert "#ComputerSystem.Reset" in summary["actions"]
    reset = next(a for a in list_actions(schema_index, "ComputerSystem") if a["name"] == "#ComputerSystem.Reset")
    assert "ResetType" in reset["parameters"]


def _tools_returning_truncated_lists(repo_root: Path) -> set[str]:
    source = (repo_root / "src" / "mirastack_redfish_mcp" / "tools" / "read.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "maybe_truncate_list"
            ):
                names.add(node.name)
    return names


def test_truncation_envelope_is_documented(repo_root: Path) -> None:
    wrapped = _tools_returning_truncated_lists(repo_root)
    assert wrapped, "expected at least one tool to wrap its list payload"
    for name in wrapped:
        assert LIST_ENVELOPE in READ_TOOL_RETURNS[name], (
            f"{name} truncates its list but does not document the envelope"
        )
    for name, returns in READ_TOOL_RETURNS.items():
        if LIST_ENVELOPE in returns:
            assert name in wrapped, f"{name} documents an envelope it does not emit"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"resource_type": "NotAType"}, "unknown resource type"),
        ({"resource_type": "ComputerSystem", "property_name": "Nope"}, "valid properties"),
        ({"resource_type": "ComputerSystem", "action_name": "Nope"}, "valid actions"),
        (
            {"resource_type": "ComputerSystem", "property_name": "Id", "action_name": "x"},
            "only one of",
        ),
    ],
)
def test_describe_schema_errors_are_actionable(
    monkeypatch: MonkeyPatch, kwargs: dict[str, Any], message: str
) -> None:
    result = _call_tool(monkeypatch, "redfish_describe_schema", kwargs)
    assert result.is_error is True
    text = " ".join(str(getattr(block, "text", "")) for block in result.content)
    assert message in text
