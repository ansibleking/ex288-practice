from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from app.classifier import FeedClassification
from app.routing import RoutingDecision

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    input_text TEXT NOT NULL,
    input_source TEXT NOT NULL,
    llm_intent TEXT NOT NULL,
    llm_confidence REAL NOT NULL,
    llm_severity TEXT NOT NULL,
    llm_matched_ticket_key TEXT,
    llm_title TEXT NOT NULL,
    llm_summary TEXT NOT NULL,
    llm_reasoning TEXT NOT NULL,
    llm_raw_response_json TEXT NOT NULL,
    routing_decision TEXT NOT NULL,
    threshold_confidence_min REAL NOT NULL,
    threshold_severity_max TEXT NOT NULL,
    action_status TEXT NOT NULL,
    jira_action_type TEXT,
    jira_issue_key TEXT,
    jira_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at);
"""

# action_status values
STATUS_EXECUTED = "executed"
STATUS_PENDING = "pending_confirmation"
STATUS_CONFIRMED = "confirmed"
STATUS_CANCELLED = "cancelled"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"


class AuditRow(BaseModel):
    id: int
    created_at: str
    input_text: str
    input_source: str
    llm_intent: str
    llm_confidence: float
    llm_severity: str
    llm_matched_ticket_key: str | None
    llm_title: str
    llm_summary: str
    llm_reasoning: str
    llm_raw_response_json: str
    routing_decision: str
    threshold_confidence_min: float
    threshold_severity_max: str
    action_status: str
    jira_action_type: str | None
    jira_issue_key: str | None
    jira_error: str | None


def _row_to_model(row: sqlite3.Row) -> AuditRow:
    return AuditRow(**{key: row[key] for key in row.keys()})


class AuditStore:
    """Persists every AI decision, independent of Jira, for compliance review.

    Plain sqlite3 wrapped in asyncio.to_thread -- this is a low-volume
    internal tool, so a full async DB driver would be unwarranted, but the
    calls still shouldn't block the FastAPI event loop directly.
    """

    def __init__(self, database_path: str):
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    async def create(
        self,
        *,
        input_text: str,
        input_source: str,
        classification: FeedClassification,
        raw_response_json: str,
        routing_decision: RoutingDecision,
        threshold_confidence_min: float,
        threshold_severity_max: str,
        action_status: str,
        jira_action_type: str | None = None,
        jira_issue_key: str | None = None,
        jira_error: str | None = None,
    ) -> AuditRow:
        return await asyncio.to_thread(
            self._create_sync,
            input_text=input_text,
            input_source=input_source,
            classification=classification,
            raw_response_json=raw_response_json,
            routing_decision=routing_decision,
            threshold_confidence_min=threshold_confidence_min,
            threshold_severity_max=threshold_severity_max,
            action_status=action_status,
            jira_action_type=jira_action_type,
            jira_issue_key=jira_issue_key,
            jira_error=jira_error,
        )

    def _create_sync(
        self,
        *,
        input_text: str,
        input_source: str,
        classification: FeedClassification,
        raw_response_json: str,
        routing_decision: RoutingDecision,
        threshold_confidence_min: float,
        threshold_severity_max: str,
        action_status: str,
        jira_action_type: str | None,
        jira_issue_key: str | None,
        jira_error: str | None,
    ) -> AuditRow:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_log (
                    created_at, input_text, input_source,
                    llm_intent, llm_confidence, llm_severity, llm_matched_ticket_key,
                    llm_title, llm_summary, llm_reasoning, llm_raw_response_json,
                    routing_decision, threshold_confidence_min, threshold_severity_max,
                    action_status, jira_action_type, jira_issue_key, jira_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    input_text,
                    input_source,
                    classification.intent.value,
                    classification.confidence,
                    classification.severity.value,
                    classification.matched_ticket_key,
                    classification.title,
                    classification.summary,
                    classification.reasoning,
                    raw_response_json,
                    routing_decision.value,
                    threshold_confidence_min,
                    threshold_severity_max,
                    action_status,
                    jira_action_type,
                    jira_issue_key,
                    jira_error,
                ),
            )
            row_id = cursor.lastrowid
            row = conn.execute("SELECT * FROM audit_log WHERE id = ?", (row_id,)).fetchone()
        return _row_to_model(row)

    async def update_action_outcome(
        self,
        audit_id: int,
        *,
        action_status: str,
        jira_action_type: str | None = None,
        jira_issue_key: str | None = None,
        jira_error: str | None = None,
    ) -> AuditRow | None:
        return await asyncio.to_thread(
            self._update_sync, audit_id, action_status, jira_action_type, jira_issue_key, jira_error
        )

    def _update_sync(
        self,
        audit_id: int,
        action_status: str,
        jira_action_type: str | None,
        jira_issue_key: str | None,
        jira_error: str | None,
    ) -> AuditRow | None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE audit_log
                SET action_status = ?, jira_action_type = ?, jira_issue_key = ?, jira_error = ?
                WHERE id = ?
                """,
                (action_status, jira_action_type, jira_issue_key, jira_error, audit_id),
            )
            row = conn.execute("SELECT * FROM audit_log WHERE id = ?", (audit_id,)).fetchone()
        return _row_to_model(row) if row else None

    async def get(self, audit_id: int) -> AuditRow | None:
        return await asyncio.to_thread(self._get_sync, audit_id)

    def _get_sync(self, audit_id: int) -> AuditRow | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM audit_log WHERE id = ?", (audit_id,)).fetchone()
        return _row_to_model(row) if row else None

    async def list(
        self, limit: int = 50, offset: int = 0, status: str | None = None
    ) -> list[AuditRow]:
        return await asyncio.to_thread(self._list_sync, limit, offset, status)

    def _list_sync(self, limit: int, offset: int, status: str | None) -> list[AuditRow]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM audit_log WHERE action_status = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (status, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
                ).fetchall()
        return [_row_to_model(r) for r in rows]

    async def list_pending(self) -> list[AuditRow]:
        return await self.list(limit=1000, offset=0, status=STATUS_PENDING)
