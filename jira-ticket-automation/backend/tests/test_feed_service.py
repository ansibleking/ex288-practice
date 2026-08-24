from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.audit import STATUS_CANCELLED, STATUS_CONFIRMED, STATUS_EXECUTED, STATUS_FAILED, STATUS_PENDING, STATUS_SKIPPED, AuditStore
from app.classifier import FeedClassification, Intent, Severity
from app.config import Settings
from app.feed_service import PendingActionError, cancel_pending, confirm_pending, process_feed
from app.jira_client import JiraClientError
from app.models import ConfirmOverrides


def _settings() -> Settings:
    return Settings(
        jira_base_url="https://jira.example.internal",
        jira_pat="test-token",
        jira_project_key="AIOPS",
        jira_issue_type="Task",
        jira_managed_label="aiops-managed",
        jira_resolved_transition_name="Done",
        anthropic_api_key="test-anthropic-key",
    )


def _jira_with_no_candidates() -> AsyncMock:
    jira = AsyncMock()
    jira.search_issues.return_value = {"issues": []}
    return jira


def _classification(**overrides) -> FeedClassification:
    defaults = dict(
        intent=Intent.NEW_ISSUE,
        confidence=0.95,
        severity=Severity.LOW,
        matched_ticket_key=None,
        title="DB pool exhaustion",
        summary="Seeing intermittent 503s",
        reasoning="clear signal",
    )
    defaults.update(overrides)
    return FeedClassification(**defaults)


@pytest.fixture
def audit_store(tmp_path):
    return AuditStore(str(tmp_path / "audit.db"))


def _patch_classify(monkeypatch, classification: FeedClassification):
    async def fake_classify(text, candidates, settings, client=None):
        return classification

    monkeypatch.setattr("app.feed_service.classify", fake_classify)


@pytest.mark.asyncio
async def test_process_feed_skips_noise_without_touching_jira(monkeypatch, audit_store):
    _patch_classify(monkeypatch, _classification(intent=Intent.NOISE))
    jira = _jira_with_no_candidates()

    response = await process_feed("hello there", "chat", jira, _settings(), audit_store)

    assert response.action_status == STATUS_SKIPPED
    assert response.jira_issue_key is None
    jira.create_issue.assert_not_awaited()

    row = await audit_store.get(response.audit_id)
    assert row.action_status == STATUS_SKIPPED
    assert row.llm_intent == "noise"


@pytest.mark.asyncio
async def test_process_feed_auto_creates_and_records_success(monkeypatch, audit_store):
    _patch_classify(monkeypatch, _classification(confidence=0.95, severity=Severity.LOW))
    jira = _jira_with_no_candidates()
    jira.create_issue.return_value = {"key": "AIOPS-42"}

    response = await process_feed("payments-svc 503s", "chat", jira, _settings(), audit_store)

    assert response.action_status == STATUS_EXECUTED
    assert response.jira_issue_key == "AIOPS-42"
    jira.create_issue.assert_awaited_once()

    row = await audit_store.get(response.audit_id)
    assert row.action_status == STATUS_EXECUTED
    assert row.jira_issue_key == "AIOPS-42"


@pytest.mark.asyncio
async def test_process_feed_auto_create_failure_records_failed_status(monkeypatch, audit_store):
    _patch_classify(monkeypatch, _classification(confidence=0.95, severity=Severity.LOW))
    jira = _jira_with_no_candidates()
    jira.create_issue.side_effect = JiraClientError("Jira 500")

    response = await process_feed("payments-svc 503s", "chat", jira, _settings(), audit_store)

    assert response.action_status == STATUS_FAILED
    assert response.jira_issue_key is None

    row = await audit_store.get(response.audit_id)
    assert row.action_status == STATUS_FAILED
    assert "Jira 500" in row.jira_error


@pytest.mark.asyncio
async def test_process_feed_passes_issue_type_override_to_auto_create(monkeypatch, audit_store):
    _patch_classify(monkeypatch, _classification(confidence=0.95, severity=Severity.LOW))
    jira = _jira_with_no_candidates()
    jira.create_issue.return_value = {"key": "AIOPS-50"}

    await process_feed(
        "payments-svc 503s", "chat", jira, _settings(), audit_store, issue_type="Service Request"
    )

    create_kwargs = jira.create_issue.await_args.kwargs
    assert create_kwargs["issue_type"] == "Service Request"


