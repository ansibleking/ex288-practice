import json

import pytest

from app.audit import AuditStore, STATUS_CONFIRMED, STATUS_EXECUTED, STATUS_PENDING
from app.classifier import FeedClassification, Intent, Severity
from app.routing import RoutingDecision


@pytest.fixture
def store(tmp_path):
    return AuditStore(str(tmp_path / "audit.db"))


def _classification(**overrides) -> FeedClassification:
    defaults = dict(
        intent=Intent.NEW_ISSUE,
        confidence=0.9,
        severity=Severity.LOW,
        matched_ticket_key=None,
        title="DB pool exhaustion",
        summary="Seeing intermittent 503s",
        reasoning="clear signal",
    )
    defaults.update(overrides)
    return FeedClassification(**defaults)


@pytest.mark.asyncio
async def test_create_persists_all_fields(store: AuditStore):
    classification = _classification()
    row = await store.create(
        input_text="payments-svc is throwing 503s",
        input_source="chat",
        classification=classification,
        raw_response_json=json.dumps({"intent": "new_issue"}),
        routing_decision=RoutingDecision.AUTO_CREATE,
        threshold_confidence_min=0.85,
        threshold_severity_max="medium",
        action_status=STATUS_EXECUTED,
        jira_action_type="create",
        jira_issue_key="AIOPS-42",
    )

    assert row.id > 0
    assert row.input_text == "payments-svc is throwing 503s"
    assert row.llm_intent == "new_issue"
    assert row.llm_confidence == 0.9
    assert row.routing_decision == "auto_create"
    assert row.action_status == STATUS_EXECUTED
    assert row.jira_issue_key == "AIOPS-42"
    assert row.created_at  # non-empty ISO timestamp


@pytest.mark.asyncio
async def test_get_returns_none_for_missing_id(store: AuditStore):
    assert await store.get(999) is None


@pytest.mark.asyncio
async def test_get_returns_created_row(store: AuditStore):
    created = await store.create(
        input_text="text",
        input_source="paste",
        classification=_classification(),
        raw_response_json="{}",
        routing_decision=RoutingDecision.PROPOSE_CREATE,
        threshold_confidence_min=0.85,
        threshold_severity_max="medium",
        action_status=STATUS_PENDING,
    )

    fetched = await store.get(created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.action_status == STATUS_PENDING


@pytest.mark.asyncio
async def test_update_action_outcome_moves_pending_to_confirmed_in_place(store: AuditStore):
    created = await store.create(
        input_text="text",
        input_source="paste",
        classification=_classification(),
        raw_response_json="{}",
        routing_decision=RoutingDecision.PROPOSE_CREATE,
        threshold_confidence_min=0.85,
        threshold_severity_max="medium",
        action_status=STATUS_PENDING,
    )

    updated = await store.update_action_outcome(
        created.id,
        action_status=STATUS_CONFIRMED,
        jira_action_type="create",
        jira_issue_key="AIOPS-7",
    )

    assert updated is not None
    assert updated.id == created.id  # same row, not a new one
    assert updated.action_status == STATUS_CONFIRMED
    assert updated.jira_issue_key == "AIOPS-7"

    all_rows = await store.list(limit=10)
    assert len(all_rows) == 1  # confirmed in place, no duplicate row


@pytest.mark.asyncio
async def test_update_action_outcome_returns_none_for_missing_id(store: AuditStore):
    result = await store.update_action_outcome(999, action_status=STATUS_CONFIRMED)
    assert result is None


@pytest.mark.asyncio
async def test_list_orders_newest_first(store: AuditStore):
    for i in range(3):
        await store.create(
            input_text=f"text {i}",
            input_source="chat",
            classification=_classification(),
            raw_response_json="{}",
            routing_decision=RoutingDecision.AUTO_CREATE,
            threshold_confidence_min=0.85,
            threshold_severity_max="medium",
            action_status=STATUS_EXECUTED,
        )

    rows = await store.list(limit=10)

    assert [r.input_text for r in rows] == ["text 2", "text 1", "text 0"]


@pytest.mark.asyncio
async def test_list_filters_by_status(store: AuditStore):
    await store.create(
        input_text="pending one",
        input_source="chat",
        classification=_classification(),
        raw_response_json="{}",
        routing_decision=RoutingDecision.PROPOSE_CREATE,
        threshold_confidence_min=0.85,
        threshold_severity_max="medium",
        action_status=STATUS_PENDING,
    )
    await store.create(
        input_text="executed one",
        input_source="chat",
        classification=_classification(),
        raw_response_json="{}",
        routing_decision=RoutingDecision.AUTO_CREATE,
        threshold_confidence_min=0.85,
        threshold_severity_max="medium",
        action_status=STATUS_EXECUTED,
    )

    pending_only = await store.list(limit=10, status=STATUS_PENDING)

    assert len(pending_only) == 1
    assert pending_only[0].input_text == "pending one"


@pytest.mark.asyncio
async def test_list_pending_convenience_method(store: AuditStore):
    await store.create(
        input_text="pending one",
        input_source="chat",
        classification=_classification(),
        raw_response_json="{}",
        routing_decision=RoutingDecision.PROPOSE_CREATE,
        threshold_confidence_min=0.85,
        threshold_severity_max="medium",
        action_status=STATUS_PENDING,
    )

    pending = await store.list_pending()

    assert len(pending) == 1
    assert pending[0].action_status == STATUS_PENDING


@pytest.mark.asyncio
async def test_store_creates_parent_directory(tmp_path):
    nested_path = tmp_path / "nested" / "dir" / "audit.db"
    store = AuditStore(str(nested_path))

    row = await store.create(
        input_text="text",
        input_source="chat",
        classification=_classification(),
        raw_response_json="{}",
        routing_decision=RoutingDecision.AUTO_CREATE,
        threshold_confidence_min=0.85,
        threshold_severity_max="medium",
        action_status=STATUS_EXECUTED,
    )

    assert nested_path.exists()
    assert row.id == 1
