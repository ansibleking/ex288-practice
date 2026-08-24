from unittest.mock import AsyncMock

import pytest

from app.approval_summary import ApprovalSummary, summarize_for_approval
from app.config import Settings
from app.tickets import FieldEntry, TicketApprovalDetail


def _settings() -> Settings:
    return Settings(
        jira_base_url="https://jira.example.internal",
        jira_pat="test-token",
        jira_project_key="SDIMD",
        anthropic_api_key="test-anthropic-key",
    )


def _ticket(**overrides) -> TicketApprovalDetail:
    defaults = dict(
        key="SDIMD-74126",
        summary="Biohub WSUS+AV server - Memory increase request",
        description="Memory utilization exceeded 90%, please increase.",
        status="Pending Line Manager",
        issue_type="IT Set Up - Hardware",
        assignee="Mayilvahanan T",
        reporter="Ilyas Ahmed",
        created="2026-08-01T09:00:00.000+0000",
        updated="2026-08-10T09:00:00.000+0000",
        url="https://jira.example.internal/browse/SDIMD-74126",
        fields=[FieldEntry(label="Environment", value="Production")],
        transitions=[],
        attachments=[],
    )
    defaults.update(overrides)
    return TicketApprovalDetail(**defaults)


def _mock_llm_client(parsed: ApprovalSummary | None = None, error: Exception | None = None) -> AsyncMock:
    client = AsyncMock()
    if error is not None:
        client.parse.side_effect = error
    else:
        client.parse.return_value = parsed
    return client


@pytest.mark.asyncio
async def test_summarize_for_approval_returns_parsed_output_and_includes_ticket_content():
    parsed = ApprovalSummary(
        overview="Requests a memory increase for a production VM.",
        key_details=["bhmanwsus01, Biohub project, Production"],
        concerns=[],
        recommendation="approve",
        reasoning="Routine capacity request with clear justification.",
    )
    client = _mock_llm_client(parsed)

    result = await summarize_for_approval(_ticket(), _settings(), llm_client=client)

    assert result.recommendation == "approve"
    call_kwargs = client.parse.await_args.kwargs
    assert call_kwargs["output_model"] is ApprovalSummary
    user_content = call_kwargs["user_content"]
    assert "Biohub WSUS+AV server - Memory increase request" in user_content
    assert "Environment: Production" in user_content
    # must not close a client it didn't create itself
    client.aclose.assert_not_awaited()


@pytest.mark.asyncio
async def test_summarize_for_approval_notes_when_no_extra_fields():
    client = _mock_llm_client(
        ApprovalSummary(
            overview="x", key_details=[], concerns=[], recommendation="needs_more_info", reasoning="thin"
        )
    )

    await summarize_for_approval(_ticket(fields=[]), _settings(), llm_client=client)

    user_content = client.parse.await_args.kwargs["user_content"]
    assert "(none)" in user_content


@pytest.mark.asyncio
async def test_summarize_for_approval_propagates_llm_client_errors():
    client = _mock_llm_client(error=ValueError("did not return parsed output"))

    with pytest.raises(ValueError):
        await summarize_for_approval(_ticket(), _settings(), llm_client=client)
