from unittest.mock import AsyncMock

import pytest

from app.audit import STATUS_EXECUTED, STATUS_FAILED, AuditStore
from app.classifier import FeedClassification, Intent, Severity
from app.config import Settings
from app.jira_client import JiraClientError
from app.schedule_store import STATUS_CREATE_FAILED, STATUS_CREATED, STATUS_RESOLVE_FAILED, STATUS_RESOLVED, ScheduleStore
from app.scheduler_runner import process_due_items


def _settings() -> Settings:
    return Settings(
        jira_base_url="https://jira.example.internal",
        jira_pat="test-token",
        jira_project_key="AIOPS",
        jira_managed_label="aiops-managed",
        jira_resolved_transition_name="Done",
        # No anthropic_api_key: resolve tests here exercise the deterministic
        # path. classify() is monkeypatched in this file regardless.
    )


def _classification(**overrides) -> FeedClassification:
    defaults = dict(
        intent=Intent.NEW_ISSUE,
        confidence=0.9,
        severity=Severity.LOW,
        matched_ticket_key=None,
        title="Scheduled maintenance window",
        summary="DB maintenance window",
        reasoning="scheduled",
    )
    defaults.update(overrides)
    return FeedClassification(**defaults)


@pytest.fixture
def schedule_store(tmp_path) -> ScheduleStore:
    return ScheduleStore(str(tmp_path / "schedule.db"))


@pytest.fixture
def audit_store(tmp_path) -> AuditStore:
    return AuditStore(str(tmp_path / "audit.db"))


def _jira_with_no_candidates() -> AsyncMock:
    jira = AsyncMock()
    jira.search_issues.return_value = {"issues": []}
    jira.get_issue.return_value = {"fields": {"status": {"name": "Open", "statusCategory": {"name": "To Do"}}}}
    return jira


def _transition(id_: str, name: str, to_name: str, to_category: str) -> dict:
    return {"id": id_, "name": name, "to": {"name": to_name, "statusCategory": {"name": to_category}}}


def _patch_classify(monkeypatch, classification: FeedClassification):
    async def fake_classify(text, candidates, settings, llm_client=None):
        return classification

    monkeypatch.setattr("app.scheduler_runner.classify", fake_classify)


@pytest.mark.asyncio
async def test_process_due_items_creates_ticket_for_due_pending_item(monkeypatch, schedule_store, audit_store):
    _patch_classify(monkeypatch, _classification())
    jira = _jira_with_no_candidates()
    jira.create_issue.return_value = {"key": "AIOPS-50"}
    item = await schedule_store.create(
        start_at="2026-08-17T09:00:00+00:00", end_at=None, text="DB maintenance", issue_type="Service Request"
    )

    await process_due_items(schedule_store, jira, _settings(), audit_store)

    updated = await schedule_store.get(item.id)
    assert updated.status == STATUS_CREATED
    assert updated.jira_issue_key == "AIOPS-50"
    assert updated.create_audit_id is not None

    create_kwargs = jira.create_issue.await_args.kwargs
    assert create_kwargs["issue_type"] == "Service Request"

    audit_row = await audit_store.get(updated.create_audit_id)
    assert audit_row.action_status == STATUS_EXECUTED
    assert audit_row.input_source == "scheduler"
    assert audit_row.jira_issue_key == "AIOPS-50"


@pytest.mark.asyncio
async def test_process_due_items_ignores_not_yet_due_items(monkeypatch, schedule_store, audit_store):
    _patch_classify(monkeypatch, _classification())
    jira = _jira_with_no_candidates()
    await schedule_store.create(
        start_at="2099-01-01T00:00:00+00:00", end_at=None, text="future", issue_type="Task"
    )

    await process_due_items(schedule_store, jira, _settings(), audit_store)

    jira.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_due_items_marks_create_failed_on_jira_error(monkeypatch, schedule_store, audit_store):
    _patch_classify(monkeypatch, _classification())
    jira = _jira_with_no_candidates()
    jira.create_issue.side_effect = JiraClientError("Jira 500")
    item = await schedule_store.create(
        start_at="2026-08-17T09:00:00+00:00", end_at=None, text="x", issue_type="Task"
    )

    await process_due_items(schedule_store, jira, _settings(), audit_store)

    updated = await schedule_store.get(item.id)
    assert updated.status == STATUS_CREATE_FAILED
    assert "Jira 500" in updated.error

    audit_row = await audit_store.get(updated.create_audit_id)
    assert audit_row.action_status == STATUS_FAILED


