from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.audit import AuditRow, AuditStore
from app.config import Settings, get_settings
from app.deps import get_audit_store, get_jira_client
from app.feed_service import PendingActionError, cancel_pending, confirm_pending
from app.jira_client import JiraClient, JiraClientError
from app.models import ConfirmOverrides, FeedResponse

router = APIRouter(prefix="/api/pending", tags=["pending"])


@router.get("", response_model=list[AuditRow])
async def list_pending(audit_store: AuditStore = Depends(get_audit_store)) -> list[AuditRow]:
    return await audit_store.list_pending()


@router.post("/{audit_id}/confirm", response_model=FeedResponse)
async def confirm(
    audit_id: int,
    overrides: ConfirmOverrides | None = None,
    jira: JiraClient = Depends(get_jira_client),
    settings: Settings = Depends(get_settings),
    audit_store: AuditStore = Depends(get_audit_store),
) -> FeedResponse:
    try:
        result = await confirm_pending(audit_id, jira, settings, audit_store, overrides)
    except PendingActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except JiraClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"No audit entry {audit_id}")
    return result


@router.post("/{audit_id}/cancel", response_model=AuditRow)
async def cancel(audit_id: int, audit_store: AuditStore = Depends(get_audit_store)) -> AuditRow:
    try:
        result = await cancel_pending(audit_id, audit_store)
    except PendingActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"No audit entry {audit_id}")
    return result
