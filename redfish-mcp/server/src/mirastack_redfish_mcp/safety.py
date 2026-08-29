"""Safety controls for write operations and tool registration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from mirastack_redfish_mcp.models import AppConfig, EndpointConfig, ToolDryRun, WriteMode


class RequiredTier(str, Enum):
    """Minimum write tier required for a mutating operation."""

    POWER = "power"
    CONFIG = "config"
    FULL = "full"


_MODE_RANK: dict[WriteMode, int] = {
    WriteMode.OFF: 0,
    WriteMode.POWER: 1,
    WriteMode.CONFIG: 2,
    WriteMode.FULL: 3,
}

_TIER_RANK: dict[RequiredTier, int] = {
    RequiredTier.POWER: 1,
    RequiredTier.CONFIG: 2,
    RequiredTier.FULL: 3,
}


@dataclass(frozen=True)
class ToolRegistrationRule:
    """Registration metadata used to hide unsupported mutating tools."""

    name: str
    required_tier: RequiredTier | None = None
    toolset: str | None = None


class SafetyGate:
    """Centralized policy enforcement for write safety."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    @property
    def write_mode(self) -> WriteMode:
        return self._config.write_mode

    def is_toolset_enabled(self, toolset: str) -> bool:
        return toolset in self._config.enabled_toolsets

    def can_register(self, rule: ToolRegistrationRule) -> bool:
        allowed_tools = self._config.enabled_tools
        if allowed_tools and rule.name not in allowed_tools:
            return False
        if rule.toolset is not None and not self.is_toolset_enabled(rule.toolset):
            return False
        if rule.required_tier is None:
            return True
        return _MODE_RANK[self.write_mode] >= _TIER_RANK[rule.required_tier]

    def enforce_mutation(
        self,
        *,
        endpoint: EndpointConfig,
        required_tier: RequiredTier,
        tool_name: str,
        confirm: bool,
        method: str,
        uri: str,
        body: dict[str, Any] | list[Any] | None,
        details: dict[str, Any] | None = None,
    ) -> ToolDryRun | None:
        """Validate mutation policy and return dry-run payload when confirm=False."""
        if endpoint.read_only:
            raise PermissionError(f"endpoint '{endpoint.name}' is read_only=true")
        if _MODE_RANK[self.write_mode] < _TIER_RANK[required_tier]:
            raise PermissionError(
                f"write mode '{self.write_mode.value}' does not permit tier '{required_tier.value}'"
            )
        if not confirm:
            return ToolDryRun(
                method=method.upper(),
                uri=uri,
                body=body,
                endpoint=endpoint.name,
                next_step=(
                    f"Dry run only. Re-invoke '{tool_name}' with confirm=true to apply this mutation."
                ),
                details=details or {},
            )
        return None
