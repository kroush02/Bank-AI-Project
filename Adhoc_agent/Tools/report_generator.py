"""Publish complete local report bundles atomically, using only extracted facts."""

import csv
import hashlib
import html
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from Adhoc_agent.models import QueryResult, Ticket, ValidationReceipt, WorkflowError


def csv_value(value):
    # Text beginning with these characters must not become an Excel formula.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def publish_report(
    root: Path,
    ticket: Ticket,
    receipt: ValidationReceipt,
    result: QueryResult,
    model: str,
    trace: list,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    # The queue generates UUIDs; do not interpolate arbitrary IDs into filesystem paths.
    report_name = hashlib.sha256(ticket.id.encode()).hexdigest()[:20]
    destination = root / report_name
    if destination.exists():
        raise WorkflowError("A report already exists for this ticket; refusing to overwrite it.")
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=root))
    try:
        metadata = {
            "ticket_id": ticket.id,
            "request": ticket.request,
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "model": model,
            "sql": receipt.plan.sql,
            "parameters": receipt.plan.bindings(),
            "explanation": receipt.plan.explanation,
            "validation": {"sql_policy": "passed", "semantic_review": receipt.reason},
            "row_count": len(result.rows),
            "columns": result.columns,
            "empty_result": not result.rows,
            "trace": trace + [{"agent": "report", "status": "published"}],
        }
        with (staging / "data.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow([csv_value(c) for c in result.columns])
            writer.writerows([[csv_value(v) for v in row] for row in result.rows])
        (staging / "data.json").write_text(
            json.dumps(
                {
                    "columns": result.columns,
                    "rows": result.rows,
                },
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        headers = "".join(f"<th>{html.escape(c)}</th>" for c in result.columns)
        body = "".join(
            "<tr>"
            + "".join(f"<td>{html.escape('' if v is None else str(v))}</td>" for v in row)
            + "</tr>"
            for row in result.rows
        )
        if not result.rows:
            body = f'<tr><td colspan="{len(result.columns)}">No matching records.</td></tr>'
        document = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bank ad-hoc report</title><style>
body{{font:16px system-ui;margin:40px auto;max-width:1100px;padding:0 24px;color:#182b3c}}
h1{{color:#164e63}}.meta{{color:#526475}}table{{border-collapse:collapse;width:100%}}
th,td{{padding:12px;border-bottom:1px solid #ccd7de;text-align:left}}th{{background:#e7f0f4}}
pre{{white-space:pre-wrap;background:#edf3f6;padding:16px;border-radius:6px;overflow-wrap:anywhere}}
section{{overflow-x:auto}}a{{color:#164e63}}footer{{margin-top:28px;color:#526475}}
</style><h1>Bank ad-hoc report</h1>
<p class="meta">Ticket {html.escape(ticket.id)} · {len(result.rows)} rows ·
{html.escape(metadata["generated_at_utc"])}</p>
<h2>Request</h2><p>{html.escape(ticket.request)}</p>
<p>{html.escape(receipt.plan.explanation)}</p>
<p><a href="data.csv">Download CSV</a> · <a href="data.json">JSON data</a> ·
<a href="metadata.json">Audit metadata</a></p>
<section><table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></section>
<h2>Validation</h2><p>{html.escape(receipt.reason)}</p>
<details><summary>SQL and parameters</summary><pre>{html.escape(receipt.plan.sql)}</pre>
<pre>{html.escape(json.dumps(receipt.plan.bindings(), indent=2))}</pre></details>
<footer>Local report · Model: {html.escape(model)} · Rows stay on this machine.
Automated validation does not establish production or business acceptance.</footer></html>"""
        (staging / "report.html").write_text(document, encoding="utf-8")
        metadata["file_sha256"] = {
            name: hashlib.sha256((staging / name).read_bytes()).hexdigest()
            for name in ("data.csv", "data.json", "report.html")
        }
        (staging / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )
        # The ticket is only completed after all four files are visible together.
        staging.rename(destination)
        return destination.resolve()
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
