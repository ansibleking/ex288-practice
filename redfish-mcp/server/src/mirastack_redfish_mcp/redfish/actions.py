"""Redfish action metadata helpers (`AllowableValues`, `ActionInfo`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ActionParameter:
    """Action argument metadata from payload annotations or ActionInfo."""

    name: str
    required: bool = False
    data_type: str | None = None
    allowable_values: list[str] = field(default_factory=list)
    allowable_numbers: list[float] = field(default_factory=list)
    allowable_pattern: str | None = None
    minimum_value: float | None = None
    maximum_value: float | None = None


@dataclass(slots=True)
class ActionInstance:
    """Live action information available on a resource payload."""

    key: str
    target: str
    title: str | None
    action_info_uri: str | None
    parameters: dict[str, ActionParameter]


def _normalize_action_key(action_name: str) -> str:
    if action_name.startswith("#"):
        return action_name
    return f"#{action_name}"


def extract_action_instance(resource: dict[str, Any], action_name: str) -> ActionInstance | None:
    """Extract one action instance from a Redfish resource payload."""
    actions = resource.get("Actions")
    if not isinstance(actions, dict):
        return None
    normalized = _normalize_action_key(action_name)
    payload = actions.get(normalized)
    if not isinstance(payload, dict):
        return None
    target = payload.get("target")
    if not isinstance(target, str) or not target.strip():
        return None
    params: dict[str, ActionParameter] = {}
    for key, value in payload.items():
        if not key.endswith("@Redfish.AllowableValues"):
            continue
        param_name = key.split("@", 1)[0]
        if not isinstance(value, list):
            continue
        params[param_name] = ActionParameter(
            name=param_name, allowable_values=[str(item) for item in value]
        )
    info_uri = payload.get("@Redfish.ActionInfo")
    return ActionInstance(
        key=normalized,
        target=target,
        title=payload.get("title") if isinstance(payload.get("title"), str) else None,
        action_info_uri=info_uri if isinstance(info_uri, str) else None,
        parameters=params,
    )


def merge_action_info(
    action: ActionInstance, action_info_payload: dict[str, Any]
) -> ActionInstance:
    """Merge ActionInfo payload data into a live action instance."""
    params = dict(action.parameters)
    parameters = action_info_payload.get("Parameters")
    if isinstance(parameters, list):
        for item in parameters:
            if not isinstance(item, dict):
                continue
            name = item.get("Name")
            if not isinstance(name, str) or not name:
                continue
            parameter = params.get(name, ActionParameter(name=name))
            parameter.required = bool(item.get("Required", parameter.required))
            data_type = item.get("DataType")
            if isinstance(data_type, str):
                parameter.data_type = data_type
            allowable_values = item.get("AllowableValues")
            if isinstance(allowable_values, list):
                parameter.allowable_values = [str(v) for v in allowable_values]
            allowable_numbers = item.get("AllowableNumbers")
            if isinstance(allowable_numbers, list):
                parameter.allowable_numbers = [float(v) for v in allowable_numbers]
            allowable_pattern = item.get("AllowablePattern")
            if isinstance(allowable_pattern, str):
                parameter.allowable_pattern = allowable_pattern
            min_value = item.get("MinimumValue")
            max_value = item.get("MaximumValue")
            if isinstance(min_value, (float, int)):
                parameter.minimum_value = float(min_value)
            if isinstance(max_value, (float, int)):
                parameter.maximum_value = float(max_value)
            params[name] = parameter
    action.parameters = params
    return action
