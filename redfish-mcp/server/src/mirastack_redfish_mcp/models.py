"""Shared models and enums for the Redfish MCP server."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class WriteMode(str, Enum):
    """Mutation tiers exposed by the server."""

    OFF = "off"
    POWER = "power"
    CONFIG = "config"
    FULL = "full"


class ToolProfile(str, Enum):
    """Named MCP tool registration profiles."""

    CORE = "core"
    STANDARD = "standard"
    FULL = "full"
    CUSTOM = "custom"


class AuthMode(str, Enum):
    """Auth mode for a Redfish endpoint."""

    AUTO = "auto"
    SESSION = "session"
    BASIC = "basic"


class EndpointConfig(BaseModel):
    """Connection and behavior settings for one Redfish endpoint."""

    name: str = Field(min_length=1, max_length=64)
    base_url: str = Field(description="Base Redfish host URL, e.g. https://192.0.2.10")
    username: str = Field(min_length=1)
    password: str = Field(min_length=1, repr=False)
    verify_ssl: bool = True
    ca_bundle: str | None = None
    timeout_sec: float = Field(default=30.0, gt=0, le=300)
    read_only: bool = False
    auth_mode: AuthMode = AuthMode.AUTO
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_.-]+", value) is None:
            raise ValueError("endpoint name must be alphanumeric with '-', '_' or '.'")
        return value

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        url = value.strip().rstrip("/")
        if not (url.startswith("https://") or url.startswith("http://")):
            raise ValueError("base_url must start with http:// or https://")
        return url


class AppConfig(BaseModel):
    """Global app configuration loaded from env and CLI."""

    endpoints: dict[str, EndpointConfig]
    default_endpoint: str | None
    write_mode: WriteMode = WriteMode.OFF
    tool_profile: ToolProfile = ToolProfile.FULL
    enabled_toolsets: set[str] = Field(default_factory=set)
    # Empty means no per-tool restriction; non-empty is an exact allowlist of tool names.
    enabled_tools: set[str] = Field(default_factory=set)
    schema_index_path: str = "src/mirastack_redfish_mcp/data/redfish_index.json.gz"
    streamable_http_host: str = "127.0.0.1"
    streamable_http_port: int = 8000
    streamable_http_path: str = "/mcp"

    @field_validator("default_endpoint")
    @classmethod
    def default_endpoint_exists(cls, value: str | None, info: Any) -> str | None:
        endpoints = info.data.get("endpoints") if hasattr(info, "data") else None
        if not isinstance(endpoints, dict):
            return value
        if not endpoints:
            if value:
                raise ValueError("default endpoint cannot be set when no endpoints are configured")
            return None
        if value is None:
            raise ValueError("default endpoint is required when endpoints are configured")
        if value not in endpoints:
            raise ValueError(f"default endpoint '{value}' not found in endpoint map")
        return value


class ToolDryRun(BaseModel):
    """Dry-run response for mutation tools."""

    dry_run: Literal[True] = True
    applied: Literal[False] = False
    method: str
    uri: str
    body: dict[str, Any] | list[Any] | None = None
    endpoint: str
    next_step: str
    details: dict[str, Any] = Field(default_factory=dict)
