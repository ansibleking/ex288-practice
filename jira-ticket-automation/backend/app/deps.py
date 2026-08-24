from fastapi import Request

from app.audit import AuditStore
from app.jira_client import JiraClient
from app.schedule_store import ScheduleStore


def get_jira_client(request: Request) -> JiraClient:
    return request.app.state.jira_client


def get_audit_store(request: Request) -> AuditStore:
    return request.app.state.audit_store


def get_schedule_store(request: Request) -> ScheduleStore:
    return request.app.state.schedule_store
