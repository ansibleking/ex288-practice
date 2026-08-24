import pytest

from app.schedule_store import (
    STATUS_CANCELLED,
    STATUS_CREATE_FAILED,
    STATUS_CREATED,
    STATUS_PENDING,
    STATUS_RESOLVE_FAILED,
    STATUS_RESOLVED,
    ScheduleStore,
)


@pytest.fixture
def store(tmp_path) -> ScheduleStore:
    return ScheduleStore(str(tmp_path / "schedule.db"))


@pytest.mark.asyncio
async def test_create_defaults_to_pending(store):
    item = await store.create(
        start_at="2026-08-17T09:00:00+00:00", end_at=None, text="DB maintenance", issue_type="Task"
    )
    assert item.status == STATUS_PENDING
    assert item.text == "DB maintenance"
    assert item.jira_issue_key is None


@pytest.mark.asyncio
async def test_list_for_range_filters_by_start_at(store):
    await store.create(start_at="2026-08-17T09:00:00+00:00", end_at=None, text="in range", issue_type="Task")
    await store.create(start_at="2026-08-18T09:00:00+00:00", end_at=None, text="out of range", issue_type="Task")

    items = await store.list_for_range("2026-08-17T00:00:00+00:00", "2026-08-18T00:00:00+00:00")

    assert len(items) == 1
    assert items[0].text == "in range"


@pytest.mark.asyncio
async def test_list_due_for_create_only_returns_pending_items_at_or_before_now(store):
    due = await store.create(start_at="2026-08-17T09:00:00+00:00", end_at=None, text="due", issue_type="Task")
    await store.create(start_at="2026-08-17T23:00:00+00:00", end_at=None, text="not yet", issue_type="Task")

    results = await store.list_due_for_create("2026-08-17T10:00:00+00:00")

    assert [i.id for i in results] == [due.id]


@pytest.mark.asyncio
async def test_list_due_for_create_excludes_already_created_items(store):
    item = await store.create(start_at="2026-08-17T09:00:00+00:00", end_at=None, text="x", issue_type="Task")
    await store.mark_created(item.id, jira_issue_key="AIOPS-1", classification_json="{}", create_audit_id=1)

    results = await store.list_due_for_create("2026-08-17T10:00:00+00:00")

    assert results == []


@pytest.mark.asyncio
async def test_list_due_for_resolve_only_returns_created_items_with_elapsed_end_at(store):
    item = await store.create(
        start_at="2026-08-17T09:00:00+00:00", end_at="2026-08-17T11:00:00+00:00", text="x", issue_type="Task"
    )
    await store.mark_created(item.id, jira_issue_key="AIOPS-1", classification_json="{}", create_audit_id=1)

    not_yet = await store.list_due_for_resolve("2026-08-17T10:00:00+00:00")
    assert not_yet == []

    due = await store.list_due_for_resolve("2026-08-17T12:00:00+00:00")
    assert [i.id for i in due] == [item.id]


@pytest.mark.asyncio
async def test_list_due_for_resolve_excludes_items_without_end_at(store):
    item = await store.create(start_at="2026-08-17T09:00:00+00:00", end_at=None, text="x", issue_type="Task")
    await store.mark_created(item.id, jira_issue_key="AIOPS-1", classification_json="{}", create_audit_id=1)

    results = await store.list_due_for_resolve("2026-08-20T00:00:00+00:00")

    assert results == []


@pytest.mark.asyncio
async def test_mark_created_sets_status_and_fields(store):
    item = await store.create(start_at="2026-08-17T09:00:00+00:00", end_at=None, text="x", issue_type="Task")

    updated = await store.mark_created(
        item.id, jira_issue_key="AIOPS-5", classification_json='{"a": 1}', create_audit_id=7
    )

    assert updated.status == STATUS_CREATED
    assert updated.jira_issue_key == "AIOPS-5"
    assert updated.classification_json == '{"a": 1}'
    assert updated.create_audit_id == 7


@pytest.mark.asyncio
async def test_mark_create_failed_sets_status_and_error(store):
    item = await store.create(start_at="2026-08-17T09:00:00+00:00", end_at=None, text="x", issue_type="Task")

    updated = await store.mark_create_failed(item.id, error="Jira 500")

    assert updated.status == STATUS_CREATE_FAILED
    assert updated.error == "Jira 500"


@pytest.mark.asyncio
async def test_mark_resolved_and_resolve_failed(store):
    item = await store.create(start_at="2026-08-17T09:00:00+00:00", end_at=None, text="x", issue_type="Task")
    await store.mark_created(item.id, jira_issue_key="AIOPS-1", classification_json="{}", create_audit_id=1)

    resolved = await store.mark_resolved(item.id, resolve_audit_id=9)
    assert resolved.status == STATUS_RESOLVED
    assert resolved.resolve_audit_id == 9

    failed = await store.mark_resolve_failed(item.id, error="transition missing", resolve_audit_id=10)
    assert failed.status == STATUS_RESOLVE_FAILED
    assert failed.error == "transition missing"


@pytest.mark.asyncio
async def test_cancel_sets_status(store):
    item = await store.create(start_at="2026-08-17T09:00:00+00:00", end_at=None, text="x", issue_type="Task")

    cancelled = await store.cancel(item.id)

    assert cancelled.status == STATUS_CANCELLED


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown_id(store):
    assert await store.get(999) is None
