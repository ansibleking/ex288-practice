"""Configuration loading from environment variables and files."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from mirastack_redfish_mcp.models import AppConfig, AuthMode, EndpointConfig, ToolProfile, WriteMode

LOGGER = logging.getLogger(__name__)
NAMESPACED_REDFISH_PREFIX = "MIRASTACK_REDFISH_"
LEGACY_REDFISH_PREFIX = "REDFISH_"
_LEGACY_REDFISH_WARNED: set[str] = set()

ALL_TOOLSETS: set[str] = {
    "discovery",
    "inventory",
    "health",
    "sensors",
    "logs",
    "firmware",
    "boot",
    "bios",
    "tasks",
    "accounts",
    "virtualmedia",
    "raw",
    "schema",
    "power",
    "write",
}

PROFILE_TOOLSETS: dict[ToolProfile, set[str]] = {
    ToolProfile.CORE: {
        "discovery",
        "inventory",
        "health",
        "sensors",
        "logs",
        "firmware",
        "schema",
        "power",
        "boot",
    },
    ToolProfile.STANDARD: {
        "discovery",
        "inventory",
        "health",
        "sensors",
        "logs",
        "firmware",
        "boot",
        "bios",
        "tasks",
        "accounts",
        "virtualmedia",
        "schema",
        "power",
    },
    ToolProfile.FULL: set(ALL_TOOLSETS),
}

# Curated small-model surface. `core` is an exact allowlist, not a toolset union, so a
# destructive FULL-tier tool cannot enter `core` just by sharing a toolset with a read tool.
CORE_TOOLS: set[str] = {
    "list_systems",
    "get_system",
    "list_chassis",
    "get_health_summary",
    "get_thermal",
    "get_power",
    "get_sensors",
    "get_component_inventory",
    "get_firmware_inventory",
    "get_log_entries",
    "get_boot_config",
    "redfish_describe_schema",
    "redfish_list_available_actions",
    "set_power_state",
    "set_boot_override",
}

PROFILE_TOOLS: dict[ToolProfile, set[str]] = {
    ToolProfile.CORE: CORE_TOOLS,
}

# Toolsets whose tool descriptions direct the model at a tool from another toolset. Enabling the
# key without the value would advertise instructions the model cannot follow, so the companion is
# pulled in automatically. All named profiles already include every companion.
TOOLSET_COMPANIONS: dict[str, set[str]] = {
    # redfish_invoke_action tells the caller to run redfish_list_available_actions first.
    "write": {"schema"},
}


def _redfish_env_name(prefix: str, suffix: str) -> str:
    return f"{prefix}{suffix}"


def _redfish_env(suffix: str) -> str | None:
    namespaced_name = _redfish_env_name(NAMESPACED_REDFISH_PREFIX, suffix)
    namespaced_value = os.getenv(namespaced_name)
    if namespaced_value is not None:
        return namespaced_value
    legacy_name = _redfish_env_name(LEGACY_REDFISH_PREFIX, suffix)
    legacy_value = os.getenv(legacy_name)
    if legacy_value is None:
        return None
    if legacy_name not in _LEGACY_REDFISH_WARNED:
        LOGGER.warning(
            "Environment variable %s is deprecated; use %s instead.",
            legacy_name,
            namespaced_name,
        )
        _LEGACY_REDFISH_WARNED.add(legacy_name)
    return legacy_value


def _env_bool(suffix: str, default: bool) -> bool:
    value = _redfish_env(suffix)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(suffix: str, default: float) -> float:
    value = _redfish_env(suffix)
    if value is None or value.strip() == "":
        return default
    return float(value)


def _read_secret_from_file(path: str | None) -> str | None:
    if not path:
        return None
    return Path(path).read_text(encoding="utf-8").strip()


def _load_endpoints_payload(raw: str) -> dict[str, Any] | None:
    """Return the endpoint payload, or None when the configured file does not exist.

    An absent file is how directory scanners and container platforms inject a placeholder
    path, so it degrades to zero-endpoint discovery mode. A file that exists but cannot be
    read or parsed stays a hard failure, so a typo in a real deployment cannot silently
    downgrade it to zero endpoints.
    """
    raw = raw.strip()
    if raw.startswith("{") or raw.startswith("["):
        loaded = json.loads(raw)
        if not isinstance(loaded, dict):
            raise ValueError(
                "MIRASTACK_REDFISH_ENDPOINTS inline payload must be a JSON object"
            )
        return {str(k): v for k, v in loaded.items()}
    path = Path(raw)
    if not path.exists():
        LOGGER.warning(
            "MIRASTACK_REDFISH_ENDPOINTS path not found: %s; starting in discovery mode with "
            "zero endpoints",
            raw,
        )
        return None
    payload = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        loaded = yaml.safe_load(payload)
    else:
        loaded = json.loads(payload)
    if not isinstance(loaded, dict):
        raise ValueError("MIRASTACK_REDFISH_ENDPOINTS file must contain a JSON/YAML object")
    return {str(k): v for k, v in loaded.items()}


def _parse_endpoint_map(raw_endpoints: dict[str, Any]) -> dict[str, EndpointConfig]:
    parsed: dict[str, EndpointConfig] = {}
    for key, payload in raw_endpoints.items():
        if not isinstance(payload, dict):
            raise ValueError(f"endpoint '{key}' must map to an object")
        password = payload.get("password")
        if isinstance(password, str) and password == "":
            password = None
        password_file = payload.get("password_file")
        if password is None:
            password = _read_secret_from_file(password_file)
        if not isinstance(password, str) or password == "":
            raise ValueError(f"endpoint '{key}' must provide password or password_file")
        endpoint = EndpointConfig(
            name=str(payload.get("name") or key),
            base_url=str(payload["base_url"]),
            username=str(payload["username"]),
            password=password,
            verify_ssl=bool(payload.get("verify_ssl", True)),
            ca_bundle=payload.get("ca_bundle"),
            timeout_sec=float(payload.get("timeout_sec", 30.0)),
            read_only=bool(payload.get("read_only", False)),
            auth_mode=AuthMode(str(payload.get("auth_mode", "auto"))),
            headers={str(k): str(v) for k, v in dict(payload.get("headers", {})).items()},
        )
        parsed[endpoint.name] = endpoint
    return parsed


def _single_endpoint_from_env() -> EndpointConfig | None:
    host = _redfish_env("HOST")
    user = _redfish_env("USERNAME")
    password = _redfish_env("PASSWORD")
    password_file = _redfish_env("PASSWORD_FILE")
    if all(value is None for value in (host, user, password, password_file)):
        return None
    if password is None:
        password = _read_secret_from_file(password_file)

    if not host or not user or not password:
        raise ValueError(
            "missing endpoint configuration: set MIRASTACK_REDFISH_HOST, "
            "MIRASTACK_REDFISH_USERNAME, and MIRASTACK_REDFISH_PASSWORD "
            "(or MIRASTACK_REDFISH_PASSWORD_FILE)"
        )

    endpoint_name = _redfish_env("ENDPOINT_NAME") or "default"
    return EndpointConfig(
        name=endpoint_name,
        base_url=host,
        username=user,
        password=password,
        verify_ssl=_env_bool("VERIFY_SSL", True),
        ca_bundle=_redfish_env("CA_BUNDLE"),
        timeout_sec=_env_float("TIMEOUT_SEC", 30.0),
        read_only=_env_bool("READ_ONLY", False),
        auth_mode=AuthMode(_redfish_env("AUTH_MODE") or "auto"),
    )


def load_config() -> AppConfig:
    """Load complete app config from environment."""
    endpoints_env = _redfish_env("ENDPOINTS")
    endpoint_map: dict[str, EndpointConfig]
    if endpoints_env:
        payload = _load_endpoints_payload(endpoints_env)
        endpoint_map = {} if payload is None else _parse_endpoint_map(payload)
    else:
        endpoint = _single_endpoint_from_env()
        endpoint_map = {} if endpoint is None else {endpoint.name: endpoint}

    default_endpoint = _redfish_env("DEFAULT_ENDPOINT")
    if default_endpoint is None and endpoint_map:
        default_endpoint = next(iter(endpoint_map.keys()))

    profile_raw = (_redfish_env("TOOL_PROFILE") or ToolProfile.FULL.value).strip().lower()
    try:
        selected_profile = ToolProfile(profile_raw)
    except ValueError as exc:
        raise ValueError(
            "MIRASTACK_REDFISH_TOOL_PROFILE must be one of: core, standard, full"
        ) from exc
    if selected_profile is ToolProfile.CUSTOM:
        raise ValueError(
            "MIRASTACK_REDFISH_TOOL_PROFILE cannot be 'custom'; "
            "use MIRASTACK_REDFISH_TOOLSETS override"
        )

    enabled_toolsets = set(PROFILE_TOOLSETS[selected_profile])
    enabled_tools = set(PROFILE_TOOLS.get(selected_profile, set()))
    effective_profile: ToolProfile = selected_profile

    toolsets_env = (_redfish_env("TOOLSETS") or "").strip()
    if toolsets_env:
        enabled_toolsets = {item.strip() for item in toolsets_env.split(",") if item.strip()}
        unknown = enabled_toolsets.difference(ALL_TOOLSETS)
        if unknown:
            raise ValueError(f"unknown toolsets: {sorted(unknown)}")
        for toolset, companions in TOOLSET_COMPANIONS.items():
            if toolset in enabled_toolsets:
                enabled_toolsets |= companions
        enabled_tools = set()
        effective_profile = ToolProfile.CUSTOM

    write_mode = WriteMode(_redfish_env("WRITE_MODE") or WriteMode.OFF.value)
    schema_index_path = _redfish_env("SCHEMA_INDEX_PATH") or (
        "src/mirastack_redfish_mcp/data/redfish_index.json.gz"
    )

    return AppConfig(
        endpoints=endpoint_map,
        default_endpoint=default_endpoint,
        write_mode=write_mode,
        tool_profile=effective_profile,
        enabled_toolsets=enabled_toolsets,
        enabled_tools=enabled_tools,
        schema_index_path=schema_index_path,
        streamable_http_host=os.getenv("MCP_HTTP_HOST", "127.0.0.1"),
        streamable_http_port=int(os.getenv("MCP_HTTP_PORT", "8000")),
        streamable_http_path=os.getenv("MCP_HTTP_PATH", "/mcp"),
    )
