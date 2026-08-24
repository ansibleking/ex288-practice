from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel

from app.classifier import CandidateTicket
from app.config import Settings
from app.jira_client import JiraClient, JiraClientError

MANAGED_TICKETS_FIELDS = ["summary", "description", "status"]
MY_TICKETS_FIELDS = ["summary", "status", "priority", "issuetype", "assignee", "updated"]
DETAIL_FIELDS = [
    "summary",
    "description",
    "status",
    "priority",
    "issuetype",
    "assignee",
    "reporter",
    "created",
    "updated",
    "comment",
    "attachment",
]
DESCRIPTION_EXCERPT_LENGTH = 300
FALLBACK_ISSUE_TYPES = ["Service Request", "Task", "Bug", "Incident"]


def managed_tickets_jql(settings: Settings) -> str:
    return f'labels = "{settings.jira_managed_label}" AND statusCategory != Done'


async def fetch_candidate_tickets(jira: JiraClient, settings: Settings) -> list[CandidateTicket]:
    result = await jira.search_issues(
        managed_tickets_jql(settings), fields=MANAGED_TICKETS_FIELDS, max_results=50
    )
    candidates: list[CandidateTicket] = []
    for issue in result.get("issues", []):
        fields = issue["fields"]
        description = fields.get("description") or ""
        candidates.append(
            CandidateTicket(
                key=issue["key"],
                summary=fields.get("summary", ""),
                description_excerpt=description[:DESCRIPTION_EXCERPT_LENGTH],
            )
        )
    return candidates


class JiraTicketSummary(BaseModel):
    key: str
    summary: str
    status: str
    priority: str | None
    issue_type: str
    assignee: str | None
    updated: str
    url: str


def my_tickets_jql(start_date: str | None = None, end_date: str | None = None) -> str:
    clauses = ["(assignee = currentUser() OR reporter = currentUser())"]
    if start_date:
        clauses.append(f'updated >= "{start_date}"')
    if end_date:
        # JQL date literals are midnight-anchored, so a bare "<= end_date"
        # would exclude nearly all of that day -- compare against the start
        # of the following day instead to make the end date inclusive.
        exclusive_end = date.fromisoformat(end_date) + timedelta(days=1)
        clauses.append(f'updated < "{exclusive_end.isoformat()}"')
    return " AND ".join(clauses) + " ORDER BY updated DESC"


class PaginatedTickets(BaseModel):
    items: list[JiraTicketSummary]
    total: int


