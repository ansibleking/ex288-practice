"""Reusable MCP prompts for common Redfish workflows."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from mirastack_redfish_mcp.models import WriteMode
from mirastack_redfish_mcp.runtime import RedfishRuntime


def register_prompts(server: MCPServer, runtime: RedfishRuntime) -> None:
    """Register prompt templates that guide small models through tool sequences."""

    @server.prompt(
        name="triage_unhealthy_hardware",
        title="Triage unhealthy hardware",
        description="Guided read-only sequence to identify unhealthy systems, chassis, and managers.",
    )
    async def triage_unhealthy_hardware(endpoint: str | None = None) -> str:
        endpoint_hint = endpoint or runtime.config.default_endpoint or "<configure-endpoint>"
        return (
            f"Use endpoint '{endpoint_hint}'.\n"
            "1) Call service_info to read capability links.\n"
            "2) Call get_health_summary.\n"
            "3) For each unhealthy member URI, call redfish_get on that URI.\n"
            "4) If thermal/power symptoms appear, call get_thermal and get_power.\n"
            "5) Call get_log_entries with severity='Critical' and summarize root causes."
        )

    if runtime.config.write_mode is not WriteMode.OFF:
        @server.prompt(
            name="safe_power_cycle_system",
            title="Safe power cycle system",
            description="Two-step dry-run and confirm flow for controlled system reset.",
        )
        async def safe_power_cycle_system(
            endpoint: str | None = None, system_uri: str | None = None
        ) -> str:
            endpoint_hint = endpoint or runtime.config.default_endpoint or "<configure-endpoint>"
            target_hint = system_uri or "<system-uri-from-list_systems>"
            return (
                f"Use endpoint '{endpoint_hint}' and target system '{target_hint}'.\n"
                "1) Call set_power_state with reset_type='GracefulRestart' and confirm=false.\n"
                "2) Review dry_run payload (applied must be false).\n"
                "3) Re-call set_power_state with the same arguments and confirm=true.\n"
                "4) Poll get_system or list_tasks until state stabilizes."
            )

    @server.prompt(
        name="collect_support_bundle",
        title="Collect support bundle",
        description="Read-only workflow for collecting logs, health, and inventory for support.",
    )
    async def collect_support_bundle(endpoint: str | None = None) -> str:
        endpoint_hint = endpoint or runtime.config.default_endpoint or "<configure-endpoint>"
        return (
            f"Use endpoint '{endpoint_hint}'.\n"
            "1) Call service_info.\n"
            "2) Call get_health_summary.\n"
            "3) Call get_log_entries with limit=200.\n"
            "4) Call get_component_inventory and get_firmware_inventory.\n"
            "5) Call list_tasks include_details=true.\n"
            "6) Return a bundle summary keyed by URI with observed risks."
        )

    @server.prompt(
        name="audit_firmware_versions",
        title="Audit firmware versions",
        description="Read-only firmware inventory audit and drift detection sequence.",
    )
    async def audit_firmware_versions(endpoint: str | None = None) -> str:
        endpoint_hint = endpoint or runtime.config.default_endpoint or "<configure-endpoint>"
        return (
            f"Use endpoint '{endpoint_hint}'.\n"
            "1) Call get_firmware_inventory.\n"
            "2) Group items by Manufacturer/Name/Version.\n"
            "3) Flag components with missing versions or inconsistent versions.\n"
            "4) Optionally call redfish_get on each inventory member URI for extra detail."
        )
