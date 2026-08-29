"""Human-readable schema documentation helpers for MCP prompts and resources."""

from __future__ import annotations

from mirastack_redfish_mcp.schema.index import EnumInfo, SchemaIndex


def _truncate(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return f"{text[: max_chars - 3]}..."


def _first_sentence(text: str) -> str:
    compact = " ".join(text.split())
    if not compact:
        return compact
    period_idx = compact.find(".")
    if period_idx == -1:
        return compact
    return compact[: period_idx + 1]


def _join_lines(lines: list[str]) -> str:
    return "\n".join(lines)


def enum_help(enum: EnumInfo, *, max_values: int = 20, max_chars: int = 700) -> str:
    """Render concise enum help text for model-facing docs."""
    value_lines: list[str] = []
    for index, value in enumerate(enum.values):
        if index >= max_values:
            break
        details = enum.descriptions.get(value)
        suffix = ""
        if value in enum.version_deprecated:
            suffix = f" (deprecated since {enum.version_deprecated[value]})"
        elif value in enum.deprecated:
            suffix = " (deprecated)"
        if details:
            value_lines.append(f"- {value}: {_first_sentence(details)}{suffix}")
        else:
            value_lines.append(f"- {value}{suffix}")

    lines: list[str] = []
    for index, line in enumerate(value_lines):
        remaining_values = len(enum.values) - (index + 1)
        candidate = list(lines)
        candidate.append(line)
        if remaining_values > 0:
            candidate.append(
                f"... {remaining_values} more values; call redfish_describe_schema for the full list."
            )
        if len(_join_lines(candidate)) <= max_chars:
            lines.append(line)
            continue
        break

    remaining_values = len(enum.values) - len(lines)
    if remaining_values > 0:
        tail = (
            f"... {remaining_values} more values; call redfish_describe_schema for the full list."
        )
        while lines:
            candidate = list(lines)
            candidate.append(tail)
            if len(_join_lines(candidate)) <= max_chars:
                return _join_lines(candidate)
            lines.pop()
        return _truncate(tail, max_chars=max_chars)
    return _join_lines(lines)


def property_help(
    index: SchemaIndex,
    resource_type: str,
    property_name: str,
    *,
    max_chars: int = 700,
) -> str:
    """Render compact documentation for a property."""
    resource = index.get_resource(resource_type)
    if resource is None:
        return f"Unknown resource type: {resource_type}"
    payload = resource.properties.get(property_name)
    if not isinstance(payload, dict):
        return f"Unknown property {property_name} on {resource_type}"

    lines: list[str] = [f"{resource_type}.{property_name}"]
    description = payload.get("description")
    if isinstance(description, str) and description:
        lines.append(description)
    prop_type = payload.get("type")
    if prop_type is not None:
        lines.append(f"Type: {prop_type}")
    units = payload.get("units")
    if units is not None:
        lines.append(f"Units: {units}")
    if payload.get("readonly") is True:
        lines.append("Read-only: true")
    deprecated = payload.get("deprecated")
    if deprecated:
        lines.append(f"Deprecated: {deprecated}")
    version_deprecated = payload.get("version_deprecated")
    if version_deprecated:
        lines.append(f"Deprecated since: {version_deprecated}")
    enum_ref = payload.get("enum_ref")
    if isinstance(enum_ref, str):
        enum_info = index.get_enum(enum_ref)
        if enum_info is not None:
            lines.append("Allowed values:")
            lines.append(enum_help(enum_info, max_values=10, max_chars=300))
    return _truncate("\n".join(lines), max_chars=max_chars)


def action_help(
    index: SchemaIndex,
    resource_type: str,
    action_key: str,
    *,
    max_chars: int = 1200,
) -> str:
    """Render compact documentation for an action and parameters."""
    resource = index.get_resource(resource_type)
    if resource is None:
        return f"Unknown resource type: {resource_type}"
    payload = resource.actions.get(action_key)
    if not isinstance(payload, dict):
        return f"Unknown action {action_key} on {resource_type}"
    lines: list[str] = [f"{resource_type} {action_key}"]
    description = payload.get("description")
    if isinstance(description, str) and description:
        lines.append(description)
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict) or not parameters:
        lines.append("Parameters: none")
        return _truncate("\n".join(lines), max_chars=max_chars)
    lines.append("Parameters:")
    for param_name in sorted(parameters):
        param_payload = parameters[param_name]
        if not isinstance(param_payload, dict):
            continue
        required = bool(param_payload.get("required_parameter"))
        pieces = [f"- {param_name}", "(required)" if required else "(optional)"]
        data_type = param_payload.get("type")
        if data_type is not None:
            pieces.append(f"type={data_type}")
        lines.append(" ".join(pieces))
        param_desc = param_payload.get("description")
        if isinstance(param_desc, str) and param_desc:
            lines.append(f"  {param_desc}")
        enum_ref = param_payload.get("enum_ref")
        if isinstance(enum_ref, str):
            enum_info = index.get_enum(enum_ref)
            if enum_info is not None:
                lines.append("  Allowed values:")
                lines.append(f"  {enum_help(enum_info, max_values=8, max_chars=320)}")
    return _truncate("\n".join(lines), max_chars=max_chars)
