from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest import MonkeyPatch

import mirastack_redfish_mcp.config as config_module
from mirastack_redfish_mcp.config import (
    CORE_TOOLS,
    PROFILE_TOOLSETS,
    TOOLSET_COMPANIONS,
    load_config,
)
from mirastack_redfish_mcp.models import ToolProfile, WriteMode

REDFISH_ENV_SUFFIXES = (
    "HOST",
    "USERNAME",
    "PASSWORD",
    "PASSWORD_FILE",
    "ENDPOINT_NAME",
    "VERIFY_SSL",
    "CA_BUNDLE",
    "TIMEOUT_SEC",
    "READ_ONLY",
    "AUTH_MODE",
    "ENDPOINTS",
    "DEFAULT_ENDPOINT",
    "TOOL_PROFILE",
    "TOOLSETS",
    "WRITE_MODE",
    "SCHEMA_INDEX_PATH",
)


def _clear_redfish_env(monkeypatch: MonkeyPatch) -> None:
    for prefix in ("MIRASTACK_REDFISH_", "REDFISH_"):
        for suffix in REDFISH_ENV_SUFFIXES:
            monkeypatch.delenv(f"{prefix}{suffix}", raising=False)


def test_load_config_single_endpoint(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("MIRASTACK_REDFISH_HOST", "https://192.0.2.10")
    monkeypatch.setenv("MIRASTACK_REDFISH_USERNAME", "admin")
    monkeypatch.setenv("MIRASTACK_REDFISH_PASSWORD", "secret")
    monkeypatch.setenv("MIRASTACK_REDFISH_WRITE_MODE", "power")
    cfg = load_config()
    assert cfg.default_endpoint == "default"
    assert "default" in cfg.endpoints
    assert cfg.write_mode is WriteMode.POWER
    assert cfg.tool_profile is ToolProfile.FULL


def test_load_config_multi_endpoint(monkeypatch: MonkeyPatch) -> None:
    endpoints = {
        "idrac-a": {
            "base_url": "https://192.0.2.10",
            "username": "operator-a",
            "password": "secret-a",
            "read_only": True,
        },
        "ilo-b": {
            "base_url": "https://192.0.2.11",
            "username": "operator-b",
            "password": "secret-b",
        },
    }
    monkeypatch.setenv("MIRASTACK_REDFISH_ENDPOINTS", json.dumps(endpoints))
    monkeypatch.setenv("MIRASTACK_REDFISH_DEFAULT_ENDPOINT", "ilo-b")
    cfg = load_config()
    assert set(cfg.endpoints.keys()) == {"idrac-a", "ilo-b"}
    assert cfg.default_endpoint == "ilo-b"
    assert cfg.endpoints["idrac-a"].read_only is True


def test_load_config_empty_environment_allows_discovery_mode(monkeypatch: MonkeyPatch) -> None:
    _clear_redfish_env(monkeypatch)
    cfg = load_config()
    assert cfg.endpoints == {}
    assert cfg.default_endpoint is None
    assert cfg.write_mode is WriteMode.OFF


def test_load_config_partial_single_endpoint_still_raises(monkeypatch: MonkeyPatch) -> None:
    _clear_redfish_env(monkeypatch)
    monkeypatch.setenv("MIRASTACK_REDFISH_HOST", "https://192.0.2.10")
    monkeypatch.setenv("MIRASTACK_REDFISH_USERNAME", "admin")
    with pytest.raises(ValueError, match="missing endpoint configuration"):
        load_config()


def test_load_config_malformed_endpoints_file_still_raises(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    _clear_redfish_env(monkeypatch)
    bad_file = tmp_path / "endpoints.yaml"
    bad_file.write_text("- this is not a mapping\n", encoding="utf-8")
    monkeypatch.setenv("MIRASTACK_REDFISH_ENDPOINTS", str(bad_file))
    with pytest.raises(ValueError, match="must contain a JSON/YAML object"):
        load_config()


def test_load_config_absent_endpoints_file_falls_back_to_discovery_mode(
    monkeypatch: MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Container platforms and directory scanners inject a placeholder endpoints path that is
    # never materialised; that must degrade to discovery mode, not kill the process.
    _clear_redfish_env(monkeypatch)
    missing = tmp_path / "redfish-endpoints.json"
    monkeypatch.setenv("MIRASTACK_REDFISH_ENDPOINTS", str(missing))
    caplog.set_level("WARNING")

    cfg = load_config()

    assert cfg.endpoints == {}
    assert cfg.default_endpoint is None
    warnings = [record.getMessage() for record in caplog.records]
    assert any(str(missing) in message for message in warnings), warnings
    assert any("discovery mode" in message for message in warnings), warnings


def test_load_config_inline_malformed_endpoints_json_still_raises(monkeypatch: MonkeyPatch) -> None:
    _clear_redfish_env(monkeypatch)
    monkeypatch.setenv("MIRASTACK_REDFISH_ENDPOINTS", '{"idrac-a": ')
    with pytest.raises(json.JSONDecodeError):
        load_config()


def test_load_config_endpoints_path_pointing_at_directory_still_raises(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    # The path exists, so this is a broken configuration rather than an absent one.
    _clear_redfish_env(monkeypatch)
    monkeypatch.setenv("MIRASTACK_REDFISH_ENDPOINTS", str(tmp_path))
    with pytest.raises(OSError):
        load_config()


def test_load_config_tool_profile_core(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("MIRASTACK_REDFISH_HOST", "https://192.0.2.10")
    monkeypatch.setenv("MIRASTACK_REDFISH_USERNAME", "admin")
    monkeypatch.setenv("MIRASTACK_REDFISH_PASSWORD", "secret")
    monkeypatch.setenv("MIRASTACK_REDFISH_TOOL_PROFILE", "core")
    cfg = load_config()
    assert cfg.tool_profile is ToolProfile.CORE
    assert "schema" in cfg.enabled_toolsets
    assert "write" not in cfg.enabled_toolsets
    assert cfg.enabled_tools == CORE_TOOLS
    assert "simple_update" not in cfg.enabled_tools


def test_load_config_toolsets_override_marks_custom(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("MIRASTACK_REDFISH_HOST", "https://192.0.2.10")
    monkeypatch.setenv("MIRASTACK_REDFISH_USERNAME", "admin")
    monkeypatch.setenv("MIRASTACK_REDFISH_PASSWORD", "secret")
    monkeypatch.setenv("MIRASTACK_REDFISH_TOOL_PROFILE", "core")
    monkeypatch.setenv("MIRASTACK_REDFISH_TOOLSETS", "discovery,schema,write")
    cfg = load_config()
    assert cfg.tool_profile is ToolProfile.CUSTOM
    assert cfg.enabled_toolsets == {"discovery", "schema", "write"}
    assert cfg.enabled_tools == set()


def test_write_toolset_pulls_in_its_companion(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("MIRASTACK_REDFISH_HOST", "https://192.0.2.10")
    monkeypatch.setenv("MIRASTACK_REDFISH_USERNAME", "admin")
    monkeypatch.setenv("MIRASTACK_REDFISH_PASSWORD", "secret")
    monkeypatch.setenv("MIRASTACK_REDFISH_TOOLSETS", "write")
    cfg = load_config()
    # redfish_invoke_action tells the model to call redfish_list_available_actions, which lives
    # in the schema toolset, so schema must come along.
    assert cfg.enabled_toolsets == {"write", "schema"}


def test_named_profiles_already_satisfy_every_companion() -> None:
    for toolset, companions in TOOLSET_COMPANIONS.items():
        for profile, toolsets in PROFILE_TOOLSETS.items():
            if toolset in toolsets:
                assert companions <= toolsets, f"profile {profile} enables {toolset} without {companions}"


def test_verify_ssl_defaults_to_true(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("MIRASTACK_REDFISH_HOST", "https://192.0.2.10")
    monkeypatch.setenv("MIRASTACK_REDFISH_USERNAME", "admin")
    monkeypatch.setenv("MIRASTACK_REDFISH_PASSWORD", "secret")
    monkeypatch.delenv("MIRASTACK_REDFISH_VERIFY_SSL", raising=False)
    cfg = load_config()
    assert cfg.endpoints["default"].verify_ssl is True


def test_namespaced_env_takes_precedence_over_legacy(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("MIRASTACK_REDFISH_HOST", "https://192.0.2.10")
    monkeypatch.setenv("REDFISH_HOST", "https://192.0.2.11")
    monkeypatch.setenv("MIRASTACK_REDFISH_USERNAME", "admin")
    monkeypatch.setenv("REDFISH_USERNAME", "legacy-user")
    monkeypatch.setenv("MIRASTACK_REDFISH_PASSWORD", "secret")
    monkeypatch.setenv("REDFISH_PASSWORD", "legacy-secret")
    cfg = load_config()
    assert cfg.endpoints["default"].base_url == "https://192.0.2.10"
    assert cfg.endpoints["default"].username == "admin"
    assert cfg.endpoints["default"].password == "secret"


def test_legacy_env_fallback_logs_deprecation_once(
    monkeypatch: MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    config_module._LEGACY_REDFISH_WARNED.clear()
    monkeypatch.setenv("REDFISH_HOST", "https://192.0.2.10")
    monkeypatch.setenv("REDFISH_USERNAME", "legacy-user")
    monkeypatch.setenv("REDFISH_PASSWORD", "legacy-secret")
    caplog.set_level("WARNING")

    load_config()
    first_count = sum("deprecated; use MIRASTACK_REDFISH_" in r.message for r in caplog.records)
    load_config()
    second_count = sum("deprecated; use MIRASTACK_REDFISH_" in r.message for r in caplog.records)

    assert first_count >= 3
    assert second_count == first_count
