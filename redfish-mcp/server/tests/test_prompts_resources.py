from __future__ import annotations

import asyncio

from mcp import Client
from pytest import MonkeyPatch

from mirastack_redfish_mcp.runtime import RedfishRuntime
from mirastack_redfish_mcp.server import create_server


def test_prompts_and_resources_registered(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("MIRASTACK_REDFISH_HOST", "https://127.0.0.1")
    monkeypatch.setenv("MIRASTACK_REDFISH_USERNAME", "user")
    monkeypatch.setenv("MIRASTACK_REDFISH_PASSWORD", "pass")
    monkeypatch.setenv("MIRASTACK_REDFISH_WRITE_MODE", "full")

    runtime = RedfishRuntime()
    server = create_server(runtime)

    async def collect() -> tuple[list[str], int]:
        async with Client(server) as client:
            prompts = await client.list_prompts()
            resources = await client.list_resources()
            return (sorted(prompt.name for prompt in prompts.prompts), len(resources.resources))

    prompt_names, resource_count = asyncio.run(collect())
    assert prompt_names == [
        "audit_firmware_versions",
        "collect_support_bundle",
        "safe_power_cycle_system",
        "triage_unhealthy_hardware",
    ]
    assert resource_count >= 1
