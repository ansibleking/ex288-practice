from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.audit import AuditRow, AuditStore
from app.deps import get_audit_store

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditRow])
async def list_audit(
    limit: int = Query(50, le=200),
    offset: int = 0,
    status: str | None = None,
    audit_store: AuditStore = Depends(get_audit_store),
) -> list[AuditRow]:
    return await audit_store.list(limit=limit, offset=offset, status=status)


@router.get("/{audit_id}", response_model=AuditRow)
async def get_audit(audit_id: int, audit_store: AuditStore = Depends(get_audit_store)) -> AuditRow:
    row = await audit_store.get(audit_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No audit entry {audit_id}")
    return row
