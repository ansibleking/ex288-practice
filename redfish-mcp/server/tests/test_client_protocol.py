from __future__ import annotations

from typing import Any

import httpx2 as httpx
import pytest

from mirastack_redfish_mcp.models import AuthMode, EndpointConfig
from mirastack_redfish_mcp.redfish.client import RedfishClient
from mirastack_redfish_mcp.redfish.errors import RedfishHTTPError
from mirastack_redfish_mcp.redfish.pagination import collect_members
from mirastack_redfish_mcp.redfish.registries import RegistryStore
from mirastack_redfish_mcp.schema.index import SchemaIndex


def _endpoint() -> EndpointConfig:
    return EndpointConfig(
        name="mock",
        base_url="https://192.0.2.10",
        username="admin",
        password="secret",
        verify_ssl=False,
        auth_mode=AuthMode.BASIC,
    )


@pytest.mark.asyncio
async def test_collect_members_nextlink() -> None:
    pages: dict[str, dict[str, Any]] = {
        "/redfish/v1/Systems": {
            "Members": [{"@odata.id": "/redfish/v1/Systems/1"}],
            "Members@odata.nextLink": "/redfish/v1/Systems?$skip=1",
        },
        "/redfish/v1/Systems?$skip=1": {
            "Members": [{"@odata.id": "/redfish/v1/Systems/2"}],
        },
    }

    async def get_json(uri: str) -> dict[str, Any]:
        return pages[uri]

    members = await collect_members(get_json, "/redfish/v1/Systems")
    assert [m["@odata.id"] for m in members] == ["/redfish/v1/Systems/1", "/redfish/v1/Systems/2"]


@pytest.mark.asyncio
async def test_patch_uses_if_match_and_surfaces_registry_message(schema_index: SchemaIndex) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET" and request.url.path == "/redfish/v1/Systems/1":
            return httpx.Response(
                200,
                json={
                    "@odata.id": "/redfish/v1/Systems/1",
                    "@odata.etag": 'W/"abc123"',
                    "Id": "1",
                },
            )
        if request.method == "PATCH" and request.url.path == "/redfish/v1/Systems/1":
            assert request.headers.get("if-match") == 'W/"abc123"'
            return httpx.Response(
                412,
                json={
                    "error": {
                        "code": "Base.1.0.PreconditionFailed",
                        "message": "Precondition failed",
                        "@Message.ExtendedInfo": [
                            {
                                "MessageId": "Base.1.0.PreconditionFailed",
                                "MessageArgs": [],
                            }
                        ],
                    }
                },
            )
        return httpx.Response(
            404, json={"error": {"code": "Base.1.0.ResourceMissingAtURI", "message": "missing"}}
        )

    transport = httpx.MockTransport(handler)
    store = RegistryStore(schema_index.data)
    client = RedfishClient(_endpoint(), store, transport=transport)

    async with client:
        await client.get_json("/redfish/v1/Systems/1")
        with pytest.raises(RedfishHTTPError) as exc:
            await client.patch_json(
                "/redfish/v1/Systems/1", {"Boot": {"BootSourceOverrideEnabled": "Once"}}
            )
    assert exc.value.status_code == 412
    assert "ETag" in str(exc.value)


@pytest.mark.asyncio
async def test_post_waits_for_task(schema_index: SchemaIndex) -> None:
    state = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/Actions/ComputerSystem.Reset"):
            return httpx.Response(
                202,
                headers={"Location": "/redfish/v1/TaskService/Tasks/42"},
                json={"@odata.id": "/redfish/v1/TaskService/Tasks/42"},
            )
        if request.method == "GET" and request.url.path == "/redfish/v1/TaskService/Tasks/42":
            state["count"] += 1
            if state["count"] < 3:
                return httpx.Response(200, json={"TaskState": "Running", "PercentComplete": 40})
            return httpx.Response(200, json={"TaskState": "Completed", "PercentComplete": 100})
        return httpx.Response(
            404, json={"error": {"code": "Base.1.0.ResourceMissingAtURI", "message": "missing"}}
        )

    transport = httpx.MockTransport(handler)
    client = RedfishClient(_endpoint(), RegistryStore(schema_index.data), transport=transport)
    async with client:
        out = await client.post_json(
            "/redfish/v1/Systems/1/Actions/ComputerSystem.Reset",
            {"ResetType": "GracefulRestart"},
            wait_task=True,
        )
    assert out["accepted"] is True
    assert out["task"]["TaskState"] == "Completed"
