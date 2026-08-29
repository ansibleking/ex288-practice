from __future__ import annotations

from collections.abc import Iterator

import pytest

from mirastack_redfish_mcp.redfish.tasks import task_uri_from_202, wait_for_task


def test_task_uri_from_202_location_header() -> None:
    uri = task_uri_from_202({"Location": "/redfish/v1/TaskService/Tasks/123"}, {})
    assert uri == "/redfish/v1/TaskService/Tasks/123"


@pytest.mark.asyncio
async def test_wait_for_task_completes() -> None:
    states: Iterator[dict[str, int | str]] = iter(
        [
            {"TaskState": "Running", "PercentComplete": 25},
            {"TaskState": "Running", "PercentComplete": 80},
            {"TaskState": "Completed", "PercentComplete": 100},
        ]
    )

    async def fake_get_json(_: str) -> dict[str, int | str]:
        return next(states)

    payload = await wait_for_task(
        get_json=fake_get_json, task_uri="/task/1", timeout_sec=3, poll_interval_sec=0
    )
    assert payload["TaskState"] == "Completed"
