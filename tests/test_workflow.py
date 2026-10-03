import csv
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Adhoc_agent.cli import main
from Adhoc_agent.config import Settings
from Adhoc_agent.demo import DEMO_REQUEST, DemoClient
from Adhoc_agent.models import (
    Binding,
    QueryResult,
    SemanticReview,
    SQLPlan,
    Ticket,
    ValidationReceipt,
    WorkflowError,
)
from Adhoc_agent.Tools.database import create_sample_database
from Adhoc_agent.Tools.gemini import GeminiClient
from Adhoc_agent.Tools.queue import LocalQueue
from Adhoc_agent.Tools.report_generator import publish_report
from Adhoc_agent.Tools.sql_excuter import execute_sql
from Adhoc_agent.Tools.sql_policy import check_query_compiles, prepare_connection, validate_sql
from Adhoc_agent.workflows.adhoc_workflow import AdhocWorkflow


@pytest.fixture
def settings(tmp_path):
    config = Settings(tmp_path, "", "test")
    create_sample_database(config.database)
    return config


def plan(sql, parameters=None):
    return SQLPlan(sql=sql, parameters=parameters or [], explanation="Test", clarification="")


class StubClient:
    label = "test-stub"

    def __init__(self, proposal, approved=True):
        self.proposal, self.approved = proposal, approved
        self.calls = []

    def generate(self, instruction, payload, response_type):
        self.calls.append((payload, response_type))
        if response_type is SQLPlan:
            return self.proposal
        return SemanticReview(approved=self.approved, reason="Test semantic review.")


def run_ticket(settings, client, request="Test request"):
    queue = LocalQueue(settings.queue)
    ticket_id = queue.submit(request)
    result = AdhocWorkflow(settings, client).run_once()
    ticket = next(t for t in queue.list() if t["id"] == ticket_id)
    return result, ticket


def test_end_to_end_demo_exact_totals_and_artifact_integrity(settings):
    result, ticket = run_ticket(settings, DemoClient(), DEMO_REQUEST)
    assert result.status == ticket["status"] == "completed"
    directory = Path(result.report_path)
    data = json.loads((directory / "data.json").read_text())
    # Failed/pending, USD and both date-boundary rows must not affect these totals.
    assert data["rows"] == [[2, "Demo Customer B", 14000.0], [1, "Demo Customer A", 7500.0]]
    metadata = json.loads((directory / "metadata.json").read_text())
    assert metadata["row_count"] == 2
    assert [s["agent"] for s in ticket["trace"]] == [
        "request",
        "sql",
        "validation",
        "extraction",
        "report",
    ]
    for name, digest in metadata["file_sha256"].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest
    assert AdhocWorkflow(settings, DemoClient()).run_once() is None


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM customer",
        "SELECT full_name FROM customer; DELETE FROM customer",
        "SELECT full_name FROM customer; SELECT full_name FROM customer",
        "PRAGMA table_info(customer)",
        "ATTACH DATABASE 'elsewhere.db' AS external",
        "SELECT name FROM sqlite_master",
        "SELECT customer_id FROM external.customer",
        "SELECT * FROM customer",
        "SELECT c.* FROM customer c",
        "SELECT readfile('/etc/passwd') FROM customer",
        "SELECT load_extension('evil') FROM customer",
        "SELECT randomblob(1000000000) FROM customer",
        "SELECT full_name FROM customer UNION SELECT full_name FROM customer",
        "WITH c AS (SELECT full_name FROM customer) SELECT full_name FROM c",
        "SELECT (SELECT full_name FROM customer) FROM customer",
        "SELECT ROW_NUMBER() OVER () FROM customer",
        'SELECT c.full_name FROM customer c CROSS JOIN "transaction" t',
        'SELECT c.full_name FROM customer c JOIN "transaction" t ON 1=1',
        'SELECT c.full_name FROM customer c JOIN "transaction" t '
        "ON c.customer_id=t.customer_id OR 1=1",
        'SELECT c.full_name FROM customer c NATURAL JOIN "transaction" t',
        'SELECT c.full_name FROM customer c JOIN "transaction" t USING (customer_id)',
        "SELECT c.full_name FROM customer c JOIN customer d ON c.customer_id=d.customer_id",
        "SELECT account_balance FROM customer",
        'SELECT "account_balance" FROM customer',
        'SELECT SUM(amount_minor) FROM "transaction"',
        "SELECT SUM(amount_minor) FROM \"transaction\" WHERE currency='EGP' OR 1=1",
        "SELECT full_name FROM customer WHERE customer_id=?",
    ],
)
def test_unsafe_or_unsupported_sql_is_rejected(sql):
    with pytest.raises(WorkflowError):
        validate_sql(plan(sql))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS customer_count FROM customer",
        'SELECT currency, SUM(amount_minor) AS total_minor FROM "transaction" GROUP BY currency',
        "SELECT SUM(amount_minor) AS total_minor FROM \"transaction\" WHERE currency='EGP'",
        "SELECT full_name, LOWER(city) AS city_lower FROM customer",
        'SELECT DATE(transaction_date) AS date FROM "transaction"',
        "SELECT STRFTIME('%Y-%m', transaction_date) AS month FROM \"transaction\"",
        "SELECT CASE WHEN city='Cairo' THEN 1 ELSE 0 END AS is_cairo FROM customer",
    ],
)
def test_supported_sql_compiles_and_executes(settings, sql):
    proposal = plan(sql)
    validate_sql(proposal)
    check_query_compiles(settings.database, proposal)
    assert execute_sql(settings.database, proposal, 100, 5).rows


