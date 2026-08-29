"""Tool registration entrypoint."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from mirastack_redfish_mcp.models import WriteMode
from mirastack_redfish_mcp.runtime import RedfishRuntime
from mirastack_redfish_mcp.safety import ToolRegistrationRule
from mirastack_redfish_mcp.tools.raw_schema import RAW_SCHEMA_TOOL_SPECS, register_raw_schema_tools
from mirastack_redfish_mcp.tools.read import READ_TOOLSETS, register_read_tools
from mirastack_redfish_mcp.tools.write import (
    WRITE_REQUIRED_TIERS,
    WRITE_TOOLSETS,
    register_write_tools,
)


def registration_rules(runtime: RedfishRuntime) -> list[ToolRegistrationRule]:
    """Return the registration rule for every tool this build knows about."""
    rules = [
        ToolRegistrationRule(name=name, toolset=toolset)
        for name, toolset in READ_TOOLSETS.items()
    ]
    rules += [
        ToolRegistrationRule(name=name, toolset=spec.toolset)
        for name, spec in RAW_SCHEMA_TOOL_SPECS.items()
    ]
    if runtime.config.write_mode is not WriteMode.OFF:
        rules += [
            ToolRegistrationRule(
                name=name,
                required_tier=WRITE_REQUIRED_TIERS[name],
                toolset=WRITE_TOOLSETS[name],
            )
            for name in WRITE_TOOLSETS
        ]
    return rules


def advertised_tool_names(runtime: RedfishRuntime) -> set[str]:
    """Names of the tools this configuration will advertise, resolved without registering."""
    return {rule.name for rule in registration_rules(runtime) if runtime.safety.can_register(rule)}


def register_tools(server: MCPServer, runtime: RedfishRuntime) -> None:
    """Register tool groups according to runtime configuration."""
    register_read_tools(server, runtime)
    register_raw_schema_tools(server, runtime)
    if runtime.config.write_mode is not WriteMode.OFF:
        register_write_tools(server, runtime)
