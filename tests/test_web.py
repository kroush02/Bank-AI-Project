import io
import json
import threading
import time
import zipfile
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from Adhoc_agent.config import Settings
from Adhoc_agent.demo import DEMO_REQUEST, DemoClient
from Adhoc_agent.Tools.database import create_sample_database
from Adhoc_agent.web.server import StudioServer


class FakeClient(DemoClient):
    def close(self):
        pass


@contextmanager
def running_server(
    tmp_path, client_factory=lambda key, model: FakeClient(), key="private-test-key"
):
    settings = Settings(tmp_path, key, "fixture")
    create_sample_database(settings.database)
    server = StudioServer(settings, 0, client_factory)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(url, data=None, token=None, **headers):
    if data is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    if token:
        headers["X-Studio-Token"] = token
    try:
        with urlopen(Request(url, data=data, headers=headers), timeout=5) as response:
            return response.status, response.headers, response.read()
    except HTTPError as error:
        return error.code, error.headers, error.read()


def wait_ticket(server, ticket_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        ticket = server.studio.queue.get(ticket_id)
        if ticket["status"] not in {"pending", "in_progress"}:
            return ticket
        time.sleep(0.01)
    pytest.fail("Ticket did not finish")


def test_browser_submission_publishes_correct_ticket_and_downloads(tmp_path):
    with running_server(tmp_path) as (server, url):
        old = server.studio.queue.submit("Older unrelated request")
        status, _, raw = request(
            url + "/api/tickets", {"request": DEMO_REQUEST}, server.studio.token
        )
        assert status == 202
        ticket_id = json.loads(raw)["id"]
        ticket = wait_ticket(server, ticket_id)
        assert ticket["status"] == "completed"
        assert server.studio.queue.get(old)["status"] == "pending"
        status, _, raw = request(url + f"/reports/{ticket_id}/data.json")
        assert status == 200
        assert json.loads(raw)["rows"] == [
            [2, "Demo Customer B", 14000.0],
            [1, "Demo Customer A", 7500.0],
        ]
        for name in ["data.csv", "data.json", "metadata.json", "report.html", "bundle.zip"]:
            status, headers, content = request(url + f"/download/{ticket_id}/{name}")
            assert status == 200
            assert headers["Content-Disposition"].startswith("attachment;")
            assert b"private-test-key" not in content
            if name == "bundle.zip":
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    assert archive.testzip() is None
                    assert set(archive.namelist()) == {
                        "data.csv",
                        "data.json",
                        "metadata.json",
                        "report.html",
                    }
        assert request(url + f"/reports/{ticket_id}/.env")[0] == 404
        assert request(url + f"/reports/{ticket_id}/../../.env")[0] == 404
        assert request(url + f"/reports/{old}/data.csv")[0] == 404
        # A fresh page load reads persisted history without making new model calls.
        status, _, raw = request(url + "/api/tickets")
        assert status == 200 and json.loads(raw)[0]["id"] == ticket_id


def test_http_security_and_configuration_do_not_expose_key(tmp_path):
    with running_server(tmp_path) as (server, url):
        for path in ["/", "/static/app.js", "/static/style.css", "/api/status"]:
            status, headers, body = request(url + path)
            assert status == 200
            assert b"private-test-key" not in body
            assert headers["X-Content-Type-Options"] == "nosniff"
        assert request(url + "/.env")[0] == 404
        assert request(url + "/api/status", Host="untrusted.example")[0] == 403
        assert request(url + "/api/tickets", {"request": DEMO_REQUEST})[0] == 403
        assert (
            request(
                url + "/api/tickets",
                {"request": DEMO_REQUEST},
                server.studio.token,
                Origin="https://untrusted.example",
            )[0]
            == 403
        )
        assert server.studio.queue.list() == []


def test_progress_is_visible_and_double_submission_is_rejected(tmp_path):
    entered, release = threading.Event(), threading.Event()

    class SlowClient(FakeClient):
        def generate(self, *args, **kwargs):
            entered.set()
            release.wait(timeout=3)
            return super().generate(*args, **kwargs)

    with running_server(tmp_path, lambda key, model: SlowClient()) as (server, url):
        try:
            _, _, raw = request(
                url + "/api/tickets", {"request": DEMO_REQUEST}, server.studio.token
            )
            ticket_id = json.loads(raw)["id"]
            assert entered.wait(timeout=2)
            _, _, raw = request(url + f"/api/tickets/{ticket_id}")
            current = json.loads(raw)
            assert current["status"] == "in_progress"
            assert current["worker_active"]
            assert current["trace"][-1] == {"agent": "sql", "status": "running"}
            assert (
                request(url + "/api/tickets", {"request": DEMO_REQUEST}, server.studio.token)[0]
                == 409
            )
            assert len(server.studio.queue.list()) == 1
        finally:
            release.set()
        assert wait_ticket(server, ticket_id)["status"] == "completed"


def test_ticket_without_a_browser_worker_is_identified(tmp_path):
    with running_server(tmp_path) as (server, url):
        ticket_id = server.studio.queue.submit("Old or CLI request")
        server.studio.queue.claim(ticket_id)
        _, _, raw = request(url + f"/api/tickets/{ticket_id}")
        ticket = json.loads(raw)
        assert ticket["status"] == "in_progress"
        assert not ticket["worker_active"]


def test_missing_key_prevents_ticket_creation(tmp_path):
    with running_server(tmp_path, key="") as (server, url):
        status, _, raw = request(url + "/api/status")
        assert status == 200 and not json.loads(raw)["ready"]
        assert (
            request(url + "/api/tickets", {"request": DEMO_REQUEST}, server.studio.token)[0] == 409
        )
        assert server.studio.queue.list() == []


def test_invalid_input_and_failed_report_are_visible(tmp_path):
    with running_server(tmp_path) as (server, url):
        for value in [None, 23, ["request"]]:
            assert request(url + "/api/tickets", {"request": value}, server.studio.token)[0] == 400
        assert request(url + "/api/tickets", {"request": " "}, server.studio.token)[0] == 409
        _, _, raw = request(
            url + "/api/tickets", {"request": "unsupported fixture request"}, server.studio.token
        )
        ticket_id = json.loads(raw)["id"]
        assert wait_ticket(server, ticket_id)["status"] == "failed"
        _, _, raw = request(url + f"/api/tickets/{ticket_id}")
        assert "Offline demo supports" in json.loads(raw)["error"]
        assert request(url + f"/download/{ticket_id}/bundle.zip")[0] == 404
