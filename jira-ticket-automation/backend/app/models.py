from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, field_validator, model_validator

from app.classifier import FeedClassification, Severity


class FeedRequest(BaseModel):
    text: str
    source: str = "chat"  # chat | paste | file
    issue_type: str | None = None  # overrides settings.jira_issue_type for a new ticket
    reporting_service_key: str | None = None  # Insight object key, when that field is required
    extra_field_values: dict[str, str] = {}  # field_id -> selected option id, for jira_extra_select_fields


class FeedResponse(BaseModel):
    audit_id: int
    classification: FeedClassification
    routing_decision: str
    action_status: str
    jira_issue_key: str | None = None


class ConfirmOverrides(BaseModel):
    """Edits a human makes to the AI's proposal before confirming a pending action.

    title and severity are merged into the stored classification. issue_type
    is handled separately (see feed_service.confirm_pending) since it isn't
    a field the classifier produces -- it's the ticket-type choice for a
    CREATE action. matched_ticket_key isn't editable here, since changing
    which ticket an update/resolve applies to is a different decision than
    editing the proposed wording, not a review-and-fix.
    """

    title: str | None = None
    severity: Severity | None = None
    issue_type: str | None = None
    reporting_service_key: str | None = None
    extra_field_values: dict[str, str] = {}


class ScheduleCreateRequest(BaseModel):
    """A day-planner entry: create a ticket at start_at, optionally auto-resolve at end_at.

    start_at/end_at must be timezone-aware (the frontend sends JS
    Date.toISOString(), which always includes a UTC offset) -- a naive
    datetime here would be ambiguous about whose clock it's measured
    against, so it's rejected rather than guessed at.
    """

    start_at: datetime
    end_at: datetime | None = None
    text: str
    issue_type: str
    reporting_service_key: str | None = None
    extra_field_values: dict[str, str] = {}

    @field_validator("start_at", "end_at")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("must include a timezone offset (e.g. from Date.toISOString())")
        return value

    @model_validator(mode="after")
    def _check_end_after_start(self) -> "ScheduleCreateRequest":
        if self.end_at is not None and self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self

    def start_at_utc_iso(self) -> str:
        return self.start_at.astimezone(timezone.utc).isoformat()

    def end_at_utc_iso(self) -> str | None:
        return self.end_at.astimezone(timezone.utc).isoformat() if self.end_at else None
