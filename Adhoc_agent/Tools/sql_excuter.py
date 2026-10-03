"""Read-only SQL execution (original repository module spelling retained)."""

import sqlite3
import time
from pathlib import Path

from Adhoc_agent.models import QueryResult, SQLPlan, WorkflowError

from .sql_policy import prepare_connection, validate_sql


def execute_sql(database: Path, plan: SQLPlan, max_rows: int, timeout: float) -> QueryResult:
    validate_sql(plan)
    conn = prepare_connection(database)
    deadline = time.monotonic() + timeout
    conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    try:
        cursor = conn.execute(plan.sql, plan.bindings())
        columns = tuple(d[0] for d in cursor.description)
        if len({c.casefold() for c in columns}) != len(columns):
            raise WorkflowError("Report column names must be unique; add SQL aliases.")
        rows = cursor.fetchmany(max_rows + 1)
        if len(rows) > max_rows:
            raise WorkflowError(
                f"Result exceeds {max_rows} rows; narrow the request. "
                "No partial report was published."
            )
        return QueryResult(columns, tuple(tuple(row) for row in rows))
    except sqlite3.Error as exc:
        if "interrupted" in str(exc).lower():
            raise WorkflowError("Query exceeded the configured time limit.") from exc
        raise WorkflowError("Read-only query execution failed: " + str(exc)) from exc
    finally:
        conn.close()
