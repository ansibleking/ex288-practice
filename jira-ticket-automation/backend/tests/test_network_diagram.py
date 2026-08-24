from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.network_diagram import (
    MAX_DIAGRAM_ROWS,
    DiagramEdge,
    DiagramNode,
    NetworkDiagram,
    _format_sheet,
    generate_network_diagram,
)


def _settings() -> Settings:
    return Settings(
        jira_base_url="https://jira.example.internal",
        jira_pat="test-token",
        jira_project_key="SDIMD",
        onprem_llm_base_url="https://onprem.example.internal/v1",
    )


def _mock_llm_client(parsed: NetworkDiagram | None = None, error: Exception | None = None) -> AsyncMock:
    client = AsyncMock()
    if error is not None:
        client.parse.side_effect = error
    else:
        client.parse.return_value = parsed
    return client


@pytest.mark.asyncio
async def test_generate_network_diagram_returns_parsed_graph_and_uses_given_client():
    parsed = NetworkDiagram(
        nodes=[
            DiagramNode(id="web01", label="web01 (10.0.0.1)", role="source", zone="internal"),
            DiagramNode(id="db01", label="db01 (10.0.0.5)", role="destination", zone="internal"),
        ],
        edges=[
            DiagramEdge(
                source_id="web01",
                target_id="db01",
                label="TCP/5432",
                status="approved",
                reason="Application connection pool",
            )
        ],
        summary="web01 is granted database access to db01 over 5432.",
    )
    client = _mock_llm_client(parsed)

    result = await generate_network_diagram(
        ["Source", "Destination", "Port"], [["web01", "db01", "5432"]], _settings(), llm_client=client
    )

    assert result is parsed
    call_kwargs = client.parse.await_args.kwargs
    assert call_kwargs["output_model"] is NetworkDiagram
    assert "web01" in call_kwargs["user_content"]
    # must not close a client it didn't create itself
    client.aclose.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_network_diagram_propagates_llm_errors():
    client = _mock_llm_client(error=ValueError("bad schema"))

    with pytest.raises(ValueError):
        await generate_network_diagram(["Source"], [["web01"]], _settings(), llm_client=client)


def test_diagram_node_requires_zone_and_edge_reason_defaults_to_none():
    node = DiagramNode(id="web01", label="web01", role="source", zone="dmz")
    edge = DiagramEdge(source_id="web01", target_id="db01", label="443", status="approved")

    assert node.zone == "dmz"
    assert edge.reason is None


def test_format_sheet_includes_headers_and_rows():
    text = _format_sheet(["Source", "Destination"], [["web01", "db01"]])

    assert "Columns: Source | Destination" in text
    assert "web01 | db01" in text


def test_format_sheet_truncates_and_notes_omitted_rows():
    rows = [[f"host{i}", "db01"] for i in range(MAX_DIAGRAM_ROWS + 10)]

    text = _format_sheet(["Source", "Destination"], rows)

    assert "10 more rows omitted" in text
    assert text.count("host") == MAX_DIAGRAM_ROWS