async def fetch_my_tickets(
    jira: JiraClient,
    settings: Settings,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> PaginatedTickets:
    result = await jira.search_issues(
        my_tickets_jql(start_date, end_date), fields=MY_TICKETS_FIELDS, start_at=offset, max_results=limit
    )
    base_url = settings.jira_base_url.rstrip("/")
    tickets: list[JiraTicketSummary] = []
    for issue in result.get("issues", []):
        fields = issue["fields"]
        priority = fields.get("priority")
        issue_type = fields.get("issuetype") or {}
        status = fields.get("status") or {}
        assignee = fields.get("assignee")
        tickets.append(
            JiraTicketSummary(
                key=issue["key"],
                summary=fields.get("summary", ""),
                status=status.get("name", ""),
                priority=priority.get("name") if priority else None,
                issue_type=issue_type.get("name", ""),
                assignee=assignee.get("displayName") if assignee else None,
                updated=fields.get("updated", ""),
                url=f"{base_url}/browse/{issue['key']}",
            )
        )
    return PaginatedTickets(items=tickets, total=result.get("total", len(tickets)))


class JiraComment(BaseModel):
    author: str
    body: str
    created: str


class JiraAttachment(BaseModel):
    id: str
    filename: str
    size: int
    mime_type: str
    author: str
    created: str
    url: str


class JiraTicketDetail(BaseModel):
    key: str
    summary: str
    description: str
    status: str
    priority: str | None
    issue_type: str
    assignee: str | None
    reporter: str | None
    created: str
    updated: str
    url: str
    comments: list[JiraComment]
    attachments: list[JiraAttachment]


def _extract_attachments(fields: dict[str, Any]) -> list[JiraAttachment]:
    return [
        JiraAttachment(
            id=a["id"],
            filename=a.get("filename", "attachment"),
            size=a.get("size", 0),
            mime_type=a.get("mimeType", "application/octet-stream"),
            author=(a.get("author") or {}).get("displayName", "Unknown"),
            created=a.get("created", ""),
            url=a.get("content", ""),
        )
        for a in fields.get("attachment") or []
    ]


async def fetch_ticket_detail(jira: JiraClient, settings: Settings, key: str) -> JiraTicketDetail:
    issue = await jira.get_issue(key, fields=DETAIL_FIELDS)
    fields = issue["fields"]
    priority = fields.get("priority")
    issue_type = fields.get("issuetype") or {}
    status = fields.get("status") or {}
    assignee = fields.get("assignee")
    reporter = fields.get("reporter")
    comments = [
        JiraComment(
            author=(c.get("author") or {}).get("displayName", "Unknown"),
            body=c.get("body", ""),
            created=c.get("created", ""),
        )
        for c in (fields.get("comment") or {}).get("comments", [])
    ]
    attachments = _extract_attachments(fields)
    base_url = settings.jira_base_url.rstrip("/")
    return JiraTicketDetail(
        key=issue["key"],
        summary=fields.get("summary", ""),
        description=fields.get("description") or "",
        status=status.get("name", ""),
        priority=priority.get("name") if priority else None,
        issue_type=issue_type.get("name", ""),
        assignee=assignee.get("displayName") if assignee else None,
        reporter=reporter.get("displayName") if reporter else None,
        created=fields.get("created", ""),
        updated=fields.get("updated", ""),
        url=f"{base_url}/browse/{issue['key']}",
        comments=comments,
        attachments=attachments,
    )


async def fetch_issue_types(jira: JiraClient, settings: Settings) -> list[str]:
    # createmeta isn't available/enabled on every Jira DC instance or for
    # every project -- fall back to a static list rather than blocking
    # ticket creation on a metadata lookup that isn't load-bearing.
    try:
        types = await jira.get_create_issue_types(settings.jira_project_key)
    except JiraClientError:
        return FALLBACK_ISSUE_TYPES
    return types or FALLBACK_ISSUE_TYPES


class ReportingServiceOption(BaseModel):
    key: str
    label: str


async def fetch_reporting_services(
    jira: JiraClient, settings: Settings, query: str | None = None
) -> list[ReportingServiceOption]:
    entries = await jira.search_insight_objects(
        object_type=settings.jira_reporting_service_object_type,
        object_schema_id=settings.jira_insight_object_schema_id,
        query=query,
    )
    return [
        ReportingServiceOption(key=e["objectKey"], label=e["label"])
        for e in entries
        if e.get("objectKey") and e.get("label")
    ]


class SelectOption(BaseModel):
    id: str
    value: str


class ExtraSelectField(BaseModel):
    field_id: str
    label: str
    options: list[SelectOption]


async def fetch_extra_select_fields(jira: JiraClient, settings: Settings) -> list[ExtraSelectField]:
    """Discover option lists for extra required select fields.

    Reads them from a single editmeta call against a known-good reference
    issue (settings.jira_field_metadata_reference_issue) rather than
    createmeta, which returned 404 on this Jira DC instance. Disabled
    options are dropped since Jira rejects them the same as an invalid one.
    """
    if not settings.jira_extra_select_fields or not settings.jira_field_metadata_reference_issue:
        return []
    editmeta_fields = await jira.get_editmeta(settings.jira_field_metadata_reference_issue)
    result: list[ExtraSelectField] = []
    for field_id, label in settings.jira_extra_select_fields.items():
        meta = editmeta_fields.get(field_id)
        if not meta:
            continue
        options = [
            SelectOption(id=o["id"], value=o["value"])
            for o in meta.get("allowedValues", [])
            if not o.get("disabled") and o.get("id") and o.get("value")
        ]
        result.append(ExtraSelectField(field_id=field_id, label=label, options=options))
    return result


# Tickets pending the current user's decision are detected generically by
# whether Jira currently offers them a transition that reads like an
# approval action -- not by hardcoding status names, since different issue
# types/workflows on this instance use different approval status labels
# ("Pending Line Manager", "IMD Domain Approval", "Awaiting SM Approval", ...).
APPROVAL_TRANSITION_PATTERN = re.compile(r"approve|reject|decline", re.IGNORECASE)
APPROVAL_LIST_FIELDS = ["summary", "status", "issuetype", "reporter", "updated"]


def approvals_jql(settings: Settings) -> str:
    # Being the assignee isn't the only way Jira grants Approve/Reject here
    # -- some workflows (e.g. IT Change) grant it via a named
    # user/group-picker field even when the ticket is unassigned. OR those
    # in as extra candidate clauses; the get_transitions check below still
    # does the real filtering to whatever's actually actionable right now.
    clauses = ["assignee = currentUser()"]
    for field_id in settings.jira_approver_fields:
        clauses.append(f"cf[{field_id.removeprefix('customfield_')}] = currentUser()")
    scope = " OR ".join(clauses)
    return f"({scope}) AND statusCategory != Done ORDER BY updated DESC"


class TransitionFieldSpec(BaseModel):
    field_id: str
    label: str
    type: str  # "string" | "number"


# A transition screen can require ordinary fields beyond the built-in
# comment (e.g. a numeric "Estimated Hrs." field on some approval
# transitions) -- these only surface as a 400 on the transition attempt
# itself if not asked for upfront, same gap as the comment requirement.
# Only simple text/number fields are surfaced as inputs; anything else
# (select, user picker, ...) isn't rendered here and will still fail with
# Jira's own clear error if it turns out to be required, the same way
# comment/estimated-hours failures did before being handled specifically.
_SUPPORTED_TRANSITION_FIELD_TYPES = {"string", "number"}


def _transition_extra_fields(raw_fields: dict[str, Any]) -> list[TransitionFieldSpec]:
    specs = []
    for field_id, meta in raw_fields.items():
        schema_type = (meta.get("schema") or {}).get("type")
        if schema_type not in _SUPPORTED_TRANSITION_FIELD_TYPES:
            continue
        specs.append(TransitionFieldSpec(field_id=field_id, label=meta.get("name", field_id), type=schema_type))
    return specs


class TransitionOption(BaseModel):
    id: str
    name: str
    to_status: str
    extra_fields: list[TransitionFieldSpec] = []


class ApprovalTicket(BaseModel):
    key: str
    summary: str
    status: str
    issue_type: str
    reporter: str | None
    updated: str
    url: str
    transitions: list[TransitionOption]


async def fetch_approval_tickets(jira: JiraClient, settings: Settings) -> list[ApprovalTicket]:
    result = await jira.search_issues(approvals_jql(settings), fields=APPROVAL_LIST_FIELDS, max_results=100)
    issues = result.get("issues", [])
    transitions_by_key = await asyncio.gather(*(jira.get_transitions(issue["key"]) for issue in issues))

    base_url = settings.jira_base_url.rstrip("/")
    tickets: list[ApprovalTicket] = []
    for issue, transitions in zip(issues, transitions_by_key):
        approval_transitions = [
            TransitionOption(
                id=t["id"],
                name=t["name"],
                to_status=t["to"]["name"],
                extra_fields=_transition_extra_fields(t.get("fields") or {}),
            )
            for t in transitions
            if APPROVAL_TRANSITION_PATTERN.search(t["name"])
        ]
        if not approval_transitions:
            continue
        fields = issue["fields"]
        issue_type = fields.get("issuetype") or {}
        status = fields.get("status") or {}
        reporter = fields.get("reporter")
        tickets.append(
            ApprovalTicket(
                key=issue["key"],
                summary=fields.get("summary", ""),
                status=status.get("name", ""),
                issue_type=issue_type.get("name", ""),
                reporter=reporter.get("displayName") if reporter else None,
                updated=fields.get("updated", ""),
                url=f"{base_url}/browse/{issue['key']}",
                transitions=approval_transitions,
            )
        )
    return tickets


# Jira reuses customfields across unrelated issue types on this instance, so
# a raw field dump is mostly noise (SLA objects, auto-generated KB-link
# search widgets, unfilled wiki-table templates). These two filters keep
# only fields that resolve to real, human-readable content, so the ticket
# fed to the LLM (and shown in the UI) looks like what a person reviewing
# the ticket in Jira would actually see -- not the full ~700-field dump.
_JUNK_VALUE_MARKERS = ("<a href", "<style", "<table", "<div", "<script")


def _flatten_field_value(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        if any(marker in value for marker in _JUNK_VALUE_MARKERS):
            return None
        return value
    if isinstance(value, dict):
        if "value" in value:
            return _flatten_field_value(value["value"])
        if "displayName" in value:
            return _flatten_field_value(value["displayName"])
        return None
    if isinstance(value, list):
        parts = [p for p in (_flatten_field_value(v) for v in value) if p]
        return ", ".join(parts) if parts else None
    return None


def _is_substantive(text: str) -> bool:
    # Wiki-markup table fields (e.g. "||Col||\r\n|| || ||") flatten to a
    # non-empty string even when every cell is blank -- strip the table
    # syntax and whitespace and require real content to remain.
    return len(re.sub(r"[|\s]", "", text)) >= 8


class FieldEntry(BaseModel):
    label: str
    value: str


class TicketApprovalDetail(BaseModel):
    key: str
    summary: str
    description: str
    status: str
    issue_type: str
    assignee: str | None
    reporter: str | None
    created: str
    updated: str
    url: str
    fields: list[FieldEntry]
    transitions: list[TransitionOption]
    attachments: list[JiraAttachment]


async def fetch_approval_detail(jira: JiraClient, settings: Settings, key: str) -> TicketApprovalDetail:
    issue = await jira.get_issue(key, fields=["*all"])
    raw_fields = issue["fields"]
    field_defs, transitions_raw = await asyncio.gather(jira.get_fields(), jira.get_transitions(key))
    label_by_id = {f["id"]: f["name"] for f in field_defs}

    entries: list[FieldEntry] = []
    for field_id, value in raw_fields.items():
        if not field_id.startswith("customfield_"):
            continue
        text = _flatten_field_value(value)
        if not text or not _is_substantive(text):
            continue
        entries.append(FieldEntry(label=label_by_id.get(field_id, field_id), value=text))

    transitions = [
        TransitionOption(
            id=t["id"],
            name=t["name"],
            to_status=t["to"]["name"],
            extra_fields=_transition_extra_fields(t.get("fields") or {}),
        )
        for t in transitions_raw
    ]

    issue_type = raw_fields.get("issuetype") or {}
    status = raw_fields.get("status") or {}
    assignee = raw_fields.get("assignee")
    reporter = raw_fields.get("reporter")
    base_url = settings.jira_base_url.rstrip("/")
    return TicketApprovalDetail(
        key=issue["key"],
        summary=raw_fields.get("summary", ""),
        description=raw_fields.get("description") or "",
        status=status.get("name", ""),
        issue_type=issue_type.get("name", ""),
        assignee=assignee.get("displayName") if assignee else None,
        reporter=reporter.get("displayName") if reporter else None,
        created=raw_fields.get("created", ""),
        updated=raw_fields.get("updated", ""),
        url=f"{base_url}/browse/{issue['key']}",
        fields=entries,
        transitions=transitions,
        attachments=_extract_attachments(raw_fields),
    )
