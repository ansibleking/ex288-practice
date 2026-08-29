"""Collection pagination helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

GetJSONFn = Callable[[str], Awaitable[dict[str, Any]]]


async def collect_members(
    get_json: GetJSONFn, collection_uri: str, limit: int = 1000
) -> list[dict[str, Any]]:
    """Follow Members and Members@odata.nextLink across pages."""
    results: list[dict[str, Any]] = []
    current_uri = collection_uri
    visited: set[str] = set()

    while current_uri and current_uri not in visited:
        visited.add(current_uri)
        payload = await get_json(current_uri)
        members = payload.get("Members")
        if isinstance(members, list):
            for member in members:
                if isinstance(member, dict):
                    results.append(member)
                    if len(results) >= limit:
                        return results
        next_link = payload.get("Members@odata.nextLink")
        current_uri = next_link if isinstance(next_link, str) else ""
    return results


async def iter_member_uris(get_json: GetJSONFn, collection_uri: str) -> AsyncIterator[str]:
    """Yield member URIs from paginated collections."""
    members = await collect_members(get_json, collection_uri)
    for member in members:
        uri = member.get("@odata.id")
        if isinstance(uri, str):
            yield uri
