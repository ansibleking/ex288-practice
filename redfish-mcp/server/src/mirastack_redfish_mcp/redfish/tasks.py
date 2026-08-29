"""Task monitoring helpers for 202 Accepted responses."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

TERMINAL_TASK_STATES = {
    "Completed",
    "Cancelled",
    "Exception",
    "Killed",
    "Interrupted",
}

RUNNING_TASK_STATES = {
    "New",
    "Starting",
    "Running",
    "Suspended",
    "Pending",
    "Stopping",
    "Service",
    "Cancelling",
}


def task_uri_from_202(response_headers: dict[str, str], payload: Any) -> str | None:
    """
    Resolve task monitor URI from a 202 response.

    Preference order:
    1) Location header
    2) Payload TaskMonitor
    3) Payload @odata.id (Task resource)
    """
    location = response_headers.get("location") or response_headers.get("Location")
    if isinstance(location, str) and location.strip():
        return location.strip()
    if isinstance(payload, dict):
        monitor = payload.get("TaskMonitor")
        if isinstance(monitor, str) and monitor.strip():
            return monitor.strip()
        odata_id = payload.get("@odata.id")
        if isinstance(odata_id, str) and odata_id.strip():
            return odata_id.strip()
    return None


async def wait_for_task(
    *,
    get_json: Callable[[str], Awaitable[dict[str, Any]]],
    task_uri: str,
    timeout_sec: float = 300.0,
    poll_interval_sec: float = 1.5,
) -> dict[str, Any]:
    """Poll Task/TaskMonitor until terminal or timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_sec
    while True:
        payload = await get_json(task_uri)
        state = payload.get("TaskState")
        if isinstance(state, str):
            if state in TERMINAL_TASK_STATES:
                return payload
            if state not in RUNNING_TASK_STATES:
                return payload
        if loop.time() >= deadline:
            out = dict(payload)
            out["Timeout"] = True
            return out
        await asyncio.sleep(poll_interval_sec)
