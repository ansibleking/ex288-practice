#!/usr/bin/env python3
"""Validate hardcoded Redfish actions and payload keys against schema index."""

from __future__ import annotations

import ast
import gzip
import json
import sys
from pathlib import Path
from typing import Any


def _action_key(action_name: str) -> str:
    return action_name if action_name.startswith("#") else f"#{action_name}"


def _load_index(path: Path) -> dict[str, Any]:
    with gzip.open(path) as handle:
        payload = json.loads(handle.read())
    if not isinstance(payload, dict):
        raise ValueError("schema index must be a JSON object")
    return payload


def _load_action_catalog(index_payload: dict[str, Any]) -> dict[str, set[str]]:
    catalog: dict[str, set[str]] = {}
    resources = index_payload.get("resource_types")
    if not isinstance(resources, dict):
        return catalog
    for resource_payload in resources.values():
        if not isinstance(resource_payload, dict):
            continue
        actions = resource_payload.get("actions")
        if not isinstance(actions, dict):
            continue
        for action_name, action_payload in actions.items():
            if not isinstance(action_name, str) or not isinstance(action_payload, dict):
                continue
            params = action_payload.get("parameters")
            names: set[str] = set()
            if isinstance(params, dict):
                names = {name for name in params if isinstance(name, str)}
            catalog.setdefault(action_name, set()).update(names)
    return catalog


def _load_property_catalog(index_payload: dict[str, Any]) -> dict[str, set[str]]:
    catalog: dict[str, set[str]] = {}
    resources = index_payload.get("resource_types")
    if not isinstance(resources, dict):
        return catalog
    for resource_type, resource_payload in resources.items():
        if not isinstance(resource_type, str) or not isinstance(resource_payload, dict):
            continue
        properties = resource_payload.get("properties")
        if not isinstance(properties, dict):
            continue
        names = {name for name in properties if isinstance(name, str)}
        catalog[resource_type] = names
    return catalog


def _literal_dict_keys(node: ast.AST) -> set[str] | None:
    if not isinstance(node, ast.Dict):
        return None
    keys: set[str] = set()
    for key_node in node.keys:
        if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
            return None
        keys.add(key_node.value)
    return keys


def _extract_write_actions(path: Path) -> list[tuple[str, set[str] | None, int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    output: list[tuple[str, set[str] | None, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = None
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
        if func_name == "_invoke_action":
            action_name: str | None = None
            payload_keys: set[str] | None = None
            for keyword in node.keywords:
                if keyword.arg == "action_name":
                    if isinstance(keyword.value, ast.Constant) and isinstance(
                        keyword.value.value, str
                    ):
                        action_name = keyword.value.value
                elif keyword.arg == "payload":
                    payload_keys = _literal_dict_keys(keyword.value)
            if action_name is not None:
                output.append((action_name, payload_keys, node.lineno, "_invoke_action"))
        if func_name == "extract_action_instance" and len(node.args) >= 2:
            arg = node.args[1]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                output.append((arg.value, None, node.lineno, "extract_action_instance"))
    return output


def _extract_example_property_assertions(
    path: Path,
) -> list[tuple[str, str, str, list[str], int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    output: list[tuple[str, str, str, list[str], int]] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id != "EXAMPLE_PROPERTY_ASSERTIONS":
            continue
        if not isinstance(node.value, ast.List):
            return output
        for item in node.value.elts:
            if not isinstance(item, ast.Dict):
                continue
            payload: dict[str, Any] = {}
            for key_node, value_node in zip(item.keys, item.values, strict=False):
                if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                    continue
                key_name = key_node.value
                if isinstance(value_node, ast.Constant):
                    payload[key_name] = value_node.value
                elif isinstance(value_node, ast.List):
                    values: list[str] = []
                    for element in value_node.elts:
                        if isinstance(element, ast.Constant) and isinstance(element.value, str):
                            values.append(element.value)
                    payload[key_name] = values
            tool = payload.get("tool")
            parameter = payload.get("parameter")
            resource_type = payload.get("resource_type")
            properties = payload.get("properties")
            if (
                isinstance(tool, str)
                and isinstance(parameter, str)
                and isinstance(resource_type, str)
                and isinstance(properties, list)
            ):
                output.append((tool, parameter, resource_type, properties, item.lineno))
    return output


def _check_component_fields(property_catalog: dict[str, set[str]]) -> list[str]:
    """Every compact_component descriptor must exist on at least one walked resource type."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from mirastack_redfish_mcp.render import (
        COMPONENT_DESCRIPTOR_KEYS,
        COMPONENT_RESOURCE_TYPES,
    )

    errors: list[str] = []
    known: set[str] = set()
    for resource_type in COMPONENT_RESOURCE_TYPES:
        properties = property_catalog.get(resource_type)
        if properties is None:
            errors.append(
                f"render.py: COMPONENT_RESOURCE_TYPES entry {resource_type!r} "
                "was not found in schema index"
            )
            continue
        known |= properties
    for field_name in COMPONENT_DESCRIPTOR_KEYS:
        if field_name not in known:
            errors.append(
                f"render.py: compact_component field {field_name!r} is not a property of any of "
                f"{list(COMPONENT_RESOURCE_TYPES)}"
            )
    return errors


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    index_path = repo_root / "src" / "mirastack_redfish_mcp" / "data" / "redfish_index.json.gz"
    write_tools_path = repo_root / "src" / "mirastack_redfish_mcp" / "tools" / "write.py"

    index_payload = _load_index(index_path)
    catalog = _load_action_catalog(index_payload)
    property_catalog = _load_property_catalog(index_payload)
    actions = _extract_write_actions(write_tools_path)
    example_assertions = _extract_example_property_assertions(write_tools_path)

    errors: list[str] = []
    for action_name, payload_keys, line_no, source in actions:
        key = _action_key(action_name)
        allowed_params = catalog.get(key)
        if allowed_params is None:
            errors.append(
                f"{write_tools_path}:{line_no}: action '{action_name}' ({source}) "
                "was not found in schema index"
            )
            continue
        if payload_keys is None or not payload_keys:
            continue
        unexpected = sorted(payload_keys - allowed_params)
        if unexpected:
            errors.append(
                f"{write_tools_path}:{line_no}: action '{action_name}' payload keys "
                f"{unexpected} not present in schema params {sorted(allowed_params)}"
            )

    for tool, parameter, resource_type, properties, line_no in example_assertions:
        known_properties = property_catalog.get(resource_type)
        if known_properties is None:
            errors.append(
                f"{write_tools_path}:{line_no}: example assertion for {tool}.{parameter} references unknown resource type {resource_type!r}"
            )
            continue
        missing = sorted(prop for prop in properties if prop not in known_properties)
        if missing:
            errors.append(
                f"{write_tools_path}:{line_no}: example assertion for {tool}.{parameter} uses properties {missing} not found on {resource_type}"
            )

    errors.extend(_check_component_fields(property_catalog))

    if errors:
        print("Corpus conformance check failed:")
        for error in errors:
            print(f"- {error}")
        sys.exit(1)

    print("Corpus conformance check passed.")


if __name__ == "__main__":
    main()