@pytest.mark.asyncio
async def test_process_due_items_marks_create_failed_on_classification_error(monkeypatch, schedule_store, audit_store):
    async def broken_classify(text, candidates, settings, llm_client=None):
        raise ValueError("on-prem endpoint unreachable")

    monkeypatch.setattr("app.scheduler_runner.classify", broken_classify)
    jira = _jira_with_no_candidates()
    item = await schedule_store.create(
        start_at="2026-08-17T09:00:00+00:00", end_at=None, text="x", issue_type="Task"
    )

    await process_due_items(schedule_store, jira, _settings(), audit_store)

    updated = await schedule_store.get(item.id)
    assert updated.status == STATUS_CREATE_FAILED
    assert "on-prem endpoint unreachable" in updated.error
    jira.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_due_items_resolves_created_item_past_end_at(monkeypatch, schedule_store, audit_store):
    _patch_classify(monkeypatch, _classification())
    jira = _jira_with_no_candidates()
    jira.get_transitions.return_value = [_transition("31", "Resolve", "Done", "Done")]
    item = await schedule_store.create(
        start_at="2020-01-01T09:00:00+00:00",
        end_at="2020-01-01T11:00:00+00:00",
        text="DB maintenance",
        issue_type="Task",
    )
    await schedule_store.mark_created(
        item.id,
        jira_issue_key="AIOPS-60",
        classification_json=_classification(title="Maintenance", severity=Severity.LOW).model_dump_json(),
        create_audit_id=1,
    )

    await process_due_items(schedule_store, jira, _settings(), audit_store)

    updated = await schedule_store.get(item.id)
    assert updated.status == STATUS_RESOLVED
    jira.add_comment.assert_awaited_once()
    jira.do_transition.assert_awaited_once_with("AIOPS-60", "31", fields=None)

    audit_row = await audit_store.get(updated.resolve_audit_id)
    assert audit_row.action_status == STATUS_EXECUTED
    assert audit_row.jira_issue_key == "AIOPS-60"
    assert audit_row.llm_intent == "resolved"


@pytest.mark.asyncio
async def test_process_due_items_marks_resolve_failed_on_partial_failure(monkeypatch, schedule_store, audit_store):
    _patch_classify(monkeypatch, _classification())
    jira = _jira_with_no_candidates()
    jira.get_transitions.side_effect = JiraClientError("transitions endpoint down")
    item = await schedule_store.create(
        start_at="2020-01-01T09:00:00+00:00",
        end_at="2020-01-01T11:00:00+00:00",
        text="x",
        issue_type="Task",
    )
    await schedule_store.mark_created(
        item.id,
        jira_issue_key="AIOPS-61",
        classification_json=_classification().model_dump_json(),
        create_audit_id=1,
    )

    await process_due_items(schedule_store, jira, _settings(), audit_store)

    updated = await schedule_store.get(item.id)
    assert updated.status == STATUS_RESOLVE_FAILED
    assert "transitions endpoint down" in updated.error


@pytest.mark.asyncio
async def test_process_due_items_does_not_resolve_items_without_end_at(monkeypatch, schedule_store, audit_store):
    _patch_classify(monkeypatch, _classification())
    jira = _jira_with_no_candidates()
    item = await schedule_store.create(
        start_at="2020-01-01T09:00:00+00:00", end_at=None, text="x", issue_type="Task"
    )
    await schedule_store.mark_created(
        item.id,
        jira_issue_key="AIOPS-62",
        classification_json=_classification().model_dump_json(),
        create_audit_id=1,
    )

    await process_due_items(schedule_store, jira, _settings(), audit_store)

    jira.add_comment.assert_not_awaited()
    updated = await schedule_store.get(item.id)
    assert updated.status == STATUS_CREATED
