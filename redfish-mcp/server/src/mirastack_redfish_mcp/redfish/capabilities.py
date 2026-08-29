"""Service capability probing from ServiceRoot and metadata endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode


@dataclass(slots=True)
class ProtocolCapabilities:
    """Subset of ServiceRoot.ProtocolFeaturesSupported used by this server."""

    expand_query: bool = False
    select_query: bool = False
    only_query: bool = False
    excerpt_query: bool = False
    filter_query: bool = False
    max_expand_levels: int | None = None
    redfish_version: str | None = None
    metadata_uri: str = "/redfish/v1/$metadata"
    odata_uri: str = "/redfish/v1/odata"
    links: dict[str, str] = field(default_factory=dict)


def parse_capabilities(service_root: dict[str, Any]) -> ProtocolCapabilities:
    """Extract capability flags from ServiceRoot payload."""
    pfs = service_root.get("ProtocolFeaturesSupported")
    links = service_root.get("Links")
    result = ProtocolCapabilities(
        redfish_version=service_root.get("RedfishVersion")
        if isinstance(service_root.get("RedfishVersion"), str)
        else None,
    )
    if isinstance(pfs, dict):
        result.expand_query = bool(pfs.get("ExpandQuery", False))
        result.select_query = bool(pfs.get("SelectQuery", False))
        result.only_query = bool(pfs.get("OnlyMemberQuery", False))
        result.excerpt_query = bool(pfs.get("ExcerptQuery", False))
        result.filter_query = bool(pfs.get("FilterQuery", False))
        expand = pfs.get("ExpandQuery")
        if isinstance(expand, dict):
            max_levels = expand.get("MaxLevels")
            if isinstance(max_levels, int):
                result.max_expand_levels = max_levels
    if isinstance(links, dict):
        for key, value in links.items():
            if isinstance(value, dict):
                odata_id = value.get("@odata.id")
                if isinstance(odata_id, str):
                    result.links[key] = odata_id
            elif isinstance(value, list):
                continue
    return result


def apply_query_support(
    *,
    capabilities: ProtocolCapabilities,
    expand: str | None = None,
    select: str | None = None,
    only: str | None = None,
    excerpt: str | None = None,
) -> dict[str, str]:
    """Return only query parameters supported by this service."""
    params: dict[str, str] = {}
    if expand and capabilities.expand_query:
        params["$expand"] = expand
    if select and capabilities.select_query:
        params["$select"] = select
    if only and capabilities.only_query:
        params["only"] = only
    if excerpt and capabilities.excerpt_query:
        params["excerpt"] = excerpt
    return params


def append_query(uri: str, params: dict[str, str]) -> str:
    """Append query parameters to URI while preserving existing query string."""
    if not params:
        return uri
    sep = "&" if "?" in uri else "?"
    return f"{uri}{sep}{urlencode(params)}"


class CapabilityCache:
    """Endpoint-local cache for ServiceRoot and parsed protocol capabilities."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[dict[str, Any], ProtocolCapabilities]] = {}

    async def get(
        self, client: Any, *, refresh: bool = False
    ) -> tuple[dict[str, Any], ProtocolCapabilities]:
        endpoint_name = getattr(client.endpoint, "name", "default")
        if not refresh and endpoint_name in self._cache:
            return self._cache[endpoint_name]
        root = await client.get_json("/redfish/v1")
        caps = parse_capabilities(root)
        self._cache[endpoint_name] = (root, caps)
        return root, caps
