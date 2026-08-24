from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile

from app.audit import AuditStore
from app.config import Settings, get_settings
from app.deps import get_audit_store, get_jira_client
from app.feed_service import process_feed
from app.jira_client import JiraClient, JiraClientError
from app.models import FeedRequest, FeedResponse

router = APIRouter(prefix="/api/feed", tags=["feed"])


@router.post("", response_model=FeedResponse)
async def submit_feed(
    body: FeedRequest,
    jira: JiraClient = Depends(get_jira_client),
    settings: Settings = Depends(get_settings),
    audit_store: AuditStore = Depends(get_audit_store),
) -> FeedResponse:
    try:
        return await process_feed(
            body.text,
            body.source,
            jira,
            settings,
            audit_store,
            issue_type=body.issue_type,
            reporting_service_key=body.reporting_service_key,
            extra_field_values=body.extra_field_values or None,
        )
    except JiraClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/file", response_model=FeedResponse)
async def submit_feed_file(
    file: UploadFile,
    issue_type: str | None = Form(None),
    reporting_service_key: str | None = Form(None),
    extra_field_values: str | None = Form(None, description="JSON object: field_id -> selected option id"),
    jira: JiraClient = Depends(get_jira_client),
    settings: Settings = Depends(get_settings),
    audit_store: AuditStore = Depends(get_audit_store),
) -> FeedResponse:
    # Plain-text/log extraction only in v1 -- no PDF/OCR.
    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400, detail="Only plain-text/log files are supported in this version."
        ) from exc

    try:
        return await process_feed(
            text,
            "file",
            jira,
            settings,
            audit_store,
            issue_type=issue_type,
            reporting_service_key=reporting_service_key,
            extra_field_values=json.loads(extra_field_values) if extra_field_values else None,
        )
    except JiraClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
