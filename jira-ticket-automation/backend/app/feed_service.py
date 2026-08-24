from __future__ import annotations

from app.actions import action_type_for, execute_action, is_auto
from app.audit import (
    STATUS_CANCELLED,
    STATUS_CONFIRMED,
    STATUS_EXECUTED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SKIPPED,
    AuditRow,
    AuditStore,
)
from app.classifier import FeedClassification, classify
from app.config import Settings
from app.jira_client import JiraClient
from app.models import ConfirmOverrides, FeedResponse
from app.routing import RoutingDecision, route
from app.tickets import fetch_candidate_tickets


class PendingActionError(ValueError):
    """Raised when confirm/cancel is attempted on a row that isn't pending."""


def _error_summary(steps) -> str | None:
    failures = [f"{s.step}: {s.error}" for s in steps if not s.ok]
    return "; ".join(failures) or None


async def process_feed(
    text: str,
    source: str,
    jira: JiraClient,
    settings: Settings,
    audit_store: AuditStore,
    issue_type: str | None = None,
    reporting_service_key: str | None = None,
    extra_field_values: dict[str, str] | None = None,
) -> FeedResponse:
    candidates = await fetch_candidate_tickets(jira, settings)
    classification = await classify(text, candidates, settings)
    decision = route(classification, settings)
    action_type = action_type_for(decision)
    raw_response_json = classification.model_dump_json()

    common_kwargs = dict(
        input_text=text,
        input_source=source,
        classification=classification,
        raw_response_json=raw_response_json,
        routing_decision=decision,
        threshold_confidence_min=settings.autonomy_auto_confidence_min,
        threshold_severity_max=settings.autonomy_auto_severity_max,
    )

    if decision is RoutingDecision.SKIP_AS_NOISE:
        row = await audit_store.create(action_status=STATUS_SKIPPED, **common_kwargs)
        return FeedResponse(
            audit_id=row.id,
            classification=classification,
            routing_decision=decision.value,
            action_status=STATUS_SKIPPED,
        )

    if is_auto(decision):
        result = await execute_action(
            action_type,
            classification,
            jira,
            settings,
            issue_type=issue_type,
            reporting_service_key=reporting_service_key,
            extra_field_values=extra_field_values,
        )
        status = STATUS_EXECUTED if result.all_ok else STATUS_FAILED
        row = await audit_store.create(
            action_status=status,
            jira_action_type=action_type.value,
            jira_issue_key=result.jira_issue_key,
            jira_error=_error_summary(result.steps),
            **common_kwargs,
        )
        return FeedResponse(
            audit_id=row.id,
            classification=classification,
            routing_decision=decision.value,
            action_status=status,
            jira_issue_key=result.jira_issue_key,
        )

    # propose_* -- nothing touches Jira until the human confirms.
    row = await audit_store.create(
        action_status=STATUS_PENDING, jira_action_type=action_type.value, **common_kwargs
    )
    return FeedResponse(
        audit_id=row.id,
        classification=classification,
        routing_decision=decision.value,
        action_status=STATUS_PENDING,
    )


async def confirm_pending(
    audit_id: int,
    jira: JiraClient,
    settings: Settings,
    audit_store: AuditStore,
    overrides: ConfirmOverrides | None = None,
) -> FeedResponse | None:
    row = await audit_store.get(audit_id)
    if row is None:
        return None
    if row.action_status != STATUS_PENDING:
        raise PendingActionError(f"audit entry {audit_id} is not pending (status={row.action_status})")

    classification = FeedClassification.model_validate_json(row.llm_raw_response_json)
    issue_type_override: str | None = None
    reporting_service_key_override: str | None = None
    extra_field_values_override: dict[str, str] | None = None
    if overrides is not None:
        issue_type_override = overrides.issue_type
        reporting_service_key_override = overrides.reporting_service_key
        extra_field_values_override = overrides.extra_field_values or None
        update = overrides.model_dump(
            exclude_none=True, exclude={"issue_type", "reporting_service_key", "extra_field_values"}
        )
        if update:
            classification = classification.model_copy(update=update)
    decision = RoutingDecision(row.routing_decision)
    action_type = action_type_for(decision)

    result = await execute_action(
        action_type,
        classification,
        jira,
        settings,
        issue_type=issue_type_override,
        reporting_service_key=reporting_service_key_override,
        extra_field_values=extra_field_values_override,
    )
    status = STATUS_CONFIRMED if result.all_ok else STATUS_FAILED
    updated = await audit_store.update_action_outcome(
        audit_id,
        action_status=status,
        jira_action_type=action_type.value,
        jira_issue_key=result.jira_issue_key,
        jira_error=_error_summary(result.steps),
    )
    assert updated is not None
    return FeedResponse(
        audit_id=audit_id,
        classification=classification,
        routing_decision=decision.value,
        action_status=status,
        jira_issue_key=result.jira_issue_key,
    )


async def cancel_pending(audit_id: int, audit_store: AuditStore) -> AuditRow | None:
    row = await audit_store.get(audit_id)
    if row is None:
        return None
    if row.action_status != STATUS_PENDING:
        raise PendingActionError(f"audit entry {audit_id} is not pending (status={row.action_status})")
    return await audit_store.update_action_outcome(audit_id, action_status=STATUS_CANCELLED)
