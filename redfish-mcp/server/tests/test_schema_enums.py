from __future__ import annotations

from mirastack_redfish_mcp.schema.index import SchemaIndex


def test_reset_type_enum_has_expected_values(schema_index: SchemaIndex) -> None:
    enum_info = schema_index.get_enum("Resource.json#/definitions/ResetType")
    assert enum_info is not None
    assert len(enum_info.values) == 15
    assert "ForceOff" in enum_info.values
    assert "non-graceful shutdown" in enum_info.descriptions.get("ForceOff", "")


def test_boot_source_enum_has_expected_values(schema_index: SchemaIndex) -> None:
    enum_info = schema_index.get_enum("ComputerSystem.json#/definitions/BootSource")
    assert enum_info is not None
    assert len(enum_info.values) == 16
    assert "Pxe" in enum_info.values
    assert "UefiHttp" in enum_info.values


def test_enum_ref_coverage_floor(schema_index: SchemaIndex) -> None:
    action_param_refs = 0
    property_refs = 0
    for resource in schema_index.resource_types.values():
        for action in resource.actions.values():
            if not isinstance(action, dict):
                continue
            parameters = action.get("parameters")
            if not isinstance(parameters, dict):
                continue
            for parameter in parameters.values():
                if isinstance(parameter, dict) and isinstance(parameter.get("enum_ref"), str):
                    action_param_refs += 1
        for prop in resource.properties.values():
            if isinstance(prop, dict) and isinstance(prop.get("enum_ref"), str):
                property_refs += 1
    assert action_param_refs >= 60
    assert property_refs >= 200
