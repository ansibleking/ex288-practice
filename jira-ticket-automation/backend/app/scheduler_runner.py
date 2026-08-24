from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from app.actions import ActionType, execute_action
from app.audit import STATUS_EXECUTED, STATUS_FAILED, AuditStore
from app.classifier import FeedClassification, Intent, Severity, classify
from app.config import Settings
from app.jira_client import JiraClient
from app.routing import RoutingDecision
from app.schedule_store import ScheduledItem, ScheduleStore
from app.tickets import fetch_candidate_tickets

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _steps_error_summary(steps) -> str:
    return "; ".join(f"{s.step}: {s.error}" for s in steps if not s.ok and s.error) or "unknown error"


async def _create_scheduled_item(
    item: ScheduledItem,
    schedule_store: ScheduleStore,
    jira: JiraClient,
    settings: Settings,
    audit_store: AuditStore,
) -> None:
    try:
        candidates = await fetch_candidate_tickets(jira, settings)
        classification = await classify(item.text, candidates, settings)
    except Exception as exc:  # noqa: BLE001 -- classifier/network failures must not kill the loop
        logger.warning("scheduled item %s: classification failed: %s", item.id, exc)
        await schedule_store.mark_create_failed(item.id, error=f"classification failed: {exc}")
        return

    extra_field_values = json.loads(item.extra_field_values_json) if item.extra_field_values_json else None
    result = await execute_action(
        ActionType.CREATE,
        classification,
        jira,
        settings,
        issue_type=item.issue_type,
        reporting_service_key=item.reporting_service_key,
        extra_field_values=extra_field_values,
    )
    status = STATUS_EXECUTED if result.all_ok else STATUS_FAILED
    error = None if result.all_ok else _steps_error_summary(result.steps)

    audit_row = await audit_store.create(
        input_text=item.text,
        input_source="scheduler",
        classification=classification,
        raw_response_json=classification.model_dump_json(),
        routing_decision=RoutingDecision.AUTO_CREATE,
        threshold_confidence_min=settings.autonomy_auto_confidence_min,
        threshold_severity_max=settings.autonomy_auto_severity_max,
        action_status=status,
        jira_action_type=ActionType.CREATE.value,
        jira_issue_key=result.jira_issue_key,
        jira_error=error,
    )

    if result.all_ok and result.jira_issue_key:
        await schedule_store.mark_created(
            item.id,
            jira_issue_key=result.jira_issue_key,
            classification_json=classification.model_dump_json(),
            create_audit_id=audit_row.id,
        )
    else:
        await schedule_store.mark_create_failed(
            item.id, error=error or "ticket creation failed", create_audit_id=audit_row.id
        )


async def _resolve_scheduled_item(
    item: ScheduledItem,
    schedule_store: ScheduleStore,
    jira: JiraClient,
    settings: Settings,
    audit_store: AuditStore,
) -> None:
    assert item.jira_issue_key is not None, "router guarantees jira_issue_key before a resolve is due"

    base = FeedClassification.model_validate_json(item.classification_json) if item.classification_json else None
    classification = FeedClassification(
        intent=Intent.RESOLVED,
        confidence=1.0,
        severity=base.severity if base else Severity.LOW,
        matched_ticket_key=item.jira_issue_key,
        title=base.title if base else item.text,
        summary=base.summary if base else item.text,
        reasoning="Scheduled window ended; automatically resolved by the scheduler.",
        resolution_comment=f"Scheduled window ended at {item.end_at} — automatically resolved.",
    )

    result = await execute_action(ActionType.RESOLVE, classification, jira, settings)
    status = STATUS_EXECUTED if result.all_ok else STATUS_FAILED
    error = None if result.all_ok else _steps_error_summary(result.steps)

    audit_row = await audit_store.create(
        input_text=f"[scheduled resolve] {item.text}",
        input_source="scheduler",
        classification=classification,
        raw_response_json=classification.model_dump_json(),
        routing_decision=RoutingDecision.AUTO_RESOLVE,
        threshold_confidence_min=settings.autonomy_auto_confidence_min,
        threshold_severity_max=settings.autonomy_auto_severity_max,
        action_status=status,
        jira_action_type=ActionType.RESOLVE.value,
        jira_issue_key=item.jira_issue_key,
        jira_error=error,
    )

    if result.all_ok:
        await schedule_store.mark_resolved(item.id, resolve_audit_id=audit_row.id)
    else:
        await schedule_store.mark_resolve_failed(item.id, error=error or "resolve failed", resolve_audit_id=audit_row.id)


async def process_due_items(
    schedule_store: ScheduleStore, jira: JiraClient, settings: Settings, audit_store: AuditStore
) -> None:
    """One polling pass: fire any scheduled create/resolve that's now due.

    Split into two passes (creates, then resolves) each polling interval so
    an item scheduled with start_at == end_at (a zero-length window, unusual
    but not invalid) still gets created before it's considered for resolve.
    """
    now = _now_iso()
    for item in await schedule_store.list_due_for_create(now):
        await _create_scheduled_item(item, schedule_store, jira, settings, audit_store)
    for item in await schedule_store.list_due_for_resolve(now):
        await _resolve_scheduled_item(item, schedule_store, jira, settings, audit_store)


async def scheduler_loop(
    schedule_store: ScheduleStore,
    jira: JiraClient,
    settings: Settings,
    audit_store: AuditStore,
    poll_seconds: float,
) -> None:
    """Runs forever (as a background asyncio task) until cancelled."""
    while True:
        try:
            await process_due_items(schedule_store, jira, settings, audit_store)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- one bad iteration must not kill the loop
            logger.exception("scheduler loop iteration failed")
        await asyncio.sleep(poll_seconds)
