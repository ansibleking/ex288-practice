from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_schedule_store
from app.models import ScheduleCreateRequest
from app.schedule_store import STATUS_PENDING, ScheduledItem, ScheduleStore

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


@router.post("", response_model=ScheduledItem)
async def create_scheduled_item(
    body: ScheduleCreateRequest, store: ScheduleStore = Depends(get_schedule_store)
) -> ScheduledItem:
    return await store.create(
        start_at=body.start_at_utc_iso(),
        end_at=body.end_at_utc_iso(),
        text=body.text,
        issue_type=body.issue_type,
        reporting_service_key=body.reporting_service_key,
        extra_field_values_json=json.dumps(body.extra_field_values) if body.extra_field_values else None,
    )


@router.get("", response_model=list[ScheduledItem])
async def list_scheduled_items(
    start: str = Query(..., description="UTC ISO 8601 range start, inclusive"),
    end: str = Query(..., description="UTC ISO 8601 range end, exclusive"),
    store: ScheduleStore = Depends(get_schedule_store),
) -> list[ScheduledItem]:
    return await store.list_for_range(start, end)


@router.post("/{item_id}/cancel", response_model=ScheduledItem)
async def cancel_scheduled_item(
    item_id: int, store: ScheduleStore = Depends(get_schedule_store)
) -> ScheduledItem:
    item = await store.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No scheduled item {item_id}")
    if item.status != STATUS_PENDING:
        raise HTTPException(
            status_code=409, detail=f"scheduled item {item_id} is not pending (status={item.status})"
        )
    updated = await store.cancel(item_id)
    assert updated is not None
    return updated
