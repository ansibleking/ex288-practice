"""Mutating MCP tools with tiered safety gates and dry-run previews."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from mirastack_redfish_mcp.redfish.actions import (
    ActionInstance,
    extract_action_instance,
    merge_action_info,
)
from mirastack_redfish_mcp.redfish.settings import resolve_settings_target
from mirastack_redfish_mcp.runtime import RedfishRuntime
from mirastack_redfish_mcp.safety import RequiredTier, ToolRegistrationRule
from mirastack_redfish_mcp.schema.docs import enum_help
from mirastack_redfish_mcp.schema.enums import require_enum_values, require_versioned_ref
from mirastack_redfish_mcp.tools.read import _first_collection_member_uri, _link_uri
from mirastack_redfish_mcp.tools.registration import build_enum_param_descriptions, register_tool

ToolFunc = TypeVar("ToolFunc", bound=Callable[..., Any])

CONFIRM_SUFFIX = (
    " Returns a preview when confirm is false; nothing is changed until you call it again "
    "with confirm=true."
)


@dataclass(frozen=True)
class ToolSpec:
    title: str
    description: str
    destructive: bool
    idempotent: bool
    param_descriptions: dict[str, str] = field(default_factory=dict)
    toolset: str = ""
    required_tier: RequiredTier | None = None
    returns: str = ""
    example: str = ""
    param_examples: dict[str, list[Any]] = field(default_factory=dict)


WRITE_TOOL_SPECS: dict[str, ToolSpec] = {
    "set_power_state": ToolSpec(
        title="Set system power state",
        description=(
            "Invoke ComputerSystem.Reset with a ResetType value to power on, power off, "
            "or reset a system."
            + CONFIRM_SUFFIX
        ),
        destructive=True,
        idempotent=False,
        param_descriptions={
            "reset_type": "Redfish ResetType value for ComputerSystem.Reset.",
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "system_uri": "Target ComputerSystem URI. Omit to auto-select the first system.",
            "confirm": "Set true to apply the mutation. False returns a dry-run preview only.",
        },
    ),
    "set_boot_override": ToolSpec(
        title="Set one-time or continuous boot override",
        description=(
            "PATCH the Boot section of a system to set override target, enablement, and mode."
            + CONFIRM_SUFFIX
        ),
        destructive=False,
        idempotent=True,
        param_descriptions={
            "target": "BootSourceOverrideTarget value. Send the literal string \"None\" (not JSON null) to boot from the normal boot device.",
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "system_uri": "Target ComputerSystem URI. Omit to auto-select the first system.",
            "enabled": "BootSourceOverrideEnabled value.",
            "mode": "BootSourceOverrideMode value when supported by firmware.",
            "confirm": "Set true to apply the mutation. False returns a dry-run preview only.",
        },
    ),
    "reset_manager": ToolSpec(
        title="Reset manager controller",
        description=(
            "Invoke Manager.Reset on a manager controller to restart or power-cycle BMC services."
            + CONFIRM_SUFFIX
        ),
        destructive=True,
        idempotent=False,
        param_descriptions={
            "reset_type": "Redfish ResetType value for Manager.Reset.",
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "manager_uri": "Target Manager URI. Omit to auto-select the first manager.",
            "confirm": "Set true to apply the mutation. False returns a dry-run preview only.",
        },
    ),
    "cancel_task": ToolSpec(
        title="Cancel or delete task",
        description=(
            "DELETE a Task resource URI to cancel or remove an in-progress/queued task entry."
            + CONFIRM_SUFFIX
        ),
        destructive=True,
        idempotent=False,
        param_descriptions={
            "task_uri": "Task resource URI under /redfish/v1/TaskService/Tasks/...",
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "confirm": "Set true to apply the mutation. False returns a dry-run preview only.",
        },
    ),
    "set_bios_attributes": ToolSpec(
        title="Set BIOS attributes",
        description=(
            "PATCH BIOS SettingsObject Attributes using @Redfish.Settings indirection. "
            "Attributes are staged on the settings object and take effect at the next system "
            "reset, not immediately."
            + CONFIRM_SUFFIX
        ),
        # The attribute map is caller-chosen and vendor-defined, and a bad value can leave the
        # system unbootable, so this carries the same warning as the raw PATCH escape hatch.
        destructive=True,
        idempotent=True,
        param_descriptions={
            "attributes": "BIOS attribute map to apply to the settings object. Call get_bios_attributes first to list valid attribute names for this vendor.",
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "system_uri": "Target ComputerSystem URI. Omit to auto-select the first system.",
            "confirm": "Set true to apply the mutation. False returns a dry-run preview only.",
        },
    ),
    "insert_virtual_media": ToolSpec(
        title="Insert virtual media image",
        description=(
            "Attach an image to a VirtualMedia device, preferring VirtualMedia.InsertMedia action and falling back to PATCH. "
            "Mounting does not change boot order; a boot override is required to boot the image."
            + CONFIRM_SUFFIX
        ),
        destructive=False,
        idempotent=True,
        param_descriptions={
            "image": "Image URI to mount on the virtual media device.",
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "virtual_media_uri": "Target VirtualMedia URI. Omit to auto-select the first manager media device.",
            "inserted": "Whether the media should be inserted/visible to host after operation.",
            "write_protected": "Whether inserted media should be write-protected.",
            "confirm": "Set true to apply the mutation. False returns a dry-run preview only.",
        },
    ),
    "eject_virtual_media": ToolSpec(
        title="Eject virtual media image",
        description=(
            "Detach media from a VirtualMedia device, preferring VirtualMedia.EjectMedia action and falling back to PATCH."
            + CONFIRM_SUFFIX
        ),
        destructive=False,
        idempotent=True,
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "virtual_media_uri": "Target VirtualMedia URI. Omit to auto-select the first manager media device.",
            "confirm": "Set true to apply the mutation. False returns a dry-run preview only.",
        },
    ),
    "clear_logs": ToolSpec(
        title="Clear log service entries",
        description=(
            "Invoke LogService.ClearLog to delete entries from a selected log service."
            + CONFIRM_SUFFIX
        ),
        destructive=True,
        idempotent=False,
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "log_service_uri": "Target LogService URI. Omit to auto-select the first manager log service.",
            "confirm": "Set true to apply the mutation. False returns a dry-run preview only.",
        },
    ),
    "manage_account": ToolSpec(
        title="Create, patch, or delete account",
        description=(
            "Create, update, or delete AccountService account resources using operation=create|patch|delete."
            + CONFIRM_SUFFIX
        ),
        destructive=True,
        idempotent=False,
        param_descriptions={
            "operation": "Account operation: create, patch, or delete.",
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "account_uri": "Account resource URI for patch/delete operations.",
            "body": "Request payload for create or patch operations.",
            "confirm": "Set true to apply the mutation. False returns a dry-run preview only.",
        },
    ),
    "simple_update": ToolSpec(
        title="Run SimpleUpdate firmware flow",
        description=(
            "Invoke UpdateService.SimpleUpdate with image URI and optional transfer protocol/targets."
            + CONFIRM_SUFFIX
        ),
        destructive=True,
        idempotent=False,
        param_descriptions={
            "image_uri": "Image URI for UpdateService.SimpleUpdate.",
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "transfer_protocol": "Optional TransferProtocol value for image retrieval.",
            "targets": "Optional list of target URIs for multi-device update.",
            "confirm": "Set true to apply the mutation. False returns a dry-run preview only.",
        },
    ),
    "reset_to_defaults": ToolSpec(
        title="Reset manager to defaults",
        description=(
            "Invoke Manager.ResetToDefaults with ResetType to revert configuration settings."
            + CONFIRM_SUFFIX
        ),
        destructive=True,
        idempotent=False,
        param_descriptions={
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "manager_uri": "Target Manager URI. Omit to auto-select the first manager.",
            "reset_type": "ResetType value for Manager.ResetToDefaults.",
            "confirm": "Set true to apply the mutation. False returns a dry-run preview only.",
        },
    ),
    "redfish_patch": ToolSpec(
        title="Raw Redfish PATCH",
        description=(
            "Escape hatch: use when no typed mutation tool applies. Execute a raw PATCH against any Redfish URI with explicit tier gating."
            + CONFIRM_SUFFIX
        ),
        # The URI and body are entirely caller-chosen, so this cannot be advertised as
        # non-destructive even though PATCH itself is idempotent.
        destructive=True,
        idempotent=True,
        param_descriptions={
            "uri": "Target URI to patch.",
            "body": "JSON object payload for PATCH.",
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "tier": "Minimum required write tier: power, config, or full.",
            "confirm": "Set true to apply the mutation. False returns a dry-run preview only.",
        },
    ),
    "redfish_post": ToolSpec(
        title="Raw Redfish POST",
        description=(
            "Escape hatch: use when no typed mutation tool applies. Execute a raw POST against any Redfish URI with explicit tier gating."
            + CONFIRM_SUFFIX
        ),
        destructive=True,
        idempotent=False,
        param_descriptions={
            "uri": "Target URI to post to.",
            "body": "Optional JSON object payload for POST.",
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "tier": "Minimum required write tier: power, config, or full.",
            "confirm": "Set true to apply the mutation. False returns a dry-run preview only.",
        },
    ),
    "redfish_delete": ToolSpec(
        title="Raw Redfish DELETE",
        description=(
            "Escape hatch: use when no typed mutation tool applies. Execute a raw DELETE against any Redfish URI with explicit tier gating."
            + CONFIRM_SUFFIX
        ),
        destructive=True,
        idempotent=False,
        param_descriptions={
            "uri": "Target URI to delete.",
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "tier": "Minimum required write tier: power, config, or full.",
            "confirm": "Set true to apply the mutation. False returns a dry-run preview only.",
        },
    ),
    "redfish_invoke_action": ToolSpec(
        title="Raw Redfish action invoke",
        description=(
            "Escape hatch: prefer typed tools first, and call redfish_list_available_actions before invoking unfamiliar actions. Invoke any action exposed in a resource Actions block using action_name and payload."
            + CONFIRM_SUFFIX
        ),
        destructive=True,
        idempotent=False,
        param_descriptions={
            "resource_uri": "Resource URI exposing the target action in its Actions block.",
            "action_name": "Action name such as ComputerSystem.Reset (with or without leading #).",
            "payload": "Optional JSON object payload for action parameters.",
            "endpoint": "Configured endpoint name. Omit to use the default endpoint.",
            "tier": "Minimum required write tier: power, config, or full.",
            "confirm": "Set true to apply the mutation. False returns a dry-run preview only.",
        },
    ),
}

WRITE_TOOLSETS: dict[str, str] = {
    "set_power_state": "power",
    "set_boot_override": "boot",
    "reset_manager": "power",
    "cancel_task": "tasks",
    "set_bios_attributes": "bios",
    "insert_virtual_media": "virtualmedia",
    "eject_virtual_media": "virtualmedia",
    "clear_logs": "logs",
    "manage_account": "accounts",
    "simple_update": "firmware",
    "reset_to_defaults": "write",
    "redfish_patch": "write",
    "redfish_post": "write",
    "redfish_delete": "write",
    "redfish_invoke_action": "write",
}

WRITE_REQUIRED_TIERS: dict[str, RequiredTier] = {
    "set_power_state": RequiredTier.POWER,
    "set_boot_override": RequiredTier.POWER,
    "reset_manager": RequiredTier.POWER,
    "cancel_task": RequiredTier.POWER,
    "set_bios_attributes": RequiredTier.CONFIG,
    "insert_virtual_media": RequiredTier.FULL,
    "eject_virtual_media": RequiredTier.CONFIG,
    "clear_logs": RequiredTier.FULL,
    "manage_account": RequiredTier.FULL,
    "simple_update": RequiredTier.FULL,
    "reset_to_defaults": RequiredTier.FULL,
    "redfish_patch": RequiredTier.CONFIG,
    "redfish_post": RequiredTier.CONFIG,
    "redfish_delete": RequiredTier.CONFIG,
    "redfish_invoke_action": RequiredTier.CONFIG,
}

WRITE_TOOL_RETURNS: dict[str, str] = {
    "set_power_state": "Action result for ComputerSystem.Reset, or dry-run metadata when confirm=false.",
    "set_boot_override": "PATCH result for the target system Boot section, or dry-run metadata when confirm=false.",
    "reset_manager": "Action result for Manager.Reset, or dry-run metadata when confirm=false.",
    "cancel_task": "DELETE result for the target task URI, or dry-run metadata when confirm=false.",
    "set_bios_attributes": "PATCH result to BIOS settings URI plus BIOS/settings context, or dry-run metadata.",
    "insert_virtual_media": "InsertMedia action result (or PATCH fallback result) with target URI context.",
    "eject_virtual_media": "EjectMedia action result (or PATCH fallback result) with target URI context.",
    "clear_logs": "Action result for LogService.ClearLog, or dry-run metadata when confirm=false.",
    "manage_account": "Create/patch/delete account result for AccountService, or dry-run metadata.",
    "simple_update": "UpdateService.SimpleUpdate action result, often with task context for async updates.",
    "reset_to_defaults": "Action result for Manager.ResetToDefaults, or dry-run metadata when confirm=false.",
    "redfish_patch": "Raw PATCH result from the target URI, or dry-run metadata with payload preview.",
    "redfish_post": "Raw POST result from the target URI, or dry-run metadata with payload preview.",
    "redfish_delete": "Raw DELETE result from the target URI, or dry-run metadata with payload preview.",
    "redfish_invoke_action": "Action result for the named action target, or dry-run metadata with payload preview.",
}

WRITE_TOOL_EXAMPLES: dict[str, str] = {
    "set_power_state": "set_power_state(reset_type='GracefulRestart', system_uri='/redfish/v1/Systems/1', confirm=false)",
    "set_boot_override": "set_boot_override(target='Pxe', enabled='Once', system_uri='/redfish/v1/Systems/1', confirm=false)",
    "reset_manager": "reset_manager(reset_type='GracefulRestart', manager_uri='/redfish/v1/Managers/1', confirm=false)",
    "cancel_task": "cancel_task(task_uri='/redfish/v1/TaskService/Tasks/42', confirm=false)",
    "set_bios_attributes": "set_bios_attributes(attributes={'<VendorAttributeName>':'<ValueFromGetBiosAttributes>'}, confirm=false)",
    "insert_virtual_media": "insert_virtual_media(image='https://repo/os.iso', confirm=false)",
    "eject_virtual_media": "eject_virtual_media(virtual_media_uri='/redfish/v1/Managers/1/VirtualMedia/CD1', confirm=false)",
    "clear_logs": "clear_logs(log_service_uri='/redfish/v1/Managers/1/LogServices/SEL', confirm=false)",
    "manage_account": "manage_account(operation='create', body={'UserName':'ops-admin','RoleId':'Administrator'}, confirm=false)",
    "simple_update": "simple_update(image_uri='https://repo/fw.bin', transfer_protocol='HTTPS', confirm=false)",
    "reset_to_defaults": "reset_to_defaults(manager_uri='/redfish/v1/Managers/1', reset_type='ResetAll', confirm=false)",
    "redfish_patch": "redfish_patch(uri='/redfish/v1/Systems/1', body={'AssetTag':'rack12-u3'}, tier='config', confirm=false)",
    "redfish_post": "redfish_post(uri='/redfish/v1/Systems/1/Actions/ComputerSystem.Reset', body={'ResetType':'On'}, confirm=false)",
    "redfish_delete": "redfish_delete(uri='/redfish/v1/TaskService/Tasks/42', tier='power', confirm=false)",
    "redfish_invoke_action": "redfish_invoke_action(resource_uri='/redfish/v1/Systems/1', action_name='ComputerSystem.Reset', confirm=false)",
}

WRITE_TOOL_PARAM_EXAMPLES: dict[str, dict[str, list[Any]]] = {
    "set_bios_attributes": {
        "attributes": [{"<VendorAttributeName>": "<ValueFromGetBiosAttributes>"}],
    },
    "manage_account": {
        "body": [
            {
                "UserName": "ops-admin",
                "Password": "<StrongPassword>",
                "RoleId": "Administrator",
                "Enabled": True,
            }
        ]
    },
    "redfish_patch": {
        "body": [{"Boot": {"BootSourceOverrideEnabled": "Once", "BootSourceOverrideTarget": "Pxe"}}]
    },
    "redfish_post": {"body": [{"ResetType": "GracefulRestart"}]},
    "redfish_invoke_action": {"payload": [{"ResetType": "GracefulRestart"}]},
}

EXAMPLE_PROPERTY_ASSERTIONS: list[dict[str, Any]] = [
    {
        "tool": "manage_account",
        "parameter": "body",
        "resource_type": "ManagerAccount",
        "properties": ["UserName", "Password", "RoleId", "Enabled"],
    },
    {
        "tool": "redfish_patch",
        "parameter": "body",
        "resource_type": "ComputerSystem",
        "properties": ["Boot", "AssetTag"],
    },
]


def _normalize_uri(uri: str) -> str:
    return uri if uri.startswith("/") or uri.startswith("http") else f"/{uri}"


def _normalize_action_key(action_name: str) -> str:
    return action_name if action_name.startswith("#") else f"#{action_name}"


def _resolve_schema_action(
    runtime: RedfishRuntime, resource_uri: str, action_name: str
) -> dict[str, Any] | None:
    uri_match = runtime.uri_resolver.resolve(resource_uri)
    if uri_match is None:
        return None
    resource = runtime.schema_index.get_resource(uri_match.resource_type)
    if resource is None:
        return None
    action = resource.actions.get(_normalize_action_key(action_name))
    return action if isinstance(action, dict) else None


def _enum_values_for_param(
    runtime: RedfishRuntime,
    resource_uri: str,
    action_name: str,
    parameter_name: str,
) -> tuple[list[str], str | None]:
    schema_action = _resolve_schema_action(runtime, resource_uri, action_name)
    if not isinstance(schema_action, dict):
        return ([], None)
    parameters = schema_action.get("parameters")
    if not isinstance(parameters, dict):
        return ([], None)
    parameter = parameters.get(parameter_name)
    if not isinstance(parameter, dict):
        return ([], None)
    enum_ref = parameter.get("enum_ref")
    if not isinstance(enum_ref, str):
        return ([], None)
    enum_info = runtime.schema_index.get_enum(enum_ref)
    if enum_info is None:
        return ([], None)
    return (enum_info.values, enum_ref)


def _required_schema_params(
    runtime: RedfishRuntime,
    resource_uri: str,
    action_name: str,
) -> set[str]:
    schema_action = _resolve_schema_action(runtime, resource_uri, action_name)
    if not isinstance(schema_action, dict):
        return set()
    parameters = schema_action.get("parameters")
    if not isinstance(parameters, dict):
        return set()
    required: set[str] = set()
    for param_name, payload in parameters.items():
        if not isinstance(payload, dict):
            continue
        if payload.get("required_parameter") is True:
            required.add(param_name)
    return required


def _format_allowed_values(
    runtime: RedfishRuntime,
    values: list[str],
    enum_ref: str | None,
) -> str:
    if enum_ref is None:
        return ", ".join(values)
    enum_info = runtime.schema_index.get_enum(enum_ref)
    if enum_info is None:
        return ", ".join(values)
    return enum_help(enum_info, max_values=20, max_chars=700)


def _validate_action_payload(
    *,
    runtime: RedfishRuntime,
    resource_uri: str,
    action_name: str,
    action: ActionInstance,
    payload: dict[str, Any],
) -> None:
    required_live = {name for name, parameter in action.parameters.items() if parameter.required}
    required_schema = _required_schema_params(runtime, resource_uri, action_name)
    required = required_live | required_schema
    for name in sorted(required):
        if name not in payload:
            raise ValueError(
                f"missing required parameter '{name}' for action '{action_name}' on {resource_uri}"
            )

    for name, value in payload.items():
        live = action.parameters.get(name)
        allowed_values: list[str] = []
        enum_ref: str | None = None
        if live is not None and live.allowable_values:
            allowed_values = list(live.allowable_values)
        else:
            allowed_values, enum_ref = _enum_values_for_param(runtime, resource_uri, action_name, name)
        if allowed_values and str(value) not in allowed_values:
            rendered = _format_allowed_values(runtime, allowed_values, enum_ref)
            raise ValueError(
                f"invalid value for '{name}': {value!r}. Allowed values:\n{rendered}"
            )
        if live is not None and live.allowable_numbers:
            if not isinstance(value, (int, float)):
                raise ValueError(
                    f"invalid value type for '{name}': expected numeric in {live.allowable_numbers}"
                )
            as_float = float(value)
            if as_float not in live.allowable_numbers:
                raise ValueError(
                    f"invalid numeric value for '{name}': {value!r}; allowed numbers: {live.allowable_numbers}"
                )
        if (
            live is not None
            and live.allowable_pattern
            and re.fullmatch(live.allowable_pattern, str(value)) is None
        ):
            raise ValueError(
                f"value for '{name}' does not match required pattern {live.allowable_pattern!r}"
            )
        if (
            live is not None
            and live.minimum_value is not None
            and (not isinstance(value, (int, float)) or float(value) < live.minimum_value)
        ):
            raise ValueError(f"value for '{name}' must be >= {live.minimum_value}; got {value!r}")
        if (
            live is not None
            and live.maximum_value is not None
            and (not isinstance(value, (int, float)) or float(value) > live.maximum_value)
        ):
            raise ValueError(f"value for '{name}' must be <= {live.maximum_value}; got {value!r}")


async def _invoke_action(
    *,
    runtime: RedfishRuntime,
    endpoint: str | None,
    tool_name: str,
    resource_uri: str,
    action_name: str,
    payload: dict[str, Any],
    required_tier: RequiredTier,
    confirm: bool,
) -> dict[str, Any]:
    async with runtime.client_for(endpoint) as client:
        resource = await client.get_json(resource_uri)
        action = extract_action_instance(resource, action_name)
        if action is None:
            raise ValueError(f"action '{action_name}' not exposed on resource {resource_uri}")
        if action.action_info_uri:
            try:
                action_info = await client.get_json(action.action_info_uri)
                action = merge_action_info(action, action_info)
            except Exception:
                pass
        _validate_action_payload(
            runtime=runtime,
            resource_uri=resource_uri,
            action_name=action_name,
            action=action,
            payload=payload,
        )
        dry_run = runtime.safety.enforce_mutation(
            endpoint=client.endpoint,
            required_tier=required_tier,
            tool_name=tool_name,
            confirm=confirm,
            method="POST",
            uri=action.target,
            body=payload,
            details={
                "action": action.key,
                "resource_uri": resource_uri,
                "allowable_values": {
                    key: value.allowable_values for key, value in action.parameters.items()
                },
            },
        )
        if dry_run is not None:
            return dry_run.model_dump()
        out = await client.post_json(action.target, payload, wait_task=True)
        return {
            "endpoint": client.endpoint.name,
            "action": action.key,
            "target": action.target,
            "result": out,
        }


def register_write_tools(server: MCPServer, runtime: RedfishRuntime) -> None:
    """Register mutating tools gated by write tiers."""

    index = runtime.schema_index

    tool_enum_refs: dict[str, dict[str, str]] = {
        "set_power_state": {"reset_type": "Resource.json#/definitions/ResetType"},
        "reset_manager": {"reset_type": "Resource.json#/definitions/ResetType"},
        "set_boot_override": {
            "target": "ComputerSystem.json#/definitions/BootSource",
            "enabled": require_versioned_ref(index, "ComputerSystem", "BootSourceOverrideEnabled"),
            "mode": require_versioned_ref(index, "ComputerSystem", "BootSourceOverrideMode"),
        },
        "simple_update": {
            "transfer_protocol": require_versioned_ref(
                index, "UpdateService", "TransferProtocolType"
            )
        },
        "reset_to_defaults": {
            "reset_type": require_versioned_ref(index, "Manager", "ResetToDefaultsType")
        },
    }

    reset_type_values = require_enum_values(index, "Resource.json#/definitions/ResetType")
    tool_enum_values: dict[str, dict[str, list[str]]] = {
        "set_power_state": {"reset_type": reset_type_values},
        "reset_manager": {"reset_type": reset_type_values},
        "set_boot_override": {
            "target": require_enum_values(index, "ComputerSystem.json#/definitions/BootSource"),
            "enabled": require_enum_values(index, tool_enum_refs["set_boot_override"]["enabled"]),
            "mode": require_enum_values(index, tool_enum_refs["set_boot_override"]["mode"]),
        },
        "simple_update": {
            "transfer_protocol": require_enum_values(
                index, tool_enum_refs["simple_update"]["transfer_protocol"]
            ),
        },
        "reset_to_defaults": {
            "reset_type": require_enum_values(
                index, tool_enum_refs["reset_to_defaults"]["reset_type"]
            ),
        },
        "redfish_patch": {"tier": [tier.value for tier in RequiredTier]},
        "redfish_post": {"tier": [tier.value for tier in RequiredTier]},
        "redfish_delete": {"tier": [tier.value for tier in RequiredTier]},
        "redfish_invoke_action": {"tier": [tier.value for tier in RequiredTier]},
        "manage_account": {"operation": ["create", "patch", "delete"]},
    }

    def build_param_descriptions(name: str, spec: ToolSpec) -> dict[str, str]:
        return build_enum_param_descriptions(
            index, spec.param_descriptions, tool_enum_refs.get(name, {})
        )

    def tool(name: str) -> Callable[[ToolFunc], ToolFunc]:
        spec = WRITE_TOOL_SPECS[name]
        annotations = ToolAnnotations(
            read_only_hint=False,
            destructive_hint=spec.destructive,
            idempotent_hint=spec.idempotent,
            open_world_hint=True,
        )

        def decorator(fn: ToolFunc) -> ToolFunc:
            toolset = spec.toolset or WRITE_TOOLSETS[name]
            required_tier = spec.required_tier or WRITE_REQUIRED_TIERS[name]
            rule = ToolRegistrationRule(
                name=name,
                required_tier=required_tier,
                toolset=toolset,
            )
            if not runtime.safety.can_register(rule):
                return fn
            returns_hint = spec.returns or WRITE_TOOL_RETURNS[name]
            example_hint = spec.example or WRITE_TOOL_EXAMPLES[name]
            param_examples = spec.param_examples or WRITE_TOOL_PARAM_EXAMPLES.get(name)
            description = f"{spec.description} Returns: {returns_hint} Example: {example_hint}"
            register_tool(
                server,
                fn,
                name=name,
                title=spec.title,
                description=description,
                annotations=annotations,
                param_descriptions=build_param_descriptions(name, spec),
                enum_values=tool_enum_values.get(name),
                param_examples=param_examples,
            )
            return fn

        return decorator

    async def resolve_default_system_uri(endpoint_name: str | None) -> str:
        async with runtime.client_for(endpoint_name) as client:
            root = await client.get_json("/redfish/v1")
            systems_uri = _link_uri(root, "Systems", "/redfish/v1/Systems")
            first = await _first_collection_member_uri(client, systems_uri)
            if first is None:
                raise ValueError("no systems found")
            return first

    async def resolve_default_manager_uri(endpoint_name: str | None) -> str:
        async with runtime.client_for(endpoint_name) as client:
            root = await client.get_json("/redfish/v1")
            managers_uri = _link_uri(root, "Managers", "/redfish/v1/Managers")
            first = await _first_collection_member_uri(client, managers_uri)
            if first is None:
                raise ValueError("no manager found")
            return first

    async def resolve_default_virtual_media_uri(endpoint_name: str | None) -> str:
        async with runtime.client_for(endpoint_name) as client:
            root = await client.get_json("/redfish/v1")
            managers_uri = _link_uri(root, "Managers", "/redfish/v1/Managers")
            manager_uri = await _first_collection_member_uri(client, managers_uri)
            if manager_uri is None:
                raise ValueError("no manager found")
            manager = await client.get_json(manager_uri)
            virtual_media = manager.get("VirtualMedia")
            if not isinstance(virtual_media, dict) or not isinstance(
                virtual_media.get("@odata.id"), str
            ):
                raise ValueError("manager does not expose VirtualMedia collection")
            virtual_media_uri = await _first_collection_member_uri(client, virtual_media["@odata.id"])
            if virtual_media_uri is None:
                raise ValueError("VirtualMedia collection has no members")
            return virtual_media_uri

    async def resolve_default_log_service_uri(endpoint_name: str | None) -> str:
        async with runtime.client_for(endpoint_name) as client:
            root = await client.get_json("/redfish/v1")
            managers_uri = _link_uri(root, "Managers", "/redfish/v1/Managers")
            manager_uri = await _first_collection_member_uri(client, managers_uri)
            if manager_uri is None:
                raise ValueError("no manager found")
            manager = await client.get_json(manager_uri)
            log_services = manager.get("LogServices")
            if not isinstance(log_services, dict) or not isinstance(
                log_services.get("@odata.id"), str
            ):
                raise ValueError("manager does not expose LogServices")
            log_service_uri = await _first_collection_member_uri(client, log_services["@odata.id"])
            if log_service_uri is None:
                raise ValueError("LogServices collection has no members")
            return log_service_uri

    @tool("set_power_state")
    async def set_power_state(
        reset_type: str,
        endpoint: str | None = None,
        system_uri: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        if system_uri is None:
            system_uri = await resolve_default_system_uri(endpoint)
        return await _invoke_action(
            runtime=runtime,
            endpoint=endpoint,
            tool_name="set_power_state",
            resource_uri=system_uri,
            action_name="ComputerSystem.Reset",
            payload={"ResetType": reset_type},
            required_tier=RequiredTier.POWER,
            confirm=confirm,
        )

    @tool("set_boot_override")
    async def set_boot_override(
        target: str,
        endpoint: str | None = None,
        system_uri: str | None = None,
        enabled: str = "Once",
        mode: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        if system_uri is None:
            system_uri = await resolve_default_system_uri(endpoint)
        patch_body: dict[str, Any] = {
            "Boot": {
                "BootSourceOverrideTarget": target,
                "BootSourceOverrideEnabled": enabled,
            }
        }
        if mode:
            patch_body["Boot"]["BootSourceOverrideMode"] = mode
        async with runtime.client_for(endpoint) as client:
            dry_run = runtime.safety.enforce_mutation(
                endpoint=client.endpoint,
                required_tier=RequiredTier.POWER,
                tool_name="set_boot_override",
                confirm=confirm,
                method="PATCH",
                uri=system_uri,
                body=patch_body,
                details={"operation": "boot_override"},
            )
            if dry_run is not None:
                return dry_run.model_dump()
            out = await client.patch_json(system_uri, patch_body, if_match=True, wait_task=True)
            return {"endpoint": client.endpoint.name, "uri": system_uri, "result": out}

    @tool("reset_manager")
    async def reset_manager(
        reset_type: str = "GracefulRestart",
        endpoint: str | None = None,
        manager_uri: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        if manager_uri is None:
            manager_uri = await resolve_default_manager_uri(endpoint)
        return await _invoke_action(
            runtime=runtime,
            endpoint=endpoint,
            tool_name="reset_manager",
            resource_uri=manager_uri,
            action_name="Manager.Reset",
            payload={"ResetType": reset_type},
            required_tier=RequiredTier.POWER,
            confirm=confirm,
        )

    @tool("cancel_task")
    async def cancel_task(
        task_uri: str,
        endpoint: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        target = _normalize_uri(task_uri)
        async with runtime.client_for(endpoint) as client:
            dry_run = runtime.safety.enforce_mutation(
                endpoint=client.endpoint,
                required_tier=RequiredTier.POWER,
                tool_name="cancel_task",
                confirm=confirm,
                method="DELETE",
                uri=target,
                body=None,
                details={"operation": "cancel_task"},
            )
            if dry_run is not None:
                return dry_run.model_dump()
            return {
                "endpoint": client.endpoint.name,
                "uri": target,
                "result": await client.delete_json(target, wait_task=True),
            }

    @tool("set_bios_attributes")
    async def set_bios_attributes(
        attributes: dict[str, Any],
        endpoint: str | None = None,
        system_uri: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        if not attributes:
            raise ValueError("attributes cannot be empty")
        if system_uri is None:
            system_uri = await resolve_default_system_uri(endpoint)
        async with runtime.client_for(endpoint) as client:
            system = await client.get_json(system_uri)
            bios_link = system.get("Bios")
            if not isinstance(bios_link, dict) or not isinstance(bios_link.get("@odata.id"), str):
                raise ValueError("system does not expose Bios link")
            bios_uri = bios_link["@odata.id"]
            bios = await client.get_json(bios_uri)
            settings_target = resolve_settings_target(bios)
            if settings_target is None:
                raise ValueError("BIOS resource does not expose @Redfish.Settings")
            body = {"Attributes": attributes}
            dry_run = runtime.safety.enforce_mutation(
                endpoint=client.endpoint,
                required_tier=RequiredTier.CONFIG,
                tool_name="set_bios_attributes",
                confirm=confirm,
                method="PATCH",
                uri=settings_target.settings_uri,
                body=body,
                details={"settings_etag": settings_target.current_etag},
            )
            if dry_run is not None:
                return dry_run.model_dump()
            result = await client.patch_json(
                settings_target.settings_uri,
                body,
                if_match=bool(settings_target.current_etag),
                wait_task=True,
            )
            return {
                "endpoint": client.endpoint.name,
                "bios_uri": bios_uri,
                "settings_uri": settings_target.settings_uri,
                "result": result,
            }

    @tool("insert_virtual_media")
    async def insert_virtual_media(
        image: str,
        endpoint: str | None = None,
        virtual_media_uri: str | None = None,
        inserted: bool = True,
        write_protected: bool = True,
        confirm: bool = False,
    ) -> dict[str, Any]:
        if virtual_media_uri is None:
            virtual_media_uri = await resolve_default_virtual_media_uri(endpoint)
        body = {"Image": image, "Inserted": inserted, "WriteProtected": write_protected}
        async with runtime.client_for(endpoint) as client:
            virtual_media = await client.get_json(virtual_media_uri)
            action = extract_action_instance(virtual_media, "VirtualMedia.InsertMedia")
            if action is not None:
                if action.action_info_uri:
                    try:
                        action_info = await client.get_json(action.action_info_uri)
                        action = merge_action_info(action, action_info)
                    except Exception:
                        pass
                _validate_action_payload(
                    runtime=runtime,
                    resource_uri=virtual_media_uri,
                    action_name="VirtualMedia.InsertMedia",
                    action=action,
                    payload=body,
                )
                dry_run = runtime.safety.enforce_mutation(
                    endpoint=client.endpoint,
                    required_tier=RequiredTier.FULL,
                    tool_name="insert_virtual_media",
                    confirm=confirm,
                    method="POST",
                    uri=action.target,
                    body=body,
                    details={
                        "operation": "insert_virtual_media",
                        "resource_uri": virtual_media_uri,
                        "action": action.key,
                    },
                )
                if dry_run is not None:
                    return dry_run.model_dump()
                out = await client.post_json(action.target, body, wait_task=True)
                return {
                    "endpoint": client.endpoint.name,
                    "uri": virtual_media_uri,
                    "target": action.target,
                    "result": out,
                }
            dry_run = runtime.safety.enforce_mutation(
                endpoint=client.endpoint,
                required_tier=RequiredTier.FULL,
                tool_name="insert_virtual_media",
                confirm=confirm,
                method="PATCH",
                uri=virtual_media_uri,
                body=body,
                details={"operation": "insert_virtual_media"},
            )
            if dry_run is not None:
                return dry_run.model_dump()
            out = await client.patch_json(virtual_media_uri, body, if_match=True, wait_task=True)
            return {"endpoint": client.endpoint.name, "uri": virtual_media_uri, "result": out}

    @tool("eject_virtual_media")
    async def eject_virtual_media(
        endpoint: str | None = None,
        virtual_media_uri: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        if virtual_media_uri is None:
            virtual_media_uri = await resolve_default_virtual_media_uri(endpoint)
        body = {"Image": None, "Inserted": False}
        async with runtime.client_for(endpoint) as client:
            virtual_media = await client.get_json(virtual_media_uri)
            action = extract_action_instance(virtual_media, "VirtualMedia.EjectMedia")
            if action is not None:
                if action.action_info_uri:
                    try:
                        action_info = await client.get_json(action.action_info_uri)
                        action = merge_action_info(action, action_info)
                    except Exception:
                        pass
                dry_run = runtime.safety.enforce_mutation(
                    endpoint=client.endpoint,
                    required_tier=RequiredTier.CONFIG,
                    tool_name="eject_virtual_media",
                    confirm=confirm,
                    method="POST",
                    uri=action.target,
                    body={},
                    details={
                        "operation": "eject_virtual_media",
                        "resource_uri": virtual_media_uri,
                        "action": action.key,
                    },
                )
                if dry_run is not None:
                    return dry_run.model_dump()
                out = await client.post_json(action.target, {}, wait_task=True)
                return {
                    "endpoint": client.endpoint.name,
                    "uri": virtual_media_uri,
                    "target": action.target,
                    "result": out,
                }
            dry_run = runtime.safety.enforce_mutation(
                endpoint=client.endpoint,
                required_tier=RequiredTier.CONFIG,
                tool_name="eject_virtual_media",
                confirm=confirm,
                method="PATCH",
                uri=virtual_media_uri,
                body=body,
                details={"operation": "eject_virtual_media"},
            )
            if dry_run is not None:
                return dry_run.model_dump()
            out = await client.patch_json(virtual_media_uri, body, if_match=True, wait_task=True)
            return {"endpoint": client.endpoint.name, "uri": virtual_media_uri, "result": out}

    @tool("clear_logs")
    async def clear_logs(
        endpoint: str | None = None,
        log_service_uri: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        if log_service_uri is None:
            log_service_uri = await resolve_default_log_service_uri(endpoint)
        return await _invoke_action(
            runtime=runtime,
            endpoint=endpoint,
            tool_name="clear_logs",
            resource_uri=log_service_uri,
            action_name="LogService.ClearLog",
            payload={},
            required_tier=RequiredTier.FULL,
            confirm=confirm,
        )

    @tool("manage_account")
    async def manage_account(
        operation: str,
        endpoint: str | None = None,
        account_uri: str | None = None,
        body: dict[str, Any] | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        op = operation.lower()
        if op not in {"create", "patch", "delete"}:
            raise ValueError("operation must be one of create|patch|delete")
        async with runtime.client_for(endpoint) as client:
            if op == "create":
                root = await client.get_json("/redfish/v1")
                account_service_link = root.get("AccountService")
                if not isinstance(account_service_link, dict) or not isinstance(
                    account_service_link.get("@odata.id"), str
                ):
                    raise ValueError("service does not expose AccountService")
                service = await client.get_json(account_service_link["@odata.id"])
                accounts = service.get("Accounts")
                if not isinstance(accounts, dict) or not isinstance(accounts.get("@odata.id"), str):
                    raise ValueError("AccountService does not expose Accounts")
                target_uri = accounts["@odata.id"]
                dry = runtime.safety.enforce_mutation(
                    endpoint=client.endpoint,
                    required_tier=RequiredTier.FULL,
                    tool_name="manage_account",
                    confirm=confirm,
                    method="POST",
                    uri=target_uri,
                    body=body or {},
                    details={"operation": "create_account"},
                )
                if dry is not None:
                    return dry.model_dump()
                return {
                    "endpoint": client.endpoint.name,
                    "result": await client.post_json(target_uri, body or {}),
                }

            if account_uri is None:
                raise ValueError("account_uri is required for patch and delete")
            if op == "patch":
                dry = runtime.safety.enforce_mutation(
                    endpoint=client.endpoint,
                    required_tier=RequiredTier.FULL,
                    tool_name="manage_account",
                    confirm=confirm,
                    method="PATCH",
                    uri=account_uri,
                    body=body or {},
                    details={"operation": "patch_account"},
                )
                if dry is not None:
                    return dry.model_dump()
                return {
                    "endpoint": client.endpoint.name,
                    "result": await client.patch_json(account_uri, body or {}, if_match=True),
                }
            dry = runtime.safety.enforce_mutation(
                endpoint=client.endpoint,
                required_tier=RequiredTier.FULL,
                tool_name="manage_account",
                confirm=confirm,
                method="DELETE",
                uri=account_uri,
                body=None,
                details={"operation": "delete_account"},
            )
            if dry is not None:
                return dry.model_dump()
            return {
                "endpoint": client.endpoint.name,
                "result": await client.delete_json(account_uri),
            }

    @tool("simple_update")
    async def simple_update(
        image_uri: str,
        endpoint: str | None = None,
        transfer_protocol: str | None = None,
        targets: list[str] | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        async with runtime.client_for(endpoint) as client:
            root = await client.get_json("/redfish/v1")
            update_service_link = root.get("UpdateService")
            if not isinstance(update_service_link, dict) or not isinstance(
                update_service_link.get("@odata.id"), str
            ):
                raise ValueError("service does not expose UpdateService")
            update_service = await client.get_json(update_service_link["@odata.id"])
            action = extract_action_instance(update_service, "UpdateService.SimpleUpdate")
            if action is None:
                raise ValueError("UpdateService.SimpleUpdate not exposed")
            if action.action_info_uri:
                try:
                    action_info = await client.get_json(action.action_info_uri)
                    action = merge_action_info(action, action_info)
                except Exception:
                    pass
            body: dict[str, Any] = {"ImageURI": image_uri}
            if transfer_protocol:
                body["TransferProtocol"] = transfer_protocol
            if targets:
                body["Targets"] = targets
            _validate_action_payload(
                runtime=runtime,
                resource_uri=update_service_link["@odata.id"],
                action_name="UpdateService.SimpleUpdate",
                action=action,
                payload=body,
            )
            dry_run = runtime.safety.enforce_mutation(
                endpoint=client.endpoint,
                required_tier=RequiredTier.FULL,
                tool_name="simple_update",
                confirm=confirm,
                method="POST",
                uri=action.target,
                body=body,
                details={"operation": "simple_update"},
            )
            if dry_run is not None:
                return dry_run.model_dump()
            out = await client.post_json(action.target, body, wait_task=True)
            return {"endpoint": client.endpoint.name, "target": action.target, "result": out}

    @tool("reset_to_defaults")
    async def reset_to_defaults(
        endpoint: str | None = None,
        manager_uri: str | None = None,
        reset_type: str = "ResetAll",
        confirm: bool = False,
    ) -> dict[str, Any]:
        if manager_uri is None:
            manager_uri = await resolve_default_manager_uri(endpoint)
        return await _invoke_action(
            runtime=runtime,
            endpoint=endpoint,
            tool_name="reset_to_defaults",
            resource_uri=manager_uri,
            action_name="Manager.ResetToDefaults",
            payload={"ResetType": reset_type},
            required_tier=RequiredTier.FULL,
            confirm=confirm,
        )

    @tool("redfish_patch")
    async def redfish_patch(
        uri: str,
        body: dict[str, Any],
        endpoint: str | None = None,
        tier: str = "config",
        confirm: bool = False,
    ) -> dict[str, Any]:
        required_tier = RequiredTier(tier)
        target = _normalize_uri(uri)
        async with runtime.client_for(endpoint) as client:
            dry_run = runtime.safety.enforce_mutation(
                endpoint=client.endpoint,
                required_tier=required_tier,
                tool_name="redfish_patch",
                confirm=confirm,
                method="PATCH",
                uri=target,
                body=body,
                details={"operation": "raw_patch"},
            )
            if dry_run is not None:
                return dry_run.model_dump()
            return {
                "endpoint": client.endpoint.name,
                "result": await client.patch_json(target, body, if_match=True, wait_task=True),
            }

    @tool("redfish_post")
    async def redfish_post(
        uri: str,
        body: dict[str, Any] | None = None,
        endpoint: str | None = None,
        tier: str = "config",
        confirm: bool = False,
    ) -> dict[str, Any]:
        required_tier = RequiredTier(tier)
        target = _normalize_uri(uri)
        async with runtime.client_for(endpoint) as client:
            dry_run = runtime.safety.enforce_mutation(
                endpoint=client.endpoint,
                required_tier=required_tier,
                tool_name="redfish_post",
                confirm=confirm,
                method="POST",
                uri=target,
                body=body or {},
                details={"operation": "raw_post"},
            )
            if dry_run is not None:
                return dry_run.model_dump()
            return {
                "endpoint": client.endpoint.name,
                "result": await client.post_json(target, body or {}, wait_task=True),
            }

    @tool("redfish_delete")
    async def redfish_delete(
        uri: str,
        endpoint: str | None = None,
        tier: str = "config",
        confirm: bool = False,
    ) -> dict[str, Any]:
        required_tier = RequiredTier(tier)
        target = _normalize_uri(uri)
        async with runtime.client_for(endpoint) as client:
            dry_run = runtime.safety.enforce_mutation(
                endpoint=client.endpoint,
                required_tier=required_tier,
                tool_name="redfish_delete",
                confirm=confirm,
                method="DELETE",
                uri=target,
                body=None,
                details={"operation": "raw_delete"},
            )
            if dry_run is not None:
                return dry_run.model_dump()
            return {
                "endpoint": client.endpoint.name,
                "result": await client.delete_json(target, wait_task=True),
            }

    @tool("redfish_invoke_action")
    async def redfish_invoke_action(
        resource_uri: str,
        action_name: str,
        payload: dict[str, Any] | None = None,
        endpoint: str | None = None,
        tier: str = "config",
        confirm: bool = False,
    ) -> dict[str, Any]:
        required_tier = RequiredTier(tier)
        return await _invoke_action(
            runtime=runtime,
            endpoint=endpoint,
            tool_name="redfish_invoke_action",
            resource_uri=_normalize_uri(resource_uri),
            action_name=action_name,
            payload=payload or {},
            required_tier=required_tier,
            confirm=confirm,
        )
