"""Redfish protocol helpers and client."""

from mirastack_redfish_mcp.redfish.capabilities import (
    ProtocolCapabilities,
    apply_query_support,
    parse_capabilities,
)
from mirastack_redfish_mcp.redfish.client import RedfishClient
from mirastack_redfish_mcp.redfish.errors import RedfishHTTPError
from mirastack_redfish_mcp.redfish.registries import RegistryStore

__all__ = [
    "ProtocolCapabilities",
    "RedfishClient",
    "RedfishHTTPError",
    "RegistryStore",
    "apply_query_support",
    "parse_capabilities",
]
