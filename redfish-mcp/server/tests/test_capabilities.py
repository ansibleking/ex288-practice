from __future__ import annotations

from mirastack_redfish_mcp.redfish.capabilities import apply_query_support, parse_capabilities


def test_parse_capabilities() -> None:
    service_root = {
        "RedfishVersion": "1.15.0",
        "ProtocolFeaturesSupported": {
            "ExpandQuery": {"MaxLevels": 6},
            "SelectQuery": True,
            "OnlyMemberQuery": True,
            "ExcerptQuery": False,
        },
    }
    caps = parse_capabilities(service_root)
    assert caps.redfish_version == "1.15.0"
    assert caps.expand_query is True
    assert caps.select_query is True
    assert caps.only_query is True
    assert caps.excerpt_query is False
    assert caps.max_expand_levels == 6


def test_apply_query_support_gates_unsupported() -> None:
    service_root = {"ProtocolFeaturesSupported": {"SelectQuery": True}}
    caps = parse_capabilities(service_root)
    params = apply_query_support(
        capabilities=caps,
        expand="*",
        select="Id,Name",
        only="status",
        excerpt="Sensor",
    )
    assert "$select" in params
    assert "$expand" not in params
    assert "only" not in params
    assert "excerpt" not in params
