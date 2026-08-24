from unittest.mock import AsyncMock

import pytest

from app.classifier import CandidateTicket, FeedClassification, Intent, Severity, classify
from app.config import Settings


def _settings() -> Settings:
    return Settings(
        jira_base_url="https://jira.example.internal",
        jira_pat="test-token",
        jira_project_key="AIOPS",
        anthropic_api_key="test-anthropic-key",
    )


def _mock_llm_client(parsed: FeedClassification | None = None, error: Exception | None = None) -> AsyncMock:
    client = AsyncMock()
    if error is not None:
        client.parse.side_effect = error
    else:
        client.parse.return_value = parsed
    return client


@pytest.mark.asyncio
async def test_classify_returns_parsed_output_and_includes_candidates_in_prompt():
    parsed = FeedClassification(
        intent=Intent.NEW_ISSUE,
        confidence=0.9,
        severity=Severity.HIGH,
        matched_ticket_key=None,
        title="DB pool exhaustion",
        summary="Connection pool exhausted on payments-svc",
        reasoning="Clear new incident, no existing candidate matches",
    )
    client = _mock_llm_client(parsed)

    result = await classify(
        text="payments-svc is throwing intermittent 503s",
        candidates=[CandidateTicket(key="AIOPS-1", summary="Unrelated", description_excerpt="...")],
        settings=_settings(),
        llm_client=client,
    )

    assert result.title == "DB pool exhaustion"
    call_kwargs = client.parse.await_args.kwargs
    assert call_kwargs["output_model"] is FeedClassification
    user_content = call_kwargs["user_content"]
    assert "AIOPS-1" in user_content
    assert "payments-svc is throwing intermittent 503s" in user_content
    # classify() must not close a client it didn't create itself.
    client.aclose.assert_not_awaited()


@pytest.mark.asyncio
async def test_classify_nulls_matched_key_when_not_a_real_candidate():
    parsed = FeedClassification(
        intent=Intent.UPDATE_EXISTING,
        confidence=0.8,
        severity=Severity.MEDIUM,
        matched_ticket_key="AIOPS-999",  # hallucinated -- not in candidates
        title="ignored",
        summary="ignored",
        reasoning="ignored",
    )
    client = _mock_llm_client(parsed)

    result = await classify(
        text="more detail on the earlier issue",
        candidates=[CandidateTicket(key="AIOPS-1", summary="Real ticket", description_excerpt="...")],
        settings=_settings(),
        llm_client=client,
    )

    assert result.matched_ticket_key is None


@pytest.mark.asyncio
async def test_classify_forces_null_match_for_new_issue_intent():
    parsed = FeedClassification(
        intent=Intent.NEW_ISSUE,
        confidence=0.9,
        severity=Severity.LOW,
        matched_ticket_key="AIOPS-1",  # model shouldn't do this, but defend anyway
        title="ignored",
        summary="ignored",
        reasoning="ignored",
    )
    client = _mock_llm_client(parsed)

    result = await classify(
        text="something new",
        candidates=[CandidateTicket(key="AIOPS-1", summary="Real ticket", description_excerpt="...")],
        settings=_settings(),
        llm_client=client,
    )

    assert result.matched_ticket_key is None


@pytest.mark.asyncio
async def test_classify_forces_null_match_for_service_request_intent():
    parsed = FeedClassification(
        intent=Intent.SERVICE_REQUEST,
        confidence=0.9,
        severity=Severity.LOW,
        matched_ticket_key="AIOPS-1",  # model shouldn't do this, but defend anyway
        title="Provision VPN access",
        summary="New contractor needs VPN access",
        reasoning="Clear actionable request, not an incident",
    )
    client = _mock_llm_client(parsed)

    result = await classify(
        text="Please provision VPN access for a new contractor",
        candidates=[CandidateTicket(key="AIOPS-1", summary="Real ticket", description_excerpt="...")],
        settings=_settings(),
        llm_client=client,
    )

    assert result.intent is Intent.SERVICE_REQUEST
    assert result.matched_ticket_key is None


@pytest.mark.asyncio
async def test_classify_preserves_valid_matched_key():
    parsed = FeedClassification(
        intent=Intent.RESOLVED,
        confidence=0.95,
        severity=Severity.LOW,
        matched_ticket_key="AIOPS-1",
        title="ignored",
        summary="ignored",
        reasoning="ignored",
        resolution_comment="Confirmed fixed after deploy",
    )
    client = _mock_llm_client(parsed)

    result = await classify(
        text="the payments issue is fixed now",
        candidates=[CandidateTicket(key="AIOPS-1", summary="Payments issue", description_excerpt="...")],
        settings=_settings(),
        llm_client=client,
    )

    assert result.matched_ticket_key == "AIOPS-1"
    assert result.resolution_comment == "Confirmed fixed after deploy"


@pytest.mark.asyncio
async def test_classify_propagates_llm_client_errors():
    client = _mock_llm_client(error=ValueError("did not return parsed output (stop_reason=refusal)"))

    with pytest.raises(ValueError, match="refusal"):
        await classify(
            text="something",
            candidates=[],
            settings=_settings(),
            llm_client=client,
        )


@pytest.mark.asyncio
async def test_classify_closes_a_client_it_created_itself(monkeypatch):
    parsed = FeedClassification(
        intent=Intent.NOISE,
        confidence=0.5,
        severity=Severity.LOW,
        matched_ticket_key=None,
        title="ignored",
        summary="ignored",
        reasoning="ignored",
    )
    owned_client = _mock_llm_client(parsed)
    monkeypatch.setattr("app.classifier.get_llm_client", lambda settings: owned_client)

    await classify(text="hi", candidates=[], settings=_settings())

    owned_client.aclose.assert_awaited_once()
