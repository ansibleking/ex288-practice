"""Server-level instructions presented to MCP clients."""

from __future__ import annotations

from mirastack_redfish_mcp.runtime import RedfishRuntime

DISCOVERY_TOOLS = ("list_systems", "list_chassis", "list_managers")


def _write_mode_hint(mode: str) -> str:
    if mode == "off":
        return "Write mode is off, so mutating tools are not registered."
    if mode == "power":
        return "Write mode is power, so only power-tier mutations are registered."
    if mode == "config":
        return "Write mode is config, so power and config mutations are registered."
    return "Write mode is full, so all mutating tools are registered."


def build_instructions(runtime: RedfishRuntime) -> str:
    """Build concise operating instructions for MCP clients."""
    # Imported here because mirastack_redfish_mcp.tools imports the runtime this module also depends on.
    from mirastack_redfish_mcp.tools import advertised_tool_names
    from mirastack_redfish_mcp.tools.write import WRITE_TOOL_SPECS

    advertised = advertised_tool_names(runtime)
    endpoint_names = sorted(runtime.config.endpoints.keys())
    endpoints = ", ".join(endpoint_names)
    default_endpoint = runtime.config.default_endpoint
    write_mode = runtime.config.write_mode.value
    tool_profile = runtime.config.tool_profile.value
    enabled_toolsets = ", ".join(sorted(runtime.config.enabled_toolsets))
    curated_tools = runtime.config.enabled_tools
    curated_hint = (
        f" This profile exposes a curated set of {len(curated_tools)} tools."
        if curated_tools
        else ""
    )

    lines = [
        "Use this server to inspect and control Redfish-managed hardware resources.",
    ]
    if endpoint_names:
        lines.append(
            f"Configured endpoints: {endpoints}. If endpoint is omitted, default to "
            f"'{default_endpoint}'."
        )
    else:
        lines.append(
            "Configured endpoints: none. Discovery mode is active, so schema/corpus tools still "
            "work but BMC-connected tools return a configuration error until endpoints are set."
        )

    # Every tool named below must actually be advertised, or the model is told to call
    # something it cannot see.
    discovery = [name for name in DISCOVERY_TOOLS if name in advertised]
    if discovery:
        lines.append(
            f"Resolve target URIs with {'/'.join(discovery)} and pass those URIs to follow-up "
            "tools. Most write tools auto-resolve the first collection member when URI inputs "
            "are omitted."
        )
    if "redfish_list_available_actions" in advertised:
        lines.append(
            "Before invoking an unfamiliar Redfish action, call redfish_list_available_actions "
            "for that resource URI to retrieve live ActionInfo and allowable values."
        )
    if advertised & set(WRITE_TOOL_SPECS):
        lines.append(
            "Every mutating tool accepts confirm: confirm=false returns a preview only and "
            "makes no change; call the same tool again with confirm=true to apply."
        )
    lines.append(f"Active write mode: {write_mode}. {_write_mode_hint(write_mode)}")
    lines.append(
        f"Active tool profile: {tool_profile}. Enabled toolsets: {enabled_toolsets}.{curated_hint}"
    )
    return "\n".join(lines)
