"""Schema description helpers exposed by MCP tools."""

from __future__ import annotations

from typing import Any

from mirastack_redfish_mcp.schema.index import SchemaIndex


def _summarize_property(index: SchemaIndex, property_payload: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "description": property_payload.get("description"),
        "type": property_payload.get("type"),
        "readonly": property_payload.get("readonly"),
    }
    enum_ref = property_payload.get("enum_ref")
    if isinstance(enum_ref, str):
        enum_info = index.get_enum(enum_ref)
        if enum_info is not None:
            summary["enum_ref"] = enum_ref
            summary["enum_values"] = enum_info.values
            summary["enum_descriptions"] = enum_info.descriptions
    return summary


def normalize_action_key(action_name: str) -> str:
    """Normalize an action name to the leading-hash form used by the schema index."""
    return action_name if action_name.startswith("#") else f"#{action_name}"


def describe_property(
    index: SchemaIndex, resource_type: str, property_name: str
) -> dict[str, Any] | None:
    """Return the summary for one property, or None when it is not defined."""
    info = index.get_resource(resource_type)
    if info is None:
        return None
    payload = info.properties.get(property_name)
    if not isinstance(payload, dict):
        return None
    summary = _summarize_property(index, payload)
    for extra in ("units", "deprecated", "version_deprecated"):
        value = payload.get(extra)
        if value is not None:
            summary[extra] = value
    return {
        "resource_type": info.name,
        "latest_version": info.latest_version,
        "property": property_name,
        "summary": summary,
    }


def describe_action(
    index: SchemaIndex, resource_type: str, action_name: str
) -> dict[str, Any] | None:
    """Return the definition for one action, or None when it is not defined."""
    info = index.get_resource(resource_type)
    if info is None:
        return None
    key = normalize_action_key(action_name)
    payload = info.actions.get(key)
    if not isinstance(payload, dict):
        return None
    return {
        "resource_type": info.name,
        "latest_version": info.latest_version,
        "action": key,
        "definition": _summarize_action(index, key, payload),
    }


def _summarize_action(index: SchemaIndex, action_name: str, payload: Any) -> dict[str, Any]:
    params = payload.get("parameters") if isinstance(payload, dict) else {}
    out_params: dict[str, Any] = {}
    if isinstance(params, dict):
        for param_name, param_payload in params.items():
            if not isinstance(param_payload, dict):
                continue
            param_out = dict(param_payload)
            enum_ref = param_payload.get("enum_ref")
            if isinstance(enum_ref, str):
                enum_info = index.get_enum(enum_ref)
                if enum_info is not None:
                    param_out["enum_values"] = enum_info.values
                    param_out["enum_descriptions"] = enum_info.descriptions
            out_params[param_name] = param_out
    return {
        "name": action_name,
        "display_name": payload.get("display_name") if isinstance(payload, dict) else None,
        "description": payload.get("description") if isinstance(payload, dict) else None,
        "parameter_names": sorted(params.keys()) if isinstance(params, dict) else [],
        "parameters": out_params,
    }


def describe_resource(index: SchemaIndex, resource_type: str) -> dict[str, Any] | None:
    """Return a compact summary for one resource type."""
    info = index.get_resource(resource_type)
    if info is None:
        return None
    properties: dict[str, Any] = {}
    for property_name, property_payload in sorted(info.properties.items()):
        if not isinstance(property_payload, dict):
            continue
        properties[property_name] = _summarize_property(index, property_payload)

    return {
        "resource_type": info.name,
        "latest_version": info.latest_version,
        "uris": info.uris,
        "uris_deprecated": info.uris_deprecated,
        "verbs": {
            "insertable": info.insertable,
            "updatable": info.updatable,
            "deletable": info.deletable,
        },
        "actions": sorted(info.actions.keys()),
        "property_count": len(info.properties),
        "properties": properties,
    }


def list_actions(index: SchemaIndex, resource_type: str) -> list[dict[str, Any]]:
    """Return action definitions distilled from schema index."""
    info = index.get_resource(resource_type)
    if info is None:
        return []
    return [
        _summarize_action(index, action_name, payload)
        for action_name, payload in sorted(info.actions.items())
    ]
