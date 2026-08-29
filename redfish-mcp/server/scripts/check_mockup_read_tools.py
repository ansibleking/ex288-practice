#!/usr/bin/env python3
"""Assert core read tools work against a Redfish mockup endpoint."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp import Client

from mirastack_redfish_mcp.runtime import RedfishRuntime
from mirastack_redfish_mcp.server import create_server


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _as_dict(payload: Any, label: str) -> dict[str, Any]:
    _require(isinstance(payload, dict), f"{label} must be an object")
    return payload


async def _run() -> None:
    runtime = RedfishRuntime()
    server = create_server(runtime)

    async with Client(server) as client:
        endpoints_result = await client.call_tool("list_endpoints", {})
        _require(not endpoints_result.is_error, "list_endpoints returned an error")
        endpoints = _as_dict(endpoints_result.structured_content, "list_endpoints payload").get(
            "endpoints"
        )
        _require(isinstance(endpoints, list) and len(endpoints) > 0, "no endpoints were returned")

        service_result = await client.call_tool("service_info", {})
        _require(not service_result.is_error, "service_info returned an error")
        service = _as_dict(service_result.structured_content, "service_info payload")
        service_root = _as_dict(service.get("service_root"), "service_root")
        _require(
            isinstance(service_root.get("@odata.id"), str),
            "service_info did not return service_root.@odata.id",
        )
        capabilities = _as_dict(service.get("capabilities"), "capabilities")
        _require("expand_query" in capabilities, "service_info capabilities were not well-formed")

        systems_result = await client.call_tool("list_systems", {"include_details": False})
        _require(not systems_result.is_error, "list_systems returned an error")
        systems_payload = _as_dict(systems_result.structured_content, "list_systems payload")
        systems = _as_dict(systems_payload.get("systems"), "systems")
        items = systems.get("items")
        _require(isinstance(items, list), "list_systems systems.items must be a list")
        _require(isinstance(systems.get("total"), int), "list_systems systems.total must be an int")
        _require(
            isinstance(systems.get("truncated"), bool),
            "list_systems systems.truncated must be a bool",
        )

    print("Mockup read-tool validation passed: list_endpoints, service_info, list_systems")


if __name__ == "__main__":
    asyncio.run(_run())
