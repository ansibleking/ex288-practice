from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile

from app.classifier import CandidateTicket
from app.config import Settings, get_settings
from app.deps import get_jira_client
from app.jira_client import JiraClient, JiraClientError
from app.tickets import (
    ExtraSelectField,
    JiraTicketDetail,
    PaginatedTickets,
    ReportingServiceOption,
    fetch_candidate_tickets,
    fetch_extra_select_fields,
    fetch_issue_types,
    fetch_my_tickets,
    fetch_reporting_services,
    fetch_ticket_detail,
)

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

# Static-path routes are declared before the /{key} catch-all below so
# "managed", "mine", "issue-types", "reporting-services", and
# "extra-select-fields" are never matched as a ticket key.


@router.get("/managed", response_model=list[CandidateTicket])
async def list_managed_tickets(
    jira: JiraClient = Depends(get_jira_client),
    settings: Settings = Depends(get_settings),
) -> list[CandidateTicket]:
    try:
        return await fetch_candidate_tickets(jira, settings)
    except JiraClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/mine", response_model=PaginatedTickets)
async def list_my_tickets(
    start_date: str | None = Query(default=None, description="YYYY-MM-DD, inclusive"),
    end_date: str | None = Query(default=None, description="YYYY-MM-DD, inclusive"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    jira: JiraClient = Depends(get_jira_client),
    settings: Settings = Depends(get_settings),
) -> PaginatedTickets:
    try:
        return await fetch_my_tickets(
            jira, settings, start_date=start_date, end_date=end_date, limit=limit, offset=offset
        )
    except JiraClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/issue-types", response_model=list[str])
async def list_issue_types(
    jira: JiraClient = Depends(get_jira_client),
    settings: Settings = Depends(get_settings),
) -> list[str]:
    try:
        return await fetch_issue_types(jira, settings)
    except JiraClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/reporting-services", response_model=list[ReportingServiceOption])
async def list_reporting_services(
    q: str | None = Query(default=None, description="Optional name filter"),
    jira: JiraClient = Depends(get_jira_client),
    settings: Settings = Depends(get_settings),
) -> list[ReportingServiceOption]:
    if not settings.reporting_service_configured:
        return []
    try:
        return await fetch_reporting_services(jira, settings, query=q)
    except JiraClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/extra-select-fields", response_model=list[ExtraSelectField])
async def list_extra_select_fields(
    jira: JiraClient = Depends(get_jira_client),
    settings: Settings = Depends(get_settings),
) -> list[ExtraSelectField]:
    try:
        return await fetch_extra_select_fields(jira, settings)
    except JiraClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{key}", response_model=JiraTicketDetail)
async def get_ticket_detail(
    key: str,
    jira: JiraClient = Depends(get_jira_client),
    settings: Settings = Depends(get_settings),
) -> JiraTicketDetail:
    try:
        return await fetch_ticket_detail(jira, settings, key)
    except JiraClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{key}/attachments", response_model=JiraTicketDetail)
async def upload_attachment(
    key: str,
    file: UploadFile,
    jira: JiraClient = Depends(get_jira_client),
    settings: Settings = Depends(get_settings),
) -> JiraTicketDetail:
    content = await file.read()
    try:
        await jira.add_attachment(
            key,
            filename=file.filename or "attachment",
            content=content,
            content_type=file.content_type or "application/octet-stream",
        )
        return await fetch_ticket_detail(jira, settings, key)
    except JiraClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
