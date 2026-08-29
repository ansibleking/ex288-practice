from __future__ import annotations

import json

import pytest
from pytest import MonkeyPatch

from mirastack_redfish_mcp.runtime import RedfishRuntime


def test_runtime_warns_when_single_endpoint_disables_tls(
    monkeypatch: MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("MIRASTACK_REDFISH_HOST", "https://192.0.2.10")
    monkeypatch.setenv("MIRASTACK_REDFISH_USERNAME", "admin")
    monkeypatch.setenv("MIRASTACK_REDFISH_PASSWORD", "secret")
    monkeypatch.setenv("MIRASTACK_REDFISH_VERIFY_SSL", "false")
    caplog.set_level("WARNING")

    RedfishRuntime()

    assert any(
        "Endpoint 'default' has TLS certificate verification disabled" in record.message
        for record in caplog.records
    )


def test_runtime_warns_only_for_insecure_endpoints(
    monkeypatch: MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    endpoints = {
        "secure-a": {
            "base_url": "https://192.0.2.10",
            "username": "user-a",
            "password": "secret-a",
            "verify_ssl": True,
        },
        "lab-b": {
            "base_url": "https://192.0.2.11",
            "username": "user-b",
            "password": "secret-b",
            "verify_ssl": False,
        },
    }
    monkeypatch.setenv("MIRASTACK_REDFISH_ENDPOINTS", json.dumps(endpoints))
    caplog.set_level("WARNING")

    RedfishRuntime()

    warnings = [record.message for record in caplog.records]
    assert any("Endpoint 'lab-b' has TLS certificate verification disabled" in msg for msg in warnings)
    assert not any("Endpoint 'secure-a' has TLS certificate verification disabled" in msg for msg in warnings)