def test_sqlite_authorizer_blocks_writes_and_schema_read_even_without_parser(settings):
    conn = prepare_connection(settings.database)
    try:
        for sql in [
            "DELETE FROM customer",
            "SELECT name FROM sqlite_master",
            "PRAGMA user_version",
        ]:
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(sql)
    finally:
        conn.close()
    with sqlite3.connect(settings.database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM customer").fetchone()[0] == 4


def test_parameter_injection_is_a_bound_literal(settings):
    proposal = plan(
        "SELECT full_name FROM customer WHERE city=:city",
        [
            Binding(name="city", kind="text", value="Cairo' OR 1=1 --"),
        ],
    )
    assert execute_sql(settings.database, proposal, 100, 5).rows == ()


@pytest.mark.parametrize(
    "bindings",
    [
        [],
        [Binding(name="extra", kind="text", value="Cairo")],
        [
            Binding(name="city", kind="text", value="Cairo"),
            Binding(name="city", kind="text", value="Giza"),
        ],
    ],
)
def test_parameter_names_must_match_sql(bindings):
    with pytest.raises(WorkflowError):
        validate_sql(plan("SELECT full_name FROM customer WHERE city=:city", bindings))


@pytest.mark.parametrize(
    "kind,value",
    [("real", "NaN"), ("real", "Infinity"), ("integer", "1.5"), ("integer", str(2**64))],
)
def test_invalid_numeric_bindings_are_rejected(kind, value):
    with pytest.raises(WorkflowError):
        Binding(name="p", kind=kind, value=value).converted()


def test_left_join_preserves_customers_with_no_transactions(settings):
    proposal = plan("""SELECT c.customer_id, COALESCE(SUM(t.amount_minor),0) AS total_minor
        FROM customer c LEFT JOIN "transaction" t
        ON (c.customer_id=t.customer_id) AND t.currency='EGP' AND t.status='completed'
        GROUP BY c.customer_id ORDER BY c.customer_id""")
    assert execute_sql(settings.database, proposal, 100, 5).rows[-1] == (4, 0)


def test_semantic_rejection_does_not_extract_or_publish(settings):
    client = StubClient(plan("SELECT full_name FROM customer"), approved=False)
    result, ticket = run_ticket(settings, client)
    assert result.status == ticket["status"] == "needs_clarification"
    assert len(client.calls) == 2
    assert not settings.reports.exists()


def test_generation_clarification_does_not_call_reviewer(settings):
    proposal = plan("")
    proposal.clarification = "Which month and currency?"
    client = StubClient(proposal)
    result, _ = run_ticket(settings, client)
    assert result.status == "needs_clarification"
    assert len(client.calls) == 1


def test_unsafe_generation_fails_before_semantic_review(settings):
    client = StubClient(plan("DELETE FROM customer"))
    result, ticket = run_ticket(settings, client)
    assert result.status == ticket["status"] == "failed"
    assert len(client.calls) == 1
    assert not settings.reports.exists()


def test_overflow_fails_without_truncating_or_closing_ticket(settings):
    small = Settings(settings.runtime, "", "test", max_rows=2)
    result, ticket = run_ticket(small, StubClient(plan("SELECT full_name FROM customer")))
    assert result.status == ticket["status"] == "failed"
    assert "exceeds 2 rows" in result.error
    assert not settings.reports.exists()


def test_empty_result_publishes_headers_and_explicit_empty_message(settings):
    result, ticket = run_ticket(
        settings,
        StubClient(
            plan("SELECT full_name FROM customer WHERE customer_id=-1"),
        ),
    )
    assert result.status == ticket["status"] == "completed"
    directory = Path(result.report_path)
    assert "No matching records." in (directory / "report.html").read_text()
    assert json.loads((directory / "metadata.json").read_text())["empty_result"]
    with (directory / "data.csv").open(encoding="utf-8-sig", newline="") as stream:
        assert list(csv.reader(stream)) == [["full_name"]]


def test_duplicate_output_names_are_rejected(settings):
    with pytest.raises(WorkflowError, match="unique"):
        execute_sql(
            settings.database, plan("SELECT full_name AS n, city AS n FROM customer"), 10, 5
        )


def test_report_escapes_html_and_csv_formulas(tmp_path):
    result = QueryResult(("name",), (("=1+1",), ("<script>alert(1)</script>",)))
    ticket = Ticket("../../unsafe", "<img src=x onerror=alert(1)>")
    receipt = ValidationReceipt(plan("SELECT full_name FROM customer"), "Test")
    report = publish_report(tmp_path, ticket, receipt, result, "test", [])
    assert report.parent == tmp_path
    html = (report / "report.html").read_text()
    assert "<script>" not in html and "<img " not in html
    assert "&lt;script&gt;" in html
    with (report / "data.csv").open(encoding="utf-8-sig", newline="") as stream:
        assert list(csv.reader(stream))[1] == ["'=1+1"]
    with pytest.raises(WorkflowError, match="overwrite"):
        publish_report(tmp_path, ticket, receipt, result, "test", [])


def test_report_write_failure_does_not_publish_or_complete_ticket(settings, monkeypatch):
    original = Path.write_text

    def fail_metadata(path, *args, **kwargs):
        if path.name == "metadata.json":
            raise OSError("Simulated disk error")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_metadata)
    result, ticket = run_ticket(settings, DemoClient(), DEMO_REQUEST)
    assert result.status == ticket["status"] == "failed"
    assert list(settings.reports.iterdir()) == []


