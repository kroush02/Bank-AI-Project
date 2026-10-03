"""Small loopback-only HTTP server. The existing workflow owns report publication."""

import html
import io
import json
import secrets
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from Adhoc_agent.config import Settings
from Adhoc_agent.models import WorkflowError
from Adhoc_agent.Tools.database import check_schema
from Adhoc_agent.Tools.gemini import GeminiClient
from Adhoc_agent.Tools.queue import LocalQueue
from Adhoc_agent.workflows.adhoc_workflow import AdhocWorkflow

STATIC = Path(__file__).parent / "static"
REPORT_FILES = {
    "report.html": "text/html; charset=utf-8",
    "data.csv": "text/csv; charset=utf-8",
    "data.json": "application/json",
    "metadata.json": "application/json",
}


class Studio:
    def __init__(self, settings: Settings, client_factory=GeminiClient):
        self.settings = settings
        self.queue = LocalQueue(settings.queue)
        self.client_factory = client_factory
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.active_ticket = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="report-studio")

    def configuration(self):
        problem = None
        if not self.settings.api_key:
            problem = "Add GEMINI_API_KEY to the local .env file, then restart Report Studio."
        try:
            check_schema(self.settings.database)
        except WorkflowError as exc:
            problem = str(exc)
        return {
            "ready": problem is None,
            "problem": problem,
            "model": self.settings.model,
            "report_directory": str(self.settings.reports),
            "active_ticket": self.active_ticket,
        }

    def submit(self, request: str):
        with self.lock:
            if self.active_ticket:
                raise WorkflowError("A report is already running. Wait for it to finish.")
            config = self.configuration()
            if not config["ready"]:
                raise WorkflowError(config["problem"])
            # Construct the client before saving the ticket. Its constructor makes no API call.
            client = self.client_factory(self.settings.api_key, self.settings.model)
            try:
                ticket_id = self.queue.submit(request)
            except Exception:
                client.close()
                raise
            self.active_ticket = ticket_id
            self.executor.submit(self._run, ticket_id, client)
            return ticket_id

    def _run(self, ticket_id, client):
        try:
            AdhocWorkflow(self.settings, client).run_once(ticket_id)
        except Exception:
            # Handle failures before workflow ownership, without returning provider details.
            ticket = self.queue.get(ticket_id)
            if ticket and ticket["status"] == "pending":
                self.queue.claim(ticket_id)
            if ticket and ticket["status"] in {"pending", "in_progress"}:
                self.queue.finish(
                    ticket_id,
                    "failed",
                    ticket["trace"],
                    error="The report stopped. Check the local configuration.",
                )
        finally:
            try:
                client.close()
            finally:
                with self.lock:
                    self.active_ticket = None

    def public_ticket(self, ticket):
        if ticket is None:
            return None
        result = {
            key: ticket[key]
            for key in (
                "id",
                "request",
                "status",
                "trace",
                "error",
                "created_at",
                "updated_at",
                "report_path",
            )
        }
        result["worker_active"] = self.active_ticket == ticket["id"]
        return result

    def report_directory(self, ticket_id):
        ticket = self.queue.get(ticket_id)
        if not ticket or ticket["status"] != "completed" or not ticket["report_path"]:
            return None
        path = Path(ticket["report_path"]).resolve()
        if path.parent != self.settings.reports.resolve() or not path.is_dir():
            return None
        return path

    def close(self):
        self.executor.shutdown(wait=True)


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, settings, port=8000, client_factory=GeminiClient):
        self.studio = Studio(settings, client_factory)
        try:
            super().__init__(("127.0.0.1", port), StudioHandler)
        except Exception:
            self.studio.close()
            raise

    def server_close(self):
        super().server_close()
        self.studio.close()


