from __future__ import annotations

from mirastack_redfish_mcp.schema.docs import action_help, enum_help, property_help
from mirastack_redfish_mcp.schema.index import SchemaIndex


def test_enum_help_truncates_and_preserves_meaning(schema_index: SchemaIndex) -> None:
    enum_info = schema_index.get_enum("Resource.json#/definitions/ResetType")
    assert enum_info is not None
    rendered = enum_help(enum_info, max_values=3, max_chars=250)
    assert "ForceOff" in rendered
    assert "more values" in rendered
    assert len(rendered) <= 250


def test_property_help_surfaces_deprecation(schema_index: SchemaIndex) -> None:
    rendered = property_help(schema_index, "ComputerSystem", "IndicatorLED")
    assert "IndicatorLED" in rendered
    assert "deprec" in rendered.lower()


def test_action_help_contains_allowable_values(schema_index: SchemaIndex) -> None:
    rendered = action_help(schema_index, "ComputerSystem", "#ComputerSystem.Reset")
    assert "ResetType" in rendered
    assert "ForceOff" in rendered


def test_enum_help_renders_single_spaced_deprecation_marker(schema_index: SchemaIndex) -> None:
    checked = 0
    for enum_info in schema_index.enums.values():
        if not enum_info.version_deprecated:
            continue
        rendered = enum_help(enum_info, max_values=64, max_chars=4000)
        assert "(deprecated) (deprecated since" not in rendered
        assert ".(deprecated" not in rendered
        checked += 1
    assert checked > 0
