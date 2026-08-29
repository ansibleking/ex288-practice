"""Raw escape-hatch and schema inspection MCP tools."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from mirastack_redfish_mcp.redfish.actions import extract_action_instance, merge_action_info
from mirastack_redfish_mcp.redfish.capabilities import append_query, apply_query_support
from mirastack_redfish_mcp.runtime import RedfishRuntime
from mirastack_redfish_mcp.safety import ToolRegistrationRule
from mirastack_redfish_mcp.schema.describe import (
    describe_action,
    describe_property,
    describe_resource,
    list_actions,
)
from mirastack_redfish_mcp.tools.registration import register_tool

ToolFunc = TypeVar("ToolFunc", bound=Callable[..., Any])


def _normalize_uri(uri: str) -> str:
    return uri if uri.startswith("/") or uri.startswith("http") else f"/{uri}"


@dataclass(frozen=True)
class ToolSpec:
    title: str
    description: str
    open_world_hint: bool
    param_descriptions: dict[str, str] = field(default_factory=dict)
    toolset: str = ""
    returns: str = ""
    example: str = ""


RAW_SCHEMA_TOOL_SPECS: dict[str, ToolSpec] = {
    "redfish_get": ToolSpec(
        title="Raw Redfish GET",
        description="Escape hatch: use when no typed tool fits. Fetch any Redfish URI directly and apply query options only when the endpoint advertises support.",
        open_world_hint=True,
        param_descriptions={
            "uri": "Resource URI to fetch. Relative values are normalized under /redfish/v1.",
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "expand": "Optional $expand expression. Ignored if service does not support expand.",
            "select": "Optional $select expression. Ignored if service does not support select.",
            "only": "Optional $only expression. Ignored if service does not support only.",
            "excerpt": "Optional $excerpt expression. Ignored if service does not support excerpt.",
        },
        toolset="raw",
        returns="Object with requested `resource`, resolved request URI, and query options that were actually applied.",
        example="redfish_get(uri='/redfish/v1/Systems/1', select='Id,PowerState')",
    ),
    "redfish_walk": ToolSpec(
        title="Walk Redfish graph",
        description="Escape hatch: use for topology exploration when typed list/get tools are insufficient. Perform a breadth-first walk over linked @odata.id resources.",
        open_world_hint=True,
        param_descriptions={
            "start_uri": "Root URI for traversal. Defaults to /redfish/v1.",
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "max_depth": "Maximum traversal depth from start_uri.",
            "max_nodes": "Maximum number of nodes to visit before stopping.",
        },
        toolset="raw",
        returns="Object with `nodes` (each `uri`, `depth`, and `type` from @odata.type) and `visited_count`.",
        example="redfish_walk(start_uri='/redfish/v1', max_depth=2, max_nodes=120)",
    ),
    "redfish_describe_schema": ToolSpec(
        title="Describe Redfish schema type",
        description="Return distilled schema metadata for one Redfish resource type from the bundled index artifact. Full summaries are large, so pass property_name or action_name to retrieve just one definition.",
        open_world_hint=False,
        param_descriptions={
            "resource_type": "Redfish schema type name such as ComputerSystem or Chassis.",
            "property_name": "Optional single property to describe instead of the full summary.",
            "action_name": "Optional single action to describe instead of the full summary, with or without the leading '#'.",
        },
        toolset="schema",
        returns="Full summary with URIs, properties, actions, versions, and enum metadata; or one narrowed property/action definition.",
        example="redfish_describe_schema(resource_type='ComputerSystem', property_name='PowerState')",
    ),
    "redfish_list_available_actions": ToolSpec(
        title="List available actions for resource",
        description="Prefer this before any unfamiliar write/action call. Combine schema actions with live action metadata (ActionInfo and AllowableValues) for a resource URI.",
        open_world_hint=True,
        param_descriptions={
            "uri": "Target resource URI to inspect for supported actions.",
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
        },
        toolset="schema",
        returns="Object with `schema_actions` plus `live_actions` (target URIs, required params, allowable values).",
        example="redfish_list_available_actions(uri='/redfish/v1/Systems/1')",
    ),
}


def register_raw_schema_tools(server: MCPServer, runtime: RedfishRuntime) -> None:
    """Register raw and schema-aware helper tools."""

    def tool(name: str) -> Callable[[ToolFunc], ToolFunc]:
        spec = RAW_SCHEMA_TOOL_SPECS[name]
        annotations = ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=spec.open_world_hint,
        )

        def decorator(fn: ToolFunc) -> ToolFunc:
            rule = ToolRegistrationRule(name=name, toolset=spec.toolset)
            if not runtime.safety.can_register(rule):
                return fn
            description = f"{spec.description} Returns: {spec.returns} Example: {spec.example}"
            register_tool(
                server,
                fn,
                name=name,
                title=spec.title,
                description=description,
                annotations=annotations,
                param_descriptions=spec.param_descriptions,
            )
            return fn

        return decorator

    @tool("redfish_get")
    async def redfish_get(
        uri: str,
        endpoint: str | None = None,
        expand: str | None = None,
        select: str | None = None,
        only: str | None = None,
        excerpt: str | None = None,
    ) -> dict[str, Any]:
        target = _normalize_uri(uri)
        async with runtime.client_for(endpoint) as client:
            _, caps = await runtime.capabilities.get(client)
            query = apply_query_support(
                capabilities=caps,
                expand=expand,
                select=select,
                only=only,
                excerpt=excerpt,
            )
            final_uri = append_query(target, query)
            payload = await client.get_json(final_uri)
            return {
                "endpoint": client.endpoint.name,
                "uri": final_uri,
                "query_applied": query,
                "resource": payload,
            }

    @tool("redfish_walk")
    async def redfish_walk(
        start_uri: str = "/redfish/v1",
        endpoint: str | None = None,
        max_depth: int = 2,
        max_nodes: int = 200,
    ) -> dict[str, Any]:
        target = _normalize_uri(start_uri)
        async with runtime.client_for(endpoint) as client:
            queue: list[tuple[str, int]] = [(target, 0)]
            visited: set[str] = set()
            nodes: list[dict[str, Any]] = []

            while queue and len(nodes) < max_nodes:
                current_uri, depth = queue.pop(0)
                if current_uri in visited:
                    continue
                visited.add(current_uri)
                payload = await client.get_json(current_uri)
                nodes.append(
                    {"uri": current_uri, "depth": depth, "type": payload.get("@odata.type")}
                )
                if depth >= max_depth:
                    continue

                links: list[str] = []
                for value in payload.values():
                    if isinstance(value, dict):
                        odata_id = value.get("@odata.id")
                        if isinstance(odata_id, str):
                            links.append(odata_id)
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict):
                                odata_id = item.get("@odata.id")
                                if isinstance(odata_id, str):
                                    links.append(odata_id)
                for link in links:
                    if link not in visited:
                        queue.append((link, depth + 1))
            return {"endpoint": client.endpoint.name, "nodes": nodes, "visited_count": len(visited)}

    @tool("redfish_describe_schema")
    async def redfish_describe_schema(
        resource_type: str,
        property_name: str | None = None,
        action_name: str | None = None,
    ) -> dict[str, Any]:
        info = runtime.schema_index.get_resource(resource_type)
        if info is None:
            raise ValueError(f"unknown resource type '{resource_type}'")
        if property_name is not None and action_name is not None:
            raise ValueError("pass only one of property_name or action_name")
        if property_name is not None:
            narrowed = describe_property(runtime.schema_index, resource_type, property_name)
            if narrowed is None:
                raise ValueError(
                    f"unknown property '{property_name}' on {resource_type}; "
                    f"valid properties: {', '.join(sorted(info.properties))}"
                )
            return narrowed
        if action_name is not None:
            narrowed = describe_action(runtime.schema_index, resource_type, action_name)
            if narrowed is None:
                raise ValueError(
                    f"unknown action '{action_name}' on {resource_type}; "
                    f"valid actions: {', '.join(sorted(info.actions)) or 'none'}"
                )
            return narrowed
        summary = describe_resource(runtime.schema_index, resource_type)
        if summary is None:
            raise ValueError(f"unknown resource type '{resource_type}'")
        return summary

    @tool("redfish_list_available_actions")
    async def redfish_list_available_actions(
        uri: str,
        endpoint: str | None = None,
    ) -> dict[str, Any]:
        target = _normalize_uri(uri)
        async with runtime.client_for(endpoint) as client:
            resource = await client.get_json(target)
            uri_match = runtime.uri_resolver.resolve(target)
            if uri_match is None:
                raise ValueError(f"unable to resolve URI to a Redfish resource type: {target}")
            actions = list_actions(runtime.schema_index, uri_match.resource_type)
            live_actions: dict[str, Any] = {}
            resource_actions = resource.get("Actions")
            if isinstance(resource_actions, dict):
                for action_key in resource_actions:
                    live = extract_action_instance(resource, action_key)
                    if live is None:
                        continue
                    if live.action_info_uri:
                        try:
                            action_info = await client.get_json(live.action_info_uri)
                            live = merge_action_info(live, action_info)
                        except Exception:
                            pass
                    live_actions[action_key] = {
                        "target": live.target,
                        "title": live.title,
                        "action_info_uri": live.action_info_uri,
                        "parameters": {
                            key: {
                                "required": value.required,
                                "allowable_values": value.allowable_values,
                                "allowable_numbers": value.allowable_numbers,
                                "allowable_pattern": value.allowable_pattern,
                                "minimum_value": value.minimum_value,
                                "maximum_value": value.maximum_value,
                                "data_type": value.data_type,
                            }
                            for key, value in live.parameters.items()
                        },
                    }

            return {
                "endpoint": client.endpoint.name,
                "uri": target,
                "resource_type": uri_match.resource_type,
                "schema_actions": actions,
                "live_actions": live_actions,
            }
