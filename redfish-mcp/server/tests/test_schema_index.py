from __future__ import annotations

from mirastack_redfish_mcp.schema.describe import describe_resource
from mirastack_redfish_mcp.schema.index import SchemaIndex
from mirastack_redfish_mcp.schema.resolver import UriResolver


def test_schema_index_has_core_resources(schema_index: SchemaIndex) -> None:
    for resource in ("ServiceRoot", "ComputerSystem", "Chassis", "Manager", "Task", "Sensor"):
        info = schema_index.get_resource(resource)
        assert info is not None, resource
        assert len(info.uris) >= 1


def test_uri_resolver_resolves_core_paths(uri_resolver: UriResolver) -> None:
    assert uri_resolver.resolve("/redfish/v1/Systems/437XR1138R2") is not None
    assert uri_resolver.resolve("/redfish/v1/Chassis/1U") is not None
    assert uri_resolver.resolve("/redfish/v1/Managers/BMC") is not None


def test_describe_resource_summary(schema_index: SchemaIndex) -> None:
    summary = describe_resource(schema_index, "ComputerSystem")
    assert summary is not None
    assert summary["resource_type"] == "ComputerSystem"
    assert summary["verbs"]["updatable"] in {True, False}


def test_schema_index_resolves_action_parameter_enum(schema_index: SchemaIndex) -> None:
    enum_info = schema_index.resolve_action_parameter_enum(
        "ComputerSystem",
        "#ComputerSystem.Reset",
        "ResetType",
    )
    assert enum_info is not None
    assert "ForceOff" in enum_info.values
    assert "non-graceful shutdown" in enum_info.descriptions.get("ForceOff", "")


def test_schema_index_handles_payload_without_enums() -> None:
    schema_index = SchemaIndex.from_payload({"resource_types": {}})
    assert schema_index.enums == {}
    assert schema_index.get_enum("Resource.json#/definitions/ResetType") is None
