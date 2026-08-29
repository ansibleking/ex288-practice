"""MCP resources that expose generated schema documentation."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from mirastack_redfish_mcp.runtime import RedfishRuntime
from mirastack_redfish_mcp.schema.describe import describe_resource
from mirastack_redfish_mcp.schema.docs import action_help, property_help


def _resource_summary(runtime: RedfishRuntime, resource_type: str) -> str:
    summary = describe_resource(runtime.schema_index, resource_type)
    if summary is None:
        return f"Unknown resource type: {resource_type}"
    lines = [
        f"ResourceType: {resource_type}",
        f"LatestVersion: {summary.get('latest_version')}",
        f"URI templates: {', '.join(summary.get('uris', []))}",
        f"PropertyCount: {summary.get('property_count')}",
        f"Actions: {', '.join(summary.get('actions', []))}",
    ]
    # Include one example property and action help to keep this resource practical for small models.
    properties = summary.get("properties", {})
    if isinstance(properties, dict):
        for property_name in properties:
            lines.append("")
            lines.append("Example property:")
            lines.append(property_help(runtime.schema_index, resource_type, property_name))
            break
    actions = summary.get("actions", [])
    if isinstance(actions, list):
        for action_key in actions:
            if isinstance(action_key, str):
                lines.append("")
                lines.append("Example action:")
                lines.append(
                    action_help(runtime.schema_index, resource_type, action_key, max_chars=800)
                )
                break
    return "\n".join(lines)


def register_resources(server: MCPServer, runtime: RedfishRuntime) -> None:
    """Register static documentation resources for quick model lookup."""

    @server.resource(
        "redfish://docs/getting-started",
        name="getting-started",
        title="Redfish MCP getting started",
        description="Operator checklist for selecting endpoints, discovering URIs, and safely applying writes.",
        mime_type="text/plain",
    )
    async def getting_started() -> str:
        return (
            "1) Call list_endpoints and choose endpoint.\n"
            "2) Call service_info.\n"
            "3) Call list_systems/list_chassis/list_managers to discover URIs.\n"
            "4) For unfamiliar actions, call redfish_list_available_actions first.\n"
            "5) For all writes, call with confirm=false, inspect dry_run, then re-call with confirm=true."
        )

    for resource_type in (
        "ComputerSystem",
        "Chassis",
        "Manager",
        "Task",
        "UpdateService",
        "VirtualMedia",
    ):
        uri = f"redfish://docs/schema/{resource_type.lower()}"
        title = f"{resource_type} schema guide"
        decorator = server.resource(
            uri,
            name=f"schema-{resource_type.lower()}",
            title=title,
            description=f"Generated schema summary and action guidance for {resource_type}.",
            mime_type="text/plain",
        )

        def build_schema_doc(target_resource_type: str) -> Any:
            async def schema_doc() -> str:
                return _resource_summary(runtime, target_resource_type)

            return schema_doc

        decorator(build_schema_doc(resource_type))
