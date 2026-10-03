"""Persistent local stand-in for an ITSM queue; no external ticket mutations."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from Adhoc_agent.models import Ticket, WorkflowError


class LocalQueue:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS tickets (
                id TEXT PRIMARY KEY, request TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                  CHECK(status IN ('pending','in_progress','completed','failed','needs_clarification')),
                report_path TEXT, error TEXT, trace TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )""")

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def submit(self, request: str) -> str:
        request = request.strip()
        if not request or len(request) > 8000:
            raise WorkflowError("Request must contain 1..8000 characters.")
        ticket_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute("INSERT INTO tickets (id,request) VALUES (?,?)", (ticket_id, request))
        return ticket_id

    def claim(self, ticket_id: str | None = None) -> Ticket | None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            sql = "SELECT id,request FROM tickets WHERE status='pending'"
            params = ()
            if ticket_id is not None:
                sql += " AND id=?"
                params = (ticket_id,)
            row = conn.execute(sql + " ORDER BY rowid LIMIT 1", params).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE tickets SET status='in_progress', "
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                (row["id"],),
            )
            return Ticket(row["id"], row["request"])

    def get(self, ticket_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        return {**dict(row), "trace": json.loads(row["trace"])} if row else None

    def progress(self, ticket_id: str, trace: list):
        with self._connect() as conn:
            conn.execute(
                "UPDATE tickets SET trace=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE id=? AND status='in_progress'",
                (json.dumps(trace), ticket_id),
            )

    def finish(
        self,
        ticket_id: str,
        status: str,
        trace: list,
        *,
        report_path: str | None = None,
        error: str | None = None,
    ):
        if status not in {"completed", "failed", "needs_clarification"}:
            raise WorkflowError("Invalid final ticket status.")
        if status == "completed" and (not report_path or not Path(report_path).is_dir()):
            raise WorkflowError("Cannot complete a ticket without a published report.")
        with self._connect() as conn:
            changed = conn.execute(
                """UPDATE tickets SET status=?,report_path=?,error=?,trace=?,
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE id=? AND status='in_progress'""",
                (status, report_path, error, json.dumps(trace), ticket_id),
            ).rowcount
            if changed != 1:
                raise WorkflowError("Ticket is no longer owned by this workflow.")

    def list(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM tickets ORDER BY rowid").fetchall()
        return [{**dict(row), "trace": json.loads(row["trace"])} for row in rows]

    def retry(self, ticket_id: str):
        with self._connect() as conn:
            changed = conn.execute(
                """UPDATE tickets SET status='pending', error=NULL,
                trace='[]', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE id=? AND status IN ('failed','needs_clarification')""",
                (ticket_id,),
            ).rowcount
            if changed != 1:
                raise WorkflowError("Only failed or clarification tickets can be retried.")