@pytest.mark.asyncio
async def test_process_feed_passes_reporting_service_key_to_auto_create(monkeypatch, audit_store):
    _patch_classify(monkeypatch, _classification(confidence=0.95, severity=Severity.LOW))
    jira = _jira_with_no_candidates()
    jira.create_issue.return_value = {"key": "AIOPS-51"}
    settings = _settings().model_copy(update={"jira_reporting_service_field_id": "customfield_14503"})

    await process_feed(
        "payments-svc 503s", "chat", jira, settings, audit_store, reporting_service_key="SD-1179"
    )

    create_kwargs = jira.create_issue.await_args.kwargs
    assert create_kwargs["extra_fields"] == {"customfield_14503": [{"key": "SD-1179"}]}


@pytest.mark.asyncio
async def test_process_feed_passes_extra_field_values_to_auto_create(monkeypatch, audit_store):
    _patch_classify(monkeypatch, _classification(confidence=0.95, severity=Severity.LOW))
    jira = _jira_with_no_candidates()
    jira.create_issue.return_value = {"key": "AIOPS-52"}
    settings = _settings().model_copy(update={"jira_extra_select_fields": {"customfield_36200": "Subsidiary"}})

    await process_feed(
        "payments-svc 503s",
        "chat",
        jira,
        settings,
        audit_store,
        extra_field_values={"customfield_36200": "43503"},
    )

    create_kwargs = jira.create_issue.await_args.kwargs
    assert create_kwargs["extra_fields"] == {"customfield_36200": {"id": "43503"}}


@pytest.mark.asyncio
async def test_process_feed_low_confidence_proposes_without_touching_jira(monkeypatch, audit_store):
    _patch_classify(monkeypatch, _classification(confidence=0.2, severity=Severity.LOW))
    jira = _jira_with_no_candidates()

    response = await process_feed("maybe something odd?", "chat", jira, _settings(), audit_store)

    assert response.action_status == STATUS_PENDING
    assert response.jira_issue_key is None
    jira.create_issue.assert_not_awaited()

    row = await audit_store.get(response.audit_id)
    assert row.action_status == STATUS_PENDING
    assert row.jira_action_type == "create"


@pytest.mark.asyncio
async def test_confirm_pending_executes_the_proposed_action(monkeypatch, audit_store):
    _patch_classify(monkeypatch, _classification(confidence=0.2, severity=Severity.LOW))
    jira = _jira_with_no_candidates()
    pending = await process_feed("maybe something odd?", "chat", jira, _settings(), audit_store)
    assert pending.action_status == STATUS_PENDING

    jira.create_issue.return_value = {"key": "AIOPS-99"}
    confirmed = await confirm_pending(pending.audit_id, jira, _settings(), audit_store)

    assert confirmed is not None
    assert confirmed.action_status == STATUS_CONFIRMED
    assert confirmed.jira_issue_key == "AIOPS-99"
    jira.create_issue.assert_awaited_once()

    row = await audit_store.get(pending.audit_id)
    assert row.action_status == STATUS_CONFIRMED
    assert row.id == pending.audit_id  # updated in place, not a new row


@pytest.mark.asyncio
async def test_confirm_pending_applies_title_and_severity_overrides(monkeypatch, audit_store):
    _patch_classify(monkeypatch, _classification(confidence=0.2, severity=Severity.LOW, title="Original title"))
    jira = _jira_with_no_candidates()
    pending = await process_feed("maybe something odd?", "chat", jira, _settings(), audit_store)

    jira.create_issue.return_value = {"key": "AIOPS-100"}
    confirmed = await confirm_pending(
        pending.audit_id,
        jira,
        _settings(),
        audit_store,
        overrides=ConfirmOverrides(title="Edited title", severity=Severity.HIGH),
    )

    assert confirmed is not None
    assert confirmed.classification.title == "Edited title"
    assert confirmed.classification.severity == Severity.HIGH
    create_kwargs = jira.create_issue.await_args.kwargs
    assert create_kwargs["summary"] == "Edited title"


@pytest.mark.asyncio
async def test_confirm_pending_applies_issue_type_override_without_touching_classification(
    monkeypatch, audit_store
):
    _patch_classify(monkeypatch, _classification(confidence=0.2, severity=Severity.LOW, title="Original title"))
    jira = _jira_with_no_candidates()
    pending = await process_feed("maybe something odd?", "chat", jira, _settings(), audit_store)

    jira.create_issue.return_value = {"key": "AIOPS-102"}
    confirmed = await confirm_pending(
        pending.audit_id, jira, _settings(), audit_store, overrides=ConfirmOverrides(issue_type="Service Request")
    )

    assert confirmed.classification.title == "Original title"  # issue_type isn't a classification field
    create_kwargs = jira.create_issue.await_args.kwargs
    assert create_kwargs["issue_type"] == "Service Request"