def test_queue_claim_is_atomic_and_retries_are_explicit(settings):
    queue = LocalQueue(settings.queue)
    ticket_id = queue.submit("Test")
    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(lambda _: queue.claim(), range(2)))
    assert sum(t is not None for t in claimed) == 1
    queue.finish(ticket_id, "failed", [], error="Test failure")
    assert queue.claim() is None
    queue.retry(ticket_id)
    assert queue.claim().id == ticket_id
    with pytest.raises(WorkflowError):
        queue.retry(ticket_id)


def test_sample_init_refuses_to_overwrite_user_data(settings):
    before = settings.database.read_bytes()
    with pytest.raises(WorkflowError, match="overwrite"):
        create_sample_database(settings.database)
    assert settings.database.read_bytes() == before


def test_changed_schema_fails_before_claiming_ticket(settings):
    queue = LocalQueue(settings.queue)
    queue.submit("Test")
    with sqlite3.connect(settings.database) as conn:
        conn.execute("ALTER TABLE customer ADD COLUMN secret TEXT")
    with pytest.raises(WorkflowError, match="schema"):
        AdhocWorkflow(settings, DemoClient()).run_once()
    assert queue.list()[0]["status"] == "pending"


def test_query_timeout_interrupts_expensive_query(settings):
    with sqlite3.connect(settings.database) as conn:
        conn.executemany(
            "INSERT INTO customer VALUES (?, ?, ?, ?, ?)",
            [(i, "Synthetic", "Cairo", "retail", "2025-01-01") for i in range(10, 20010)],
        )
    with pytest.raises(WorkflowError, match="time limit"):
        execute_sql(
            settings.database,
            plan("SELECT full_name FROM customer ORDER BY city"),
            100000,
            0.000001,
        )


def test_model_payloads_never_include_extracted_rows(settings):
    client = StubClient(plan("SELECT full_name FROM customer"))
    result, _ = run_ticket(settings, client)
    assert result.status == "completed"
    assert len(client.calls) == 2
    assert "Demo Customer A" not in json.dumps(client.calls, default=str)


def test_provider_adapter_structured_output_and_no_automatic_retry(monkeypatch):
    sdk = Mock()
    sdk.models.generate_content.return_value = SimpleNamespace(
        text=json.dumps(
            {"approved": True, "reason": "Matches request."},
        )
    )
    factory = Mock(return_value=sdk)
    monkeypatch.setattr("Adhoc_agent.Tools.gemini.genai.Client", factory)
    client = GeminiClient("test-placeholder", "test-model")
    assert factory.call_args.kwargs["http_options"].retry_options.attempts == 1
    review = client.generate("review", {"request": "test"}, SemanticReview)
    assert review.approved
    assert sdk.models.generate_content.call_args.kwargs["config"].response_json_schema
    sdk.models.generate_content.return_value = SimpleNamespace(text='{"approved":true}')
    with pytest.raises(WorkflowError, match="invalid structured"):
        client.generate("review", {}, SemanticReview)
    sdk.models.generate_content.return_value = SimpleNamespace(
        text='{"approved":"yes","reason":"not a boolean"}'
    )
    with pytest.raises(WorkflowError, match="invalid structured"):
        client.generate("review", {}, SemanticReview)
    sdk.models.generate_content.side_effect = RuntimeError("sensitive-provider-details")
    with pytest.raises(WorkflowError) as error:
        client.generate("review", {}, SemanticReview)
    assert "sensitive-provider-details" not in str(error.value)
    client.close()


def test_cli_demo_is_separate_from_real_pending_queue(tmp_path):
    queue = LocalQueue(tmp_path / "tickets.db")
    real = queue.submit("Do not process this in demo mode.")
    assert main(["--runtime", str(tmp_path), "demo"]) == 0
    assert queue.list()[0]["id"] == real
    assert queue.list()[0]["status"] == "pending"
    assert not (tmp_path / "bank.db").exists()