class StudioHandler(BaseHTTPRequestHandler):
    server_version = "ReportStudio/1.0"

    def log_message(self, format, *args):
        # Request text and credentials do not belong in HTTP logs.
        pass

    def host_allowed(self):
        return self.headers.get("Host") in {
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        }

    def respond(self, code, data, mime="application/json", filename=None):
        if isinstance(data, (dict, list)):
            data = json.dumps(data, ensure_ascii=False).encode()
        elif isinstance(data, str):
            data = data.encode()
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'self'",
        )
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if not self.host_allowed():
            return self.respond(403, {"error": "This interface is available only on localhost."})
        path = urlsplit(self.path).path
        studio = self.server.studio
        if path == "/":
            page = (
                (STATIC / "index.html")
                .read_text()
                .replace("__CSRF_TOKEN__", html.escape(studio.token))
            )
            return self.respond(200, page, "text/html; charset=utf-8")
        assets = {"/static/app.js": "text/javascript", "/static/style.css": "text/css"}
        if path in assets:
            return self.respond(200, (STATIC / path.rsplit("/", 1)[1]).read_bytes(), assets[path])
        if path == "/api/status":
            return self.respond(200, studio.configuration())
        if path == "/api/tickets":
            tickets = studio.queue.list()[-50:][::-1]
            return self.respond(200, [studio.public_ticket(t) for t in tickets])
        if path.startswith("/api/tickets/"):
            ticket = studio.public_ticket(studio.queue.get(path.removeprefix("/api/tickets/")))
            return (
                self.respond(200, ticket)
                if ticket
                else self.respond(404, {"error": "Ticket not found."})
            )
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] in {"reports", "download"}:
            directory = studio.report_directory(parts[1])
            name = parts[2]
            if directory is None:
                return self.respond(404, {"error": "Published report not found."})
            names = list(REPORT_FILES) if name == "bundle.zip" else [name]
            if any(n not in REPORT_FILES for n in names):
                return self.respond(404, {"error": "Report file not found."})
            if any(not (directory / n).is_file() or (directory / n).is_symlink() for n in names):
                return self.respond(404, {"error": "Report file is missing."})
            if name == "bundle.zip":
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                    for n in names:
                        archive.write(directory / n, n)
                return self.respond(
                    200, buffer.getvalue(), "application/zip", f"report-{parts[1]}.zip"
                )
            return self.respond(
                200,
                (directory / name).read_bytes(),
                REPORT_FILES[name],
                name if parts[0] == "download" else None,
            )
        self.respond(404, {"error": "Page not found."})

    def do_POST(self):
        if not self.host_allowed():
            return self.respond(403, {"error": "Invalid host."})
        studio = self.server.studio
        origin = self.headers.get("Origin")
        allowed_origins = {
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        }
        if (origin and origin not in allowed_origins) or not secrets.compare_digest(
            self.headers.get("X-Studio-Token", ""),
            studio.token,
        ):
            return self.respond(403, {"error": "Reload this page before you submit a request."})
        if urlsplit(self.path).path != "/api/tickets":
            return self.respond(404, {"error": "Page not found."})
        if self.headers.get_content_type() != "application/json":
            return self.respond(415, {"error": "Use a JSON request."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 40000 or self.headers.get("Transfer-Encoding"):
                return self.respond(413, {"error": "Request is too large or empty."})
            self.connection.settimeout(10)
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or not isinstance(body.get("request"), str):
                raise ValueError
            ticket_id = studio.submit(body["request"])
            self.respond(202, {"id": ticket_id})
        except (ValueError, UnicodeError, TimeoutError):
            self.respond(400, {"error": "Enter a valid text request."})
        except WorkflowError as exc:
            self.respond(409, {"error": str(exc)})
        except Exception:
            self.respond(
                500, {"error": "The request could not start. Check the local configuration."}
            )


def serve(settings: Settings, port: int):
    try:
        server = StudioServer(settings, port)
    except OSError as exc:
        raise WorkflowError("Could not start Report Studio. Try another --port.") from exc
    print(f"Report Studio: http://127.0.0.1:{server.server_port}", flush=True)
    print("Press Ctrl-C to stop. A running report will finish before exit.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