@pytest.mark.asyncio
async def test_confirm_pending_applies_reporting_service_key_override(monkeypatch, audit_store):
    _patch_classify(monkeypatch, _classification(confidence=0.2, severity=Severity.LOW))
    jira = _jira_with_no_candidates()
    settings = _settings().model_copy(update={"jira_reporting_service_field_id": "customfield_14503"})
    pending = await process_feed("maybe something odd?", "chat", jira, settings, audit_store)

    jira.create_issue.return_value = {"key": "AIOPS-103"}
    await confirm_pending(
        pending.audit_id, jira, settings, audit_store, overrides=ConfirmOverrides(reporting_service_key="SD-1179")
    )

    create_kwargs = jira.create_issue.await_args.kwargs
    assert create_kwargs["extra_fields"] == {"customfield_14503": [{"key": "SD-1179"}]}


@pytest.mark.asyncio
async def test_confirm_pending_applies_extra_field_values_override(monkeypatch, audit_store):
    _patch_classify(monkeypatch, _classification(confidence=0.2, severity=Severity.LOW))
    jira = _jira_with_no_candidates()
    settings = _settings().model_copy(update={"jira_extra_select_fields": {"customfield_36200": "Subsidiary"}})
    pending = await process_feed("maybe something odd?", "chat", jira, settings, audit_store)

    jira.create_issue.return_value = {"key": "AIOPS-104"}
    await confirm_pending(
        pending.audit_id,
        jira,
        settings,
        audit_store,
        overrides=ConfirmOverrides(extra_field_values={"customfield_36200": "43503"}),
    )

    create_kwargs = jira.create_issue.await_args.kwargs
    assert create_kwargs["extra_fields"] == {"customfield_36200": {"id": "43503"}}


@pytest.mark.asyncio
async def test_confirm_pending_without_overrides_keeps_original_classification(monkeypatch, audit_store):
    _patch_classify(monkeypatch, _classification(confidence=0.2, severity=Severity.LOW, title="Original title"))
    jira = _jira_with_no_candidates()
    pending = await process_feed("maybe something odd?", "chat", jira, _settings(), audit_store)

    jira.create_issue.return_value = {"key": "AIOPS-101"}
    confirmed = await confirm_pending(pending.audit_id, jira, _settings(), audit_store)

    assert confirmed.classification.title == "Original title"
    assert confirmed.classification.severity == Severity.LOW


@pytest.mark.asyncio
async def test_confirm_pending_returns_none_for_unknown_id(audit_store):
    jira = AsyncMock()
    result = await confirm_pending(999, jira, _settings(), audit_store)
    assert result is None


@pytest.mark.asyncio
async def test_confirm_pending_raises_when_not_pending(monkeypatch, audit_store):
    _patch_classify(monkeypatch, _classification(confidence=0.95, severity=Severity.LOW))
    jira = _jira_with_no_candidates()
    jira.create_issue.return_value = {"key": "AIOPS-1"}
    executed = await process_feed("clear incident", "chat", jira, _settings(), audit_store)
    assert executed.action_status == STATUS_EXECUTED

    with pytest.raises(PendingActionError):
        await confirm_pending(executed.audit_id, jira, _settings(), audit_store)


@pytest.mark.asyncio
async def test_cancel_pending_marks_cancelled_without_touching_jira(monkeypatch, audit_store):
    _patch_classify(monkeypatch, _classification(confidence=0.2, severity=Severity.LOW))
    jira = _jira_with_no_candidates()
    pending = await process_feed("maybe something odd?", "chat", jira, _settings(), audit_store)

    cancelled = await cancel_pending(pending.audit_id, audit_store)

    assert cancelled is not None
    assert cancelled.action_status == STATUS_CANCELLED
    jira.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_pending_returns_none_for_unknown_id(audit_store):
    assert await cancel_pending(999, audit_store) is None


@pytest.mark.asyncio
async def test_cancel_pending_raises_when_not_pending(monkeypatch, audit_store):
    _patch_classify(monkeypatch, _classification(intent=Intent.NOISE))
    jira = _jira_with_no_candidates()
    skipped = await process_feed("hi", "chat", jira, _settings(), audit_store)

    with pytest.raises(PendingActionError):
        await cancel_pending(skipped.audit_id, audit_store)
