from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import pytest

from mirastack_redfish_mcp.redfish.actions import ActionInstance, ActionParameter
from mirastack_redfish_mcp.tools.write import _validate_action_payload


@dataclass
class _DummyResolver:
    def resolve(self, uri: str) -> None:  # pragma: no cover - fallback path only
        return None


@dataclass
class _DummySchemaIndex:
    def get_resource(self, resource_type: str) -> None:  # pragma: no cover - fallback path only
        return None

    def get_enum(self, enum_ref: str) -> None:  # pragma: no cover - fallback path only
        return None


@dataclass
class _DummyRuntime:
    uri_resolver: _DummyResolver
    schema_index: _DummySchemaIndex


def _runtime() -> _DummyRuntime:
    return _DummyRuntime(uri_resolver=_DummyResolver(), schema_index=_DummySchemaIndex())


def test_validate_action_payload_rejects_invalid_allowable_value() -> None:
    action = ActionInstance(
        key="#ComputerSystem.Reset",
        target="/redfish/v1/Systems/1/Actions/ComputerSystem.Reset",
        title="Reset",
        action_info_uri=None,
        parameters={
            "ResetType": ActionParameter(
                name="ResetType",
                required=True,
                allowable_values=["On", "ForceOff"],
            )
        },
    )
    with pytest.raises(ValueError, match="Allowed values"):
        _validate_action_payload(
            runtime=cast(Any, _runtime()),
            resource_uri="/redfish/v1/Systems/1",
            action_name="ComputerSystem.Reset",
            action=action,
            payload={"ResetType": "PowerOff"},
        )


def test_validate_action_payload_accepts_valid_allowable_value() -> None:
    action = ActionInstance(
        key="#ComputerSystem.Reset",
        target="/redfish/v1/Systems/1/Actions/ComputerSystem.Reset",
        title="Reset",
        action_info_uri=None,
        parameters={
            "ResetType": ActionParameter(
                name="ResetType",
                required=True,
                allowable_values=["On", "ForceOff"],
            )
        },
    )
    _validate_action_payload(
        runtime=cast(Any, _runtime()),
        resource_uri="/redfish/v1/Systems/1",
        action_name="ComputerSystem.Reset",
        action=action,
        payload={"ResetType": "ForceOff"},
    )
