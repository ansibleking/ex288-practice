"""Helpers for registering MCP tools with rich metadata."""

from __future__ import annotations

import inspect
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from mirastack_redfish_mcp.schema.docs import enum_help
from mirastack_redfish_mcp.schema.index import SchemaIndex


def _default_param_description(param_name: str) -> str:
    return f"{param_name.replace('_', ' ')} parameter."


def build_enum_param_descriptions(
    index: SchemaIndex,
    param_descriptions: dict[str, str],
    enum_refs: dict[str, str],
    *,
    max_values: int = 32,
    max_chars: int = 1100,
) -> dict[str, str]:
    """Append rendered corpus enum help to the descriptions of enum-bound parameters."""
    descriptions = dict(param_descriptions)
    for param_name, enum_ref in enum_refs.items():
        enum_info = index.get_enum(enum_ref)
        if enum_info is None:
            raise ValueError(f"required enum ref not found in schema index: {enum_ref}")
        rendered_values = enum_help(enum_info, max_values=max_values, max_chars=max_chars)
        current = descriptions.get(param_name, _default_param_description(param_name))
        descriptions[param_name] = f"{current} Allowed values:\n{rendered_values}"
    return descriptions


def _strip_annotated(annotation: Any) -> Any:
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        if args:
            return args[0]
    return annotation


def apply_parameter_metadata(
    fn: Any,
    *,
    param_descriptions: dict[str, str] | None = None,
    enum_values: dict[str, list[str]] | None = None,
    param_examples: dict[str, list[Any]] | None = None,
) -> None:
    """Attach field descriptions and enum metadata via function annotations."""
    descriptions = param_descriptions or {}
    enums = enum_values or {}
    examples = param_examples or {}
    signature = inspect.signature(fn)
    resolved_hints = get_type_hints(fn, include_extras=True)
    annotations = dict(getattr(fn, "__annotations__", {}))

    for param_name in signature.parameters:
        base_annotation = _strip_annotated(
            resolved_hints.get(param_name, annotations.get(param_name, Any))
        )
        description = descriptions.get(param_name, _default_param_description(param_name))
        field_kwargs: dict[str, Any] = {"description": description}
        param_example_values = examples.get(param_name)
        if param_example_values:
            field_kwargs["examples"] = param_example_values
        values = enums.get(param_name)
        if values:
            optional = any(arg is type(None) for arg in get_args(base_annotation))
            if optional:
                field_kwargs["json_schema_extra"] = {
                    "anyOf": [
                        {"type": "string", "enum": values},
                        {"type": "null"},
                    ]
                }
            else:
                field_kwargs["json_schema_extra"] = {"enum": values}
        field = Field(**field_kwargs)
        annotations[param_name] = Annotated[base_annotation, field]

    fn.__annotations__ = annotations


def register_tool(
    server: MCPServer,
    fn: Any,
    *,
    name: str,
    title: str,
    description: str,
    annotations: ToolAnnotations | None,
    param_descriptions: dict[str, str] | None = None,
    enum_values: dict[str, list[str]] | None = None,
    param_examples: dict[str, list[Any]] | None = None,
    structured_output: bool | None = None,
) -> None:
    """Annotate and register a tool with metadata visible to MCP clients."""
    apply_parameter_metadata(
        fn,
        param_descriptions=param_descriptions,
        enum_values=enum_values,
        param_examples=param_examples,
    )
    server.add_tool(
        fn,
        name=name,
        title=title,
        description=description,
        annotations=annotations,
        structured_output=structured_output,
    )
