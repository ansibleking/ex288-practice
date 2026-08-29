"""Distilled Redfish schema index package."""

from mirastack_redfish_mcp.schema.describe import describe_resource, list_actions
from mirastack_redfish_mcp.schema.docs import action_help, enum_help, property_help
from mirastack_redfish_mcp.schema.index import EnumInfo, ResourceTypeInfo, SchemaIndex
from mirastack_redfish_mcp.schema.resolver import UriMatch, UriResolver

__all__ = [
    "EnumInfo",
    "ResourceTypeInfo",
    "SchemaIndex",
    "UriMatch",
    "UriResolver",
    "describe_resource",
    "list_actions",
    "enum_help",
    "property_help",
    "action_help",
]
