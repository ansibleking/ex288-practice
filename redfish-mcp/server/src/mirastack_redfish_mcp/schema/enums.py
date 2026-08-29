"""Enum reference resolution against the distilled schema index."""

from __future__ import annotations

import re

from mirastack_redfish_mcp.schema.index import SchemaIndex


def require_enum_values(index: SchemaIndex, enum_ref: str) -> list[str]:
    """Return enum values for a ref, failing loudly when the index lacks it."""
    enum_info = index.get_enum(enum_ref)
    if enum_info is None or not enum_info.values:
        raise ValueError(f"required enum ref not found in schema index: {enum_ref}")
    return list(enum_info.values)


def require_versioned_ref(index: SchemaIndex, resource_type: str, definition_name: str) -> str:
    """Resolve a definition to its newest versioned enum ref in the index."""
    resource = index.get_resource(resource_type)
    if resource is None or resource.latest_version is None:
        raise ValueError(f"missing latest version for resource type: {resource_type}")
    preferred = f"{resource_type}.{resource.latest_version}.json#/definitions/{definition_name}"
    if index.get_enum(preferred) is not None:
        return preferred
    best_ref: str | None = None
    best_version: tuple[int, int, int] | None = None
    pattern = re.compile(
        rf"^{re.escape(resource_type)}\.v(\d+)_(\d+)_(\d+)\.json"
        rf"#/definitions/{re.escape(definition_name)}$"
    )
    for enum_ref in index.enums:
        match = pattern.match(enum_ref)
        if match is None:
            continue
        version = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if best_version is None or version > best_version:
            best_version = version
            best_ref = enum_ref
    if best_ref is None:
        raise ValueError(
            f"missing enum definition {definition_name} for resource type {resource_type}"
        )
    return best_ref
