from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.approval_summary import ApprovalSummary, summarize_for_approval
from app.config import Settings, get_settings
from app.deps import get_jira_client
from app.jira_client import JiraClient, JiraClientError
from app.tickets import ApprovalTicket, TicketApprovalDetail, fetch_approval_detail, fetch_approval_tickets

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

# Static-path routes are declared before the /{key} catch-all so "" (the
# list route) is never ambiguous with a ticket key.


@router.get("", response_model=list[ApprovalTicket])
async def list_approvals(
    jira: JiraClient = Depends(get_jira_client),
    settings: Settings = Depends(get_settings),
) -> list[ApprovalTicket]:
    try:
        return await fetch_approval_tickets(jira, settings)
    except JiraClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{key}", response_model=TicketApprovalDetail)
async def get_approval_detail(
    key: str,
    jira: JiraClient = Depends(get_jira_client),
    settings: Settings = Depends(get_settings),
) -> TicketApprovalDetail:
    try:
        return await fetch_approval_detail(jira, settings, key)
    except JiraClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{key}/summary", response_model=ApprovalSummary)
async def get_approval_summary(
    key: str,
    jira: JiraClient = Depends(get_jira_client),
    settings: Settings = Depends(get_settings),
) -> ApprovalSummary:
    try:
        detail = await fetch_approval_detail(jira, settings, key)
        return await summarize_for_approval(detail, settings)
    except JiraClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class TransitionRequest(BaseModel):
    transition_id: str
    comment: str | None = None
    extra_field_values: dict[str, Any] | None = None


@router.post("/{key}/transition", response_model=TicketApprovalDetail)
async def transition_approval(
    key: str,
    body: TransitionRequest,
    jira: JiraClient = Depends(get_jira_client),
    settings: Settings = Depends(get_settings),
) -> TicketApprovalDetail:
    try:
        await jira.do_transition(
            key, body.transition_id, comment=body.comment, fields=body.extra_field_values
        )
        return await fetch_approval_detail(jira, settings, key)
    except JiraClientError as exc:
        # Whether a transition's screen requires a comment isn't reliably
        # exposed by this Jira DC instance's transitions/editmeta metadata
        # (confirmed on SDSEC-20643's "Require Clarifications" transition,
        # which reports no required fields at all yet 400s without a
        # comment) -- so this can only be caught reactively, by recognizing
        # Jira's own error text and translating it into something actionable
        # instead of a raw nested-JSON blob.
        if not body.comment and "comment is required" in str(exc).lower():
            raise HTTPException(
                status_code=422,
                detail="This action requires a comment. Add one above and try again.",
            ) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
