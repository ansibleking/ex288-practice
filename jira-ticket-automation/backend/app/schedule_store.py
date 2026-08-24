from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT,
    text TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    status TEXT NOT NULL,
    jira_issue_key TEXT,
    classification_json TEXT,
    create_audit_id INTEGER,
    resolve_audit_id INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_scheduled_items_start_at ON scheduled_items(start_at);
"""

# Columns added after the initial release -- CREATE TABLE IF NOT EXISTS is a
# no-op against an already-existing table, so these need an explicit
# best-effort ALTER TABLE for databases created before this column existed.
_MIGRATION_COLUMNS = [("reporting_service_key", "TEXT"), ("extra_field_values_json", "TEXT")]

# status values
STATUS_PENDING = "pending"
STATUS_CREATED = "created"
STATUS_RESOLVED = "resolved"
STATUS_CREATE_FAILED = "create_failed"
STATUS_RESOLVE_FAILED = "resolve_failed"
STATUS_CANCELLED = "cancelled"


class ScheduledItem(BaseModel):
    id: int
    created_at: str
    start_at: str
    end_at: str | None
    text: str
    issue_type: str
    reporting_service_key: str | None
    extra_field_values_json: str | None
    status: str
    jira_issue_key: str | None
    classification_json: str | None
    create_audit_id: int | None
    resolve_audit_id: int | None
    error: str | None


def _row_to_model(row: sqlite3.Row) -> ScheduledItem:
    return ScheduledItem(**{key: row[key] for key in row.keys()})


class ScheduleStore:
    """Persists day-planner entries the scheduler background loop acts on.

    Same plain-sqlite3-in-a-thread shape as AuditStore -- low volume, no
    need for a full async driver, but calls still shouldn't block the
    event loop.
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
            existing = {row[1] for row in conn.execute("PRAGMA table_info(scheduled_items)")}
            for column, sql_type in _MIGRATION_COLUMNS:
                if column not in existing:
                    conn.execute(f"ALTER TABLE scheduled_items ADD COLUMN {column} {sql_type}")

    async def create(
        self,
        *,
        start_at: str,
        end_at: str | None,
        text: str,
        issue_type: str,
        reporting_service_key: str | None = None,
        extra_field_values_json: str | None = None,
    ) -> ScheduledItem:
        return await asyncio.to_thread(
            self._create_sync,
            start_at,
            end_at,
            text,
            issue_type,
            reporting_service_key,
            extra_field_values_json,
        )

    def _create_sync(
        self,
        start_at: str,
        end_at: str | None,
        text: str,
        issue_type: str,
        reporting_service_key: str | None,
        extra_field_values_json: str | None,
    ) -> ScheduledItem:
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO scheduled_items
                    (created_at, start_at, end_at, text, issue_type, reporting_service_key,
                     extra_field_values_json, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    start_at,
                    end_at,
                    text,
                    issue_type,
                    reporting_service_key,
                    extra_field_values_json,
                    STATUS_PENDING,
                ),
            )
            row_id = cursor.lastrowid
            row = conn.execute("SELECT * FROM scheduled_items WHERE id = ?", (row_id,)).fetchone()
        return _row_to_model(row)

    async def get(self, item_id: int) -> ScheduledItem | None:
        return await asyncio.to_thread(self._get_sync, item_id)

    def _get_sync(self, item_id: int) -> ScheduledItem | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM scheduled_items WHERE id = ?", (item_id,)).fetchone()
        return _row_to_model(row) if row else None

    async def list_for_range(self, start: str, end: str) -> list[ScheduledItem]:
        return await asyncio.to_thread(self._list_for_range_sync, start, end)

    def _list_for_range_sync(self, start: str, end: str) -> list[ScheduledItem]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_items WHERE start_at >= ? AND start_at < ? ORDER BY start_at",
                (start, end),
            ).fetchall()
        return [_row_to_model(r) for r in rows]

    async def list_due_for_create(self, now_iso: str) -> list[ScheduledItem]:
        return await asyncio.to_thread(self._list_due_for_create_sync, now_iso)

    def _list_due_for_create_sync(self, now_iso: str) -> list[ScheduledItem]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_items WHERE status = ? AND start_at <= ? ORDER BY start_at",
                (STATUS_PENDING, now_iso),
            ).fetchall()
        return [_row_to_model(r) for r in rows]

    async def list_due_for_resolve(self, now_iso: str) -> list[ScheduledItem]:
        return await asyncio.to_thread(self._list_due_for_resolve_sync, now_iso)

    def _list_due_for_resolve_sync(self, now_iso: str) -> list[ScheduledItem]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM scheduled_items
                WHERE status = ? AND end_at IS NOT NULL AND end_at <= ?
                ORDER BY end_at
                """,
                (STATUS_CREATED, now_iso),
            ).fetchall()
        return [_row_to_model(r) for r in rows]

    async def mark_created(
        self, item_id: int, *, jira_issue_key: str, classification_json: str, create_audit_id: int
    ) -> ScheduledItem | None:
        return await asyncio.to_thread(
            self._set_sync,
            item_id,
            "status = ?, jira_issue_key = ?, classification_json = ?, create_audit_id = ?",
            (STATUS_CREATED, jira_issue_key, classification_json, create_audit_id),
        )

    async def mark_create_failed(
        self, item_id: int, *, error: str, create_audit_id: int | None = None
    ) -> ScheduledItem | None:
        return await asyncio.to_thread(
            self._set_sync,
            item_id,
            "status = ?, error = ?, create_audit_id = ?",
            (STATUS_CREATE_FAILED, error, create_audit_id),
        )

    async def mark_resolved(self, item_id: int, *, resolve_audit_id: int) -> ScheduledItem | None:
        return await asyncio.to_thread(
            self._set_sync, item_id, "status = ?, resolve_audit_id = ?", (STATUS_RESOLVED, resolve_audit_id)
        )

    async def mark_resolve_failed(
        self, item_id: int, *, error: str, resolve_audit_id: int | None = None
    ) -> ScheduledItem | None:
        return await asyncio.to_thread(
            self._set_sync,
            item_id,
            "status = ?, error = ?, resolve_audit_id = ?",
            (STATUS_RESOLVE_FAILED, error, resolve_audit_id),
        )

    async def cancel(self, item_id: int) -> ScheduledItem | None:
        return await asyncio.to_thread(self._set_sync, item_id, "status = ?", (STATUS_CANCELLED,))

    def _set_sync(self, item_id: int, set_clause: str, values: tuple) -> ScheduledItem | None:
        with self._connect() as conn:
            conn.execute(f"UPDATE scheduled_items SET {set_clause} WHERE id = ?", (*values, item_id))
            row = conn.execute("SELECT * FROM scheduled_items WHERE id = ?", (item_id,)).fetchone()
        return _row_to_model(row) if row else None
