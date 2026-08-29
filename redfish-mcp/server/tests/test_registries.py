from __future__ import annotations

import pytest

from mirastack_redfish_mcp.redfish.registries import RegistryStore
from mirastack_redfish_mcp.schema.index import SchemaIndex


@pytest.mark.asyncio
async def test_registry_store_renders_base_message(schema_index: SchemaIndex) -> None:
    store = RegistryStore(schema_index.data)
    rendered = await store.render_message(
        "Base.1.0.PropertyValueNotInList",
        ["InvalidValue", "Status"],
    )
    assert rendered is not None
    assert "InvalidValue" in rendered[0]
    assert "Status" in rendered[0]
