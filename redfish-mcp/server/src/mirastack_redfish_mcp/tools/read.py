"""Read-oriented MCP tools for Redfish resources."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from mirastack_redfish_mcp.redfish.pagination import collect_members, iter_member_uris
from mirastack_redfish_mcp.render import compact_component, compact_resource, maybe_truncate_list
from mirastack_redfish_mcp.runtime import RedfishRuntime
from mirastack_redfish_mcp.safety import ToolRegistrationRule
from mirastack_redfish_mcp.schema.enums import require_enum_values, require_versioned_ref
from mirastack_redfish_mcp.tools.registration import build_enum_param_descriptions, register_tool

ToolFunc = TypeVar("ToolFunc", bound=Callable[..., Any])

# Appended to the Returns line of every tool whose list payload goes through
# maybe_truncate_list, so callers know to read `.items` rather than iterating the field.
LIST_ENVELOPE = " Lists are wrapped as {items, total, truncated}."

# Upper bound on per-category detail fetches in get_component_inventory. Each detail costs one
# GET against the BMC, which is often slow and rate-limited.
COMPONENT_DETAIL_LIMIT = 64


def _link_uri(payload: dict[str, Any], key: str, fallback: str) -> str:
    value = payload.get(key)
    if isinstance(value, dict):
        odata_id = value.get("@odata.id")
        if isinstance(odata_id, str):
            return odata_id
    links = payload.get("Links")
    if isinstance(links, dict):
        value = links.get(key)
        if isinstance(value, dict):
            odata_id = value.get("@odata.id")
            if isinstance(odata_id, str):
                return odata_id
    return fallback


async def _first_collection_member_uri(client: Any, collection_uri: str) -> str | None:
    members = await collect_members(client.get_json, collection_uri, limit=1)
    if not members:
        return None
    odata_id = members[0].get("@odata.id")
    return odata_id if isinstance(odata_id, str) else None


def _extract_status(resource: dict[str, Any]) -> dict[str, Any]:
    status = resource.get("Status")
    if isinstance(status, dict):
        return {
            "Health": status.get("Health"),
            "HealthRollup": status.get("HealthRollup"),
            "State": status.get("State"),
        }
    return {
        "Health": resource.get("Health"),
        "State": resource.get("State"),
    }


@dataclass(frozen=True)
class ToolSpec:
    title: str
    description: str
    param_descriptions: dict[str, str] = field(default_factory=dict)
    toolset: str = ""
    returns: str = ""
    example: str = ""
    open_world_hint: bool = True


READ_TOOL_SPECS: dict[str, ToolSpec] = {
    "list_endpoints": ToolSpec(
        title="List configured Redfish endpoints",
        description="List all configured endpoints and their auth/read-only settings so callers can choose a valid endpoint value.",
        # Reads only local server configuration; performs no request against a Redfish service.
        open_world_hint=False,
    ),
    "service_info": ToolSpec(
        title="Get Redfish ServiceRoot capabilities",
        description="Fetch ServiceRoot and protocol feature flags to understand what query options and links the endpoint supports.",
        param_descriptions={"endpoint": "Configured endpoint name. Omit to use the default endpoint."},
    ),
    "list_systems": ToolSpec(
        title="List computer systems",
        description="List ComputerSystem members from /Systems; enable include_details for full resource payloads and health snapshots.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "include_details": "True fetches each member resource; false returns only member URIs.",
        },
    ),
    "get_system": ToolSpec(
        title="Get one computer system",
        description="Fetch a single ComputerSystem resource by URI or ID; if omitted, the first system member is auto-selected.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "system_id": "System identifier appended to /redfish/v1/Systems/{system_id}.",
            "uri": "Explicit system resource URI to fetch.",
        },
    ),
    "list_chassis": ToolSpec(
        title="List chassis resources",
        description="List Chassis members and optionally include full details and status for each chassis.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "include_details": "True fetches each member resource; false returns only member URIs.",
        },
    ),
    "get_chassis": ToolSpec(
        title="Get one chassis resource",
        description="Fetch a single Chassis resource by URI or ID; if omitted, the first chassis member is auto-selected.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "chassis_id": "Chassis identifier appended to /redfish/v1/Chassis/{chassis_id}.",
            "uri": "Explicit chassis resource URI to fetch.",
        },
    ),
    "list_managers": ToolSpec(
        title="List manager resources",
        description="List Manager members (BMC controllers such as iDRAC/iLO/XCC) and optionally include full payloads and status fields.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "include_details": "True fetches each member resource; false returns only member URIs.",
        },
    ),
    "get_manager": ToolSpec(
        title="Get one manager resource",
        description="Fetch one Manager (BMC/iDRAC/iLO/XCC) by URI or ID; if omitted, the first manager member is auto-selected.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "manager_id": "Manager identifier appended to /redfish/v1/Managers/{manager_id}.",
            "uri": "Explicit manager resource URI to fetch.",
        },
    ),
    "get_health_summary": ToolSpec(
        title="Summarize system health",
        description="Collect health/state rollups for Systems, Chassis, and Managers to provide a quick fleet health summary.",
        param_descriptions={"endpoint": "Configured endpoint name. Omit to use the default endpoint."},
    ),
    "get_thermal": ToolSpec(
        title="Get chassis thermal data",
        description="Fetch ThermalSubsystem/Thermal for temperature, fan, and cooling telemetry. Prefer this tool for inlet/exhaust temperature and fan speed requests.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "chassis_uri": "Target chassis URI. Omit to auto-select the first chassis.",
        },
    ),
    "get_power": ToolSpec(
        title="Get chassis power data",
        description="Fetch PowerSubsystem/Power for watts, PSU, power-control, and power-cap telemetry. Prefer this tool for PSU or power-draw requests.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "chassis_uri": "Target chassis URI. Omit to auto-select the first chassis.",
        },
    ),
    "get_sensors": ToolSpec(
        title="Get sensor readings",
        description="Fetch broad cross-domain sensor data from Sensors collection; if absent, fall back to deprecated Thermal inline arrays. Use get_thermal for cooling details and get_power for PSU/power metrics.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "chassis_uri": "Target chassis URI. Omit to auto-select the first chassis.",
            "limit": "Maximum number of sensor members to fetch.",
        },
    ),
    "get_component_inventory": ToolSpec(
        title="Get system component inventory",
        description="Walk the Processors, Memory, Storage, EthernetInterfaces, and PCIeDevices collections of one system. With include_details true each member is fetched, returning model, manufacturer, serial number, part number, capacity, core count, and MAC address where the vendor reports them.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "system_uri": "Target ComputerSystem URI. Omit to auto-select the first system.",
            "include_details": "True fetches each component resource (up to 64 per collection) and returns its model/serial/capacity fields; false returns only member URIs and counts.",
        },
    ),
    "get_log_entries": ToolSpec(
        title="Get log service entries",
        description="Collect entries from a selected LogService with optional severity and timestamp filtering for troubleshooting workflows.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "manager_uri": "Optional manager URI used to resolve a LogServices collection when log_service_uri is omitted.",
            "log_service_uri": "Optional explicit LogService URI. Omit to auto-select the first manager log service.",
            "severity": "Optional case-insensitive filter applied to LogEntry.Severity.",
            "since": "Optional ISO-8601 timestamp (example: 2026-08-11T12:00:00+00:00). Older entries are skipped.",
            "limit": "Maximum number of log entries to return.",
        },
    ),
    "get_firmware_inventory": ToolSpec(
        title="Get firmware inventory",
        description="Retrieve UpdateService firmware inventory members and return each firmware resource payload.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "limit": "Maximum number of firmware inventory members to fetch.",
        },
    ),
    "get_boot_config": ToolSpec(
        title="Get boot override configuration",
        description="Return the Boot section for a system so callers can inspect current override target, mode, and enablement.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "system_uri": "Target ComputerSystem URI. Omit to auto-select the first system.",
        },
    ),
    "get_bios_attributes": ToolSpec(
        title="Get BIOS attributes",
        description="Fetch BIOS attributes and the full BIOS resource for one system.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "system_uri": "Target ComputerSystem URI. Omit to auto-select the first system.",
        },
    ),
    "list_tasks": ToolSpec(
        title="List Redfish tasks",
        description="List TaskService task members and optionally include full task resource payloads.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "include_details": "True fetches each task resource; false returns only task URIs.",
        },
    ),
    "get_task": ToolSpec(
        title="Get one task resource",
        description="Fetch a task by URI or task_id; if omitted, the first task member is returned.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "task_id": "Task identifier appended to /redfish/v1/TaskService/Tasks/{task_id}.",
            "uri": "Explicit task resource URI to fetch.",
        },
    ),
    "list_accounts": ToolSpec(
        title="List account resources",
        description="List AccountService account members and optionally include full account payloads.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "include_details": "True fetches each account resource; false returns only account URIs.",
        },
    ),
    "list_virtual_media": ToolSpec(
        title="List virtual media devices",
        description="List VirtualMedia resources for a manager to inspect mounted images and media state.",
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "manager_uri": "Target manager URI. Omit to auto-select the first manager.",
        },
    ),
}

READ_TOOLSETS: dict[str, str] = {
    "list_endpoints": "discovery",
    "service_info": "discovery",
    "list_systems": "discovery",
    "get_system": "discovery",
    "list_chassis": "inventory",
    "get_chassis": "inventory",
    "list_managers": "inventory",
    "get_manager": "inventory",
    "get_health_summary": "health",
    "get_thermal": "sensors",
    "get_power": "sensors",
    "get_sensors": "sensors",
    "get_component_inventory": "inventory",
    "get_log_entries": "logs",
    "get_firmware_inventory": "firmware",
    "get_boot_config": "boot",
    "get_bios_attributes": "bios",
    "list_tasks": "tasks",
    "get_task": "tasks",
    "list_accounts": "accounts",
    "list_virtual_media": "virtualmedia",
}

READ_TOOL_RETURNS: dict[str, str] = {
    "list_endpoints": "Object containing an `endpoints` list with endpoint names, URLs, and default/read-only flags.",
    "service_info": "Object with `service_root`, `redfish_version`, `capabilities`, `links`, and resolved endpoint name.",
    "list_systems": "Object containing `collection_uri` and `systems` items with URIs and optional details."
    + LIST_ENVELOPE,
    "get_system": "Object with resolved `uri` and full `resource` payload for one ComputerSystem.",
    "list_chassis": "Object containing `collection_uri` and `chassis` items with URIs and optional details."
    + LIST_ENVELOPE,
    "get_chassis": "Object with resolved `uri` and full `resource` payload for one Chassis.",
    "list_managers": "Object containing `collection_uri` and `managers` items with URIs and optional details."
    + LIST_ENVELOPE,
    "get_manager": "Object with resolved `uri` and full `resource` payload for one Manager controller.",
    "get_health_summary": "Object with `groups` keyed by Systems/Chassis/Managers, each a list of per-member health and state rollups.",
    "get_thermal": "Object with `thermal_uri` plus full thermal resource payload.",
    "get_power": "Object with `power_uri` plus full power resource payload.",
    "get_sensors": "Object with `sensors_uri` and `sensors`, or `fallback` plus inline `temperatures`/`fans` arrays on services without a Sensors collection."
    + LIST_ENVELOPE,
    "get_component_inventory": "Object with `components` keyed by collection name, each carrying `uri`, `count`, `members` (descriptor fields when include_details is true, otherwise URI stubs), and `details_truncated`.",
    "get_log_entries": "Object with filtered `entries` and the endpoint plus chosen manager/log-service context."
    + LIST_ENVELOPE,
    "get_firmware_inventory": "Object with `firmware_inventory_uri` and firmware resources under `items`."
    + LIST_ENVELOPE,
    "get_boot_config": "Object with `system_uri` and current `boot` override configuration block.",
    "get_bios_attributes": "Object with BIOS `attributes`, `bios_uri`, and full BIOS resource payload.",
    "list_tasks": "Object with TaskService entries under `tasks` (URIs only or full task resources)."
    + LIST_ENVELOPE,
    "get_task": "Object with a single task payload under `task` and the resolved task URI.",
    "list_accounts": "Object with AccountService entries under `accounts` (URIs only or full account resources)."
    + LIST_ENVELOPE,
    "list_virtual_media": "Object with `manager_uri` and VirtualMedia resources under `virtual_media`."
    + LIST_ENVELOPE,
}

READ_TOOL_EXAMPLES: dict[str, str] = {
    "list_endpoints": "list_endpoints()",
    "service_info": "service_info(endpoint='default')",
    "list_systems": "list_systems(endpoint='default', include_details=true)",
    "get_system": "get_system(uri='/redfish/v1/Systems/1')",
    "list_chassis": "list_chassis(include_details=false)",
    "get_chassis": "get_chassis(uri='/redfish/v1/Chassis/1')",
    "list_managers": "list_managers(include_details=true)",
    "get_manager": "get_manager(uri='/redfish/v1/Managers/1')",
    "get_health_summary": "get_health_summary()",
    "get_thermal": "get_thermal(chassis_uri='/redfish/v1/Chassis/1')",
    "get_power": "get_power(chassis_uri='/redfish/v1/Chassis/1')",
    "get_sensors": "get_sensors(chassis_uri='/redfish/v1/Chassis/1', limit=100)",
    "get_component_inventory": "get_component_inventory(system_uri='/redfish/v1/Systems/1', include_details=true)",
    "get_log_entries": "get_log_entries(log_service_uri='/redfish/v1/Managers/1/LogServices/SEL', severity='Critical', limit=50)",
    "get_firmware_inventory": "get_firmware_inventory(limit=200)",
    "get_boot_config": "get_boot_config(system_uri='/redfish/v1/Systems/1')",
    "get_bios_attributes": "get_bios_attributes(system_uri='/redfish/v1/Systems/1')",
    "list_tasks": "list_tasks(include_details=true)",
    "get_task": "get_task(task_id='Task42')",
    "list_accounts": "list_accounts(include_details=false)",
    "list_virtual_media": "list_virtual_media(manager_uri='/redfish/v1/Managers/1')",
}


def register_read_tools(server: MCPServer, runtime: RedfishRuntime) -> None:
    """Register read-only tools."""
    index = runtime.schema_index

    tool_enum_refs: dict[str, dict[str, str]] = {
        "get_log_entries": {
            "severity": require_versioned_ref(index, "LogEntry", "EventSeverity"),
        },
    }

    tool_enum_values: dict[str, dict[str, list[str]]] = {
        "get_log_entries": {
            "severity": require_enum_values(index, tool_enum_refs["get_log_entries"]["severity"]),
        },
    }

    def tool(name: str) -> Callable[[ToolFunc], ToolFunc]:
        spec = READ_TOOL_SPECS[name]
        annotations = ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=spec.open_world_hint,
        )

        def decorator(fn: ToolFunc) -> ToolFunc:
            toolset = spec.toolset or READ_TOOLSETS[name]
            rule = ToolRegistrationRule(name=name, toolset=toolset)
            if not runtime.safety.can_register(rule):
                return fn
            returns_hint = spec.returns or READ_TOOL_RETURNS[name]
            example_hint = spec.example or READ_TOOL_EXAMPLES[name]
            description = f"{spec.description} Returns: {returns_hint} Example: {example_hint}"
            register_tool(
                server,
                fn,
                name=name,
                title=spec.title,
                description=description,
                annotations=annotations,
                param_descriptions=build_enum_param_descriptions(
                    index, spec.param_descriptions, tool_enum_refs.get(name, {})
                ),
                enum_values=tool_enum_values.get(name),
            )
            return fn

        return decorator

    @tool("list_endpoints")
    async def list_endpoints() -> dict[str, Any]:
        endpoints = []
        for endpoint in runtime.config.endpoints.values():
            endpoints.append(
                {
                    "name": endpoint.name,
                    "base_url": endpoint.base_url,
                    "verify_ssl": endpoint.verify_ssl,
                    "read_only": endpoint.read_only,
                    "auth_mode": endpoint.auth_mode.value,
                    "default": endpoint.name == runtime.config.default_endpoint,
                }
            )
        return {"endpoints": endpoints}

    @tool("service_info")
    async def service_info(endpoint: str | None = None) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            root, caps = await runtime.capabilities.get(client)
            return {
                "endpoint": client.endpoint.name,
                "service_root": compact_resource(root),
                "redfish_version": caps.redfish_version,
                "capabilities": {
                    "expand_query": caps.expand_query,
                    "select_query": caps.select_query,
                    "only_query": caps.only_query,
                    "excerpt_query": caps.excerpt_query,
                    "filter_query": caps.filter_query,
                    "max_expand_levels": caps.max_expand_levels,
                },
                "links": caps.links,
            }

    @tool("list_systems")
    async def list_systems(
        endpoint: str | None = None, include_details: bool = True
    ) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            root = await client.get_json("/redfish/v1")
            systems_uri = _link_uri(root, "Systems", "/redfish/v1/Systems")
            members = await collect_members(client.get_json, systems_uri, limit=500)
            items: list[dict[str, Any]] = []
            for member in members:
                uri = member.get("@odata.id")
                if not isinstance(uri, str):
                    continue
                if include_details:
                    system = await client.get_json(uri)
                    items.append(
                        {
                            "uri": uri,
                            "resource": compact_resource(system),
                            "status": _extract_status(system),
                        }
                    )
                else:
                    items.append({"uri": uri})
            return {
                "endpoint": client.endpoint.name,
                "collection_uri": systems_uri,
                "systems": maybe_truncate_list(items),
            }

    @tool("get_system")
    async def get_system(
        endpoint: str | None = None,
        system_id: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            target = uri or (f"/redfish/v1/Systems/{system_id}" if system_id else None)
            if target is None:
                root = await client.get_json("/redfish/v1")
                systems_uri = _link_uri(root, "Systems", "/redfish/v1/Systems")
                first = await _first_collection_member_uri(client, systems_uri)
                if first is None:
                    raise ValueError("no systems found")
                target = first
            payload = await client.get_json(target)
            return {"endpoint": client.endpoint.name, "uri": target, "resource": payload}

    @tool("list_chassis")
    async def list_chassis(
        endpoint: str | None = None, include_details: bool = True
    ) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            root = await client.get_json("/redfish/v1")
            chassis_uri = _link_uri(root, "Chassis", "/redfish/v1/Chassis")
            members = await collect_members(client.get_json, chassis_uri, limit=500)
            items: list[dict[str, Any]] = []
            for member in members:
                uri = member.get("@odata.id")
                if not isinstance(uri, str):
                    continue
                if include_details:
                    chassis = await client.get_json(uri)
                    items.append(
                        {
                            "uri": uri,
                            "resource": compact_resource(chassis),
                            "status": _extract_status(chassis),
                        }
                    )
                else:
                    items.append({"uri": uri})
            return {
                "endpoint": client.endpoint.name,
                "collection_uri": chassis_uri,
                "chassis": maybe_truncate_list(items),
            }

    @tool("get_chassis")
    async def get_chassis(
        endpoint: str | None = None,
        chassis_id: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            target = uri or (f"/redfish/v1/Chassis/{chassis_id}" if chassis_id else None)
            if target is None:
                root = await client.get_json("/redfish/v1")
                collection_uri = _link_uri(root, "Chassis", "/redfish/v1/Chassis")
                target = await _first_collection_member_uri(client, collection_uri)
                if target is None:
                    raise ValueError("no chassis found")
            payload = await client.get_json(target)
            return {"endpoint": client.endpoint.name, "uri": target, "resource": payload}

    @tool("list_managers")
    async def list_managers(
        endpoint: str | None = None, include_details: bool = True
    ) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            root = await client.get_json("/redfish/v1")
            managers_uri = _link_uri(root, "Managers", "/redfish/v1/Managers")
            members = await collect_members(client.get_json, managers_uri, limit=500)
            items: list[dict[str, Any]] = []
            for member in members:
                uri = member.get("@odata.id")
                if not isinstance(uri, str):
                    continue
                if include_details:
                    manager = await client.get_json(uri)
                    items.append(
                        {
                            "uri": uri,
                            "resource": compact_resource(manager),
                            "status": _extract_status(manager),
                        }
                    )
                else:
                    items.append({"uri": uri})
            return {
                "endpoint": client.endpoint.name,
                "collection_uri": managers_uri,
                "managers": maybe_truncate_list(items),
            }

    @tool("get_manager")
    async def get_manager(
        endpoint: str | None = None,
        manager_id: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            target = uri or (f"/redfish/v1/Managers/{manager_id}" if manager_id else None)
            if target is None:
                root = await client.get_json("/redfish/v1")
                collection_uri = _link_uri(root, "Managers", "/redfish/v1/Managers")
                target = await _first_collection_member_uri(client, collection_uri)
                if target is None:
                    raise ValueError("no managers found")
            payload = await client.get_json(target)
            return {"endpoint": client.endpoint.name, "uri": target, "resource": payload}

    @tool("get_health_summary")
    async def get_health_summary(endpoint: str | None = None) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            root = await client.get_json("/redfish/v1")
            summary: dict[str, Any] = {"endpoint": client.endpoint.name, "groups": {}}
            for key, fallback in (
                ("Systems", "/redfish/v1/Systems"),
                ("Chassis", "/redfish/v1/Chassis"),
                ("Managers", "/redfish/v1/Managers"),
            ):
                collection_uri = _link_uri(root, key, fallback)
                members = await collect_members(client.get_json, collection_uri, limit=100)
                group_items: list[dict[str, Any]] = []
                for member in members:
                    uri = member.get("@odata.id")
                    if not isinstance(uri, str):
                        continue
                    resource = await client.get_json(uri)
                    group_items.append(
                        {
                            "uri": uri,
                            "name": resource.get("Name") or resource.get("Id"),
                            "status": _extract_status(resource),
                        }
                    )
                summary["groups"][key] = group_items
            return summary

    @tool("get_thermal")
    async def get_thermal(
        endpoint: str | None = None,
        chassis_uri: str | None = None,
    ) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            if chassis_uri is None:
                root = await client.get_json("/redfish/v1")
                collection_uri = _link_uri(root, "Chassis", "/redfish/v1/Chassis")
                chassis_uri = await _first_collection_member_uri(client, collection_uri)
                if chassis_uri is None:
                    raise ValueError("no chassis found")
            chassis = await client.get_json(chassis_uri)
            target_uri = None
            for key in ("ThermalSubsystem", "Thermal"):
                value = chassis.get(key)
                if isinstance(value, dict) and isinstance(value.get("@odata.id"), str):
                    target_uri = value["@odata.id"]
                    break
            if target_uri is None:
                raise ValueError("no thermal or thermal subsystem link on chassis")
            payload = await client.get_json(target_uri)
            return {
                "endpoint": client.endpoint.name,
                "chassis_uri": chassis_uri,
                "thermal_uri": target_uri,
                "resource": payload,
            }

    @tool("get_power")
    async def get_power(
        endpoint: str | None = None,
        chassis_uri: str | None = None,
    ) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            if chassis_uri is None:
                root = await client.get_json("/redfish/v1")
                collection_uri = _link_uri(root, "Chassis", "/redfish/v1/Chassis")
                chassis_uri = await _first_collection_member_uri(client, collection_uri)
                if chassis_uri is None:
                    raise ValueError("no chassis found")
            chassis = await client.get_json(chassis_uri)
            target_uri = None
            for key in ("PowerSubsystem", "Power"):
                value = chassis.get(key)
                if isinstance(value, dict) and isinstance(value.get("@odata.id"), str):
                    target_uri = value["@odata.id"]
                    break
            if target_uri is None:
                raise ValueError("no power or power subsystem link on chassis")
            payload = await client.get_json(target_uri)
            return {
                "endpoint": client.endpoint.name,
                "chassis_uri": chassis_uri,
                "power_uri": target_uri,
                "resource": payload,
            }

    @tool("get_sensors")
    async def get_sensors(
        endpoint: str | None = None,
        chassis_uri: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            if chassis_uri is None:
                root = await client.get_json("/redfish/v1")
                collection_uri = _link_uri(root, "Chassis", "/redfish/v1/Chassis")
                chassis_uri = await _first_collection_member_uri(client, collection_uri)
                if chassis_uri is None:
                    raise ValueError("no chassis found")
            chassis = await client.get_json(chassis_uri)
            sensors_link = chassis.get("Sensors")
            if isinstance(sensors_link, dict) and isinstance(sensors_link.get("@odata.id"), str):
                sensors_uri = sensors_link["@odata.id"]
                sensor_uris = []
                async for uri in iter_member_uris(client.get_json, sensors_uri):
                    sensor_uris.append(uri)
                    if len(sensor_uris) >= limit:
                        break
                sensors = [await client.get_json(uri) for uri in sensor_uris]
                return {
                    "endpoint": client.endpoint.name,
                    "sensors_uri": sensors_uri,
                    "sensors": maybe_truncate_list(sensors, max_items=limit),
                }
            # fallback to deprecated Thermal inline arrays
            thermal_info = await get_thermal(endpoint=client.endpoint.name, chassis_uri=chassis_uri)
            resource = thermal_info["resource"]
            temperatures = resource.get("Temperatures", []) if isinstance(resource, dict) else []
            fans = resource.get("Fans", []) if isinstance(resource, dict) else []
            return {
                "endpoint": client.endpoint.name,
                "fallback": "thermal-inline",
                "temperatures": temperatures,
                "fans": fans,
            }

    @tool("get_component_inventory")
    async def get_component_inventory(
        endpoint: str | None = None,
        system_uri: str | None = None,
        include_details: bool = True,
    ) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            if system_uri is None:
                root = await client.get_json("/redfish/v1")
                systems_uri = _link_uri(root, "Systems", "/redfish/v1/Systems")
                system_uri = await _first_collection_member_uri(client, systems_uri)
                if system_uri is None:
                    raise ValueError("no systems found")
            system = await client.get_json(system_uri)
            categories = ("Processors", "Memory", "Storage", "EthernetInterfaces", "PCIeDevices")
            inventory: dict[str, Any] = {
                "endpoint": client.endpoint.name,
                "system_uri": system_uri,
                "components": {},
            }
            for category in categories:
                value = system.get(category)
                if not isinstance(value, dict) or not isinstance(value.get("@odata.id"), str):
                    continue
                uri = value["@odata.id"]
                members = await collect_members(client.get_json, uri, limit=500)
                entry: dict[str, Any] = {"uri": uri, "count": len(members)}
                if include_details:
                    # Each detail is a separate GET against the BMC, so the fan-out is bounded
                    # rather than left to the size of the collection.
                    detailed: list[dict[str, Any]] = []
                    for member in members[:COMPONENT_DETAIL_LIMIT]:
                        member_uri = member.get("@odata.id")
                        if not isinstance(member_uri, str):
                            continue
                        detailed.append(compact_component(await client.get_json(member_uri)))
                    entry["members"] = detailed
                    entry["details_truncated"] = len(members) > COMPONENT_DETAIL_LIMIT
                else:
                    entry["members"] = members
                inventory["components"][category] = entry
            return inventory

    @tool("get_log_entries")
    async def get_log_entries(
        endpoint: str | None = None,
        manager_uri: str | None = None,
        log_service_uri: str | None = None,
        severity: str | None = None,
        since: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        since_dt = datetime.fromisoformat(since) if since else None
        async with runtime.client_for(endpoint) as client:
            selected_services: list[str] = []
            if log_service_uri:
                selected_services = [log_service_uri]
            else:
                if manager_uri is None:
                    root = await client.get_json("/redfish/v1")
                    managers_uri = _link_uri(root, "Managers", "/redfish/v1/Managers")
                    manager_uri = await _first_collection_member_uri(client, managers_uri)
                    if manager_uri is None:
                        raise ValueError("no manager found for log retrieval")
                manager = await client.get_json(manager_uri)
                log_services = manager.get("LogServices")
                if not isinstance(log_services, dict) or not isinstance(
                    log_services.get("@odata.id"), str
                ):
                    raise ValueError("manager does not expose LogServices")
                log_services_uri = log_services["@odata.id"]
                service_members = await collect_members(client.get_json, log_services_uri, limit=20)
                for service in service_members:
                    service_uri = service.get("@odata.id")
                    if isinstance(service_uri, str):
                        selected_services.append(service_uri)
            entries: list[dict[str, Any]] = []
            for service_uri in selected_services:
                service_resource = await client.get_json(service_uri)
                entries_link = service_resource.get("Entries")
                if not isinstance(entries_link, dict) or not isinstance(
                    entries_link.get("@odata.id"), str
                ):
                    continue
                entry_collection_uri = entries_link["@odata.id"]
                members = await collect_members(client.get_json, entry_collection_uri, limit=limit)
                for member in members:
                    entry_uri = member.get("@odata.id")
                    if not isinstance(entry_uri, str):
                        continue
                    entry = await client.get_json(entry_uri)
                    if severity and str(entry.get("Severity", "")).lower() != severity.lower():
                        continue
                    if since_dt:
                        created = entry.get("Created")
                        if isinstance(created, str):
                            try:
                                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                            except ValueError:
                                created_dt = None
                            if created_dt and created_dt < since_dt:
                                continue
                    entries.append(entry)
                    if len(entries) >= limit:
                        return {
                            "endpoint": client.endpoint.name,
                            "manager_uri": manager_uri,
                            "log_service_uri": log_service_uri,
                            "log_services_scanned": selected_services,
                            "entries": maybe_truncate_list(entries, max_items=limit),
                        }
            return {
                "endpoint": client.endpoint.name,
                "manager_uri": manager_uri,
                "log_service_uri": log_service_uri,
                "log_services_scanned": selected_services,
                "entries": maybe_truncate_list(entries, max_items=limit),
            }

    @tool("get_firmware_inventory")
    async def get_firmware_inventory(
        endpoint: str | None = None, limit: int = 500
    ) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            root = await client.get_json("/redfish/v1")
            update_service = root.get("UpdateService")
            if not isinstance(update_service, dict) or not isinstance(
                update_service.get("@odata.id"), str
            ):
                raise ValueError("service does not expose UpdateService")
            update = await client.get_json(update_service["@odata.id"])
            fw = update.get("FirmwareInventory")
            if not isinstance(fw, dict) or not isinstance(fw.get("@odata.id"), str):
                raise ValueError("UpdateService does not expose FirmwareInventory")
            members = await collect_members(client.get_json, fw["@odata.id"], limit=limit)
            inventory = []
            for member in members:
                uri = member.get("@odata.id")
                if isinstance(uri, str):
                    inventory.append(await client.get_json(uri))
            return {
                "endpoint": client.endpoint.name,
                "firmware_inventory_uri": fw["@odata.id"],
                "items": maybe_truncate_list(inventory, max_items=limit),
            }

    @tool("get_boot_config")
    async def get_boot_config(
        endpoint: str | None = None,
        system_uri: str | None = None,
    ) -> dict[str, Any]:
        system = await get_system(endpoint=endpoint, uri=system_uri)
        resource = system["resource"]
        boot = resource.get("Boot") if isinstance(resource, dict) else None
        return {
            "endpoint": system["endpoint"],
            "system_uri": system["uri"],
            "boot": boot,
        }

    @tool("get_bios_attributes")
    async def get_bios_attributes(
        endpoint: str | None = None,
        system_uri: str | None = None,
    ) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            system_info = await get_system(endpoint=client.endpoint.name, uri=system_uri)
            resource = system_info["resource"]
            bios_link = resource.get("Bios") if isinstance(resource, dict) else None
            if not isinstance(bios_link, dict) or not isinstance(bios_link.get("@odata.id"), str):
                raise ValueError("system does not expose Bios link")
            bios = await client.get_json(bios_link["@odata.id"])
            return {
                "endpoint": client.endpoint.name,
                "system_uri": system_info["uri"],
                "bios_uri": bios_link["@odata.id"],
                "attributes": bios.get("Attributes"),
                "resource": bios,
            }

    @tool("list_tasks")
    async def list_tasks(
        endpoint: str | None = None, include_details: bool = True
    ) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            root = await client.get_json("/redfish/v1")
            task_service_link = root.get("TaskService")
            if not isinstance(task_service_link, dict) or not isinstance(
                task_service_link.get("@odata.id"), str
            ):
                raise ValueError("service does not expose TaskService")
            task_service = await client.get_json(task_service_link["@odata.id"])
            tasks_link = task_service.get("Tasks")
            if not isinstance(tasks_link, dict) or not isinstance(tasks_link.get("@odata.id"), str):
                raise ValueError("TaskService does not expose Tasks collection")
            members = await collect_members(client.get_json, tasks_link["@odata.id"], limit=500)
            items: list[dict[str, Any]] = []
            for member in members:
                uri = member.get("@odata.id")
                if not isinstance(uri, str):
                    continue
                if include_details:
                    payload = await client.get_json(uri)
                    items.append(payload)
                else:
                    items.append({"@odata.id": uri})
            return {"endpoint": client.endpoint.name, "tasks": maybe_truncate_list(items)}

    @tool("get_task")
    async def get_task(
        endpoint: str | None = None,
        task_id: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            target = uri or (f"/redfish/v1/TaskService/Tasks/{task_id}" if task_id else None)
            if target is None:
                tasks = await list_tasks(endpoint=client.endpoint.name, include_details=False)
                items = tasks["tasks"]["items"]
                if not items:
                    raise ValueError("no tasks found")
                target = items[0]["@odata.id"]
            payload = await client.get_json(target)
            return {"endpoint": client.endpoint.name, "uri": target, "task": payload}

    @tool("list_accounts")
    async def list_accounts(
        endpoint: str | None = None, include_details: bool = True
    ) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            root = await client.get_json("/redfish/v1")
            account_service = root.get("AccountService")
            if not isinstance(account_service, dict) or not isinstance(
                account_service.get("@odata.id"), str
            ):
                raise ValueError("service does not expose AccountService")
            account_svc = await client.get_json(account_service["@odata.id"])
            accounts = account_svc.get("Accounts")
            if not isinstance(accounts, dict) or not isinstance(accounts.get("@odata.id"), str):
                raise ValueError("AccountService does not expose Accounts collection")
            members = await collect_members(client.get_json, accounts["@odata.id"], limit=500)
            items: list[dict[str, Any]] = []
            for member in members:
                uri = member.get("@odata.id")
                if not isinstance(uri, str):
                    continue
                if include_details:
                    items.append(await client.get_json(uri))
                else:
                    items.append({"@odata.id": uri})
            return {"endpoint": client.endpoint.name, "accounts": maybe_truncate_list(items)}

    @tool("list_virtual_media")
    async def list_virtual_media(
        endpoint: str | None = None, manager_uri: str | None = None
    ) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            if manager_uri is None:
                root = await client.get_json("/redfish/v1")
                managers_uri = _link_uri(root, "Managers", "/redfish/v1/Managers")
                manager_uri = await _first_collection_member_uri(client, managers_uri)
                if manager_uri is None:
                    raise ValueError("no manager found")
            manager = await client.get_json(manager_uri)
            vm = manager.get("VirtualMedia")
            if not isinstance(vm, dict) or not isinstance(vm.get("@odata.id"), str):
                raise ValueError("manager does not expose VirtualMedia collection")
            members = await collect_members(client.get_json, vm["@odata.id"], limit=100)
            resources: list[dict[str, Any]] = []
            for member in members:
                uri = member.get("@odata.id")
                if isinstance(uri, str):
                    resources.append(await client.get_json(uri))
            return {
                "endpoint": client.endpoint.name,
                "manager_uri": manager_uri,
                "virtual_media": maybe_truncate_list(resources),
            }
