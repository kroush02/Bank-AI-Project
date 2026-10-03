import sqlite3
from contextlib import closing
from pathlib import Path

from Adhoc_agent.models import WorkflowError

from .schema import SCHEMA_SQL, TABLE_COLUMNS


def create_sample_database(path: Path) -> None:
    """Create fictional demo data exclusively; refuse to overwrite an existing database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.touch(exist_ok=False)
    except FileExistsError as exc:
        raise WorkflowError(
            "Database already exists; sample initialization will not overwrite it."
        ) from exc
    try:
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(SCHEMA_SQL)
            conn.executemany(
                "INSERT INTO customer VALUES (?, ?, ?, ?, ?)",
                [
                    (1, "Demo Customer A", "Cairo", "retail", "2025-01-10"),
                    (2, "Demo Customer B", "Alexandria", "business", "2025-02-15"),
                    (3, "Demo Customer C", "Cairo", "retail", "2025-03-20"),
                    (4, "Demo Customer D", "Giza", "retail", "2025-04-01"),
                ],
            )
            conn.executemany(
                'INSERT INTO "transaction" VALUES (?, ?, ?, ?, ?, ?, ?)',
                [
                    (1, 1, 300000, "EGP", "debit", "completed", "2026-09-03"),
                    (2, 1, 450000, "EGP", "debit", "completed", "2026-09-15"),
                    (3, 2, 1200000, "EGP", "credit", "completed", "2026-09-07"),
                    (4, 2, 200000, "EGP", "debit", "completed", "2026-09-21"),
                    (5, 3, 150000, "EGP", "debit", "completed", "2026-09-11"),
                    (6, 1, 900000, "EGP", "debit", "failed", "2026-09-16"),
                    (7, 2, 100000, "USD", "credit", "completed", "2026-09-08"),
                    (8, 1, 600000, "EGP", "debit", "completed", "2026-08-31"),
                    (9, 3, 800000, "EGP", "credit", "pending", "2026-09-12"),
                    (10, 1, 700000, "EGP", "debit", "completed", "2026-10-01"),
                ],
            )
            conn.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise


def open_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise WorkflowError("Bank database missing. Run init-demo first.")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    return conn


def check_schema(path: Path) -> None:
    """Never generate SQL against an unexpected database."""
    with closing(open_readonly(path)) as conn:
        for table, expected in TABLE_COLUMNS.items():
            actual = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
            if actual != expected:
                raise WorkflowError(f"Unexpected schema for {table}; configure the schema first.")
        foreign_keys = conn.execute('PRAGMA foreign_key_list("transaction")').fetchall()
        if not any(r[2:5] == ("customer", "customer_id", "customer_id") for r in foreign_keys):
            raise WorkflowError("Transaction/customer foreign key is missing.")
