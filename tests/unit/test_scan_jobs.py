"""Scan jobs for the dashboard: the live snapshot over the WebSocket and from polling, the
heartbeat, cancelling (including the scanner worker's jobs), the WebSocket origin list, the
Content-Security-Policy, and a check that the real uvicorn server accepts WebSockets at all.
No real scan runs."""

import json
import logging
import re
import socket
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosedOK
from websockets.sync.client import connect

import app.main as main
import app.scan as scan_mod
import app.scanner as scanner_mod
from app.discovery.messages import message_for
from app.discovery.models import CheckStatus, DiscoveryResult
from app.discovery.runner import Collector, run_discovery
from app.jobs import ScanBusy, ScanJob, ScanJobs
from app.scanner import ScannerError, ScannerProcess
from tests.unit.test_runner import NET, collector, o

NOW = datetime(2026, 11, 3, tzinfo=UTC)


def fake_result(mode):
    return DiscoveryResult(
        started_at=NOW, finished_at=NOW, mode=mode, network=None, devices=[], checks=[]
    )


def wait_until(condition, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


def scripted_run(seen, gate=None):
    """A stand-in for run_scan that reports progress like the real one. With a gate, it
    stops after discovery (router active) until the gate is set."""

    def run(consent, scanner, duration_seconds, online=True, *, progress, **kwargs):
        seen["consent"] = consent
        progress.step("listen", "running")
        progress.step("nearby", "running")
        progress.devices(2)
        progress.problem(message_for("npcap_missing"), "listen")
        progress.devices(4)
        progress.problem(message_for("npcap_missing"), "listen")  # the same message once
        progress.step("listen", "done")
        if consent:
            progress.step("services", "running")
            progress.step("services", "done")
        else:
            progress.step("services", "skipped", "needs_permission")
        progress.step("router", "running")
        progress.heard("nearby", {"wifi": 12})
        if gate is not None:
            gate.wait(5)
        progress.raise_if_cancelled()
        progress.step("router", "done")
        progress.problem(message_for("bluetooth_off"), "nearby")
        progress.step("nearby", "done")
        return fake_result("full" if consent else "passive")

    return run


@pytest.fixture
def client(monkeypatch):
    seen = {}
    monkeypatch.setattr(main, "run_scan", scripted_run(seen))
    monkeypatch.setattr(main, "SCAN_HEARTBEAT_SECONDS", 0.05)
    with TestClient(main.app) as c:
        c.seen = seen
        yield c


def states_for(client, job_id, **headers):
    """Every message the WebSocket sends, up to and including the final state."""
    out = []
    with client.websocket_connect(f"/api/scans/{job_id}/events", headers=headers) as ws:
        while True:
            msg = ws.receive_json()
            out.append(msg)
            if msg["type"] != "state" or msg["state"] != "running":
                return out


def statuses(snapshot):
    return {s["key"]: s["status"] for s in snapshot["steps"]}


# --- the live snapshot -------------------------------------------------------------------------


def test_websocket_sends_the_live_state_until_the_end(client):
    r = client.post("/api/scans", json={"consent": True})
    assert r.status_code == 202
    job_id = r.json()["id"]
    final = states_for(client, job_id)[-1]
    assert final["type"] == "state" and final["state"] == "done"
    assert statuses(final) == {
        "listen": "failed",  # finished, with a problem: shown as an amber notice
        "services": "done",  # a consented check asks devices which services they offer
        "router": "done",
        "nearby": "failed",
        "explain": "done",
    }
    steps = {s["key"]: s for s in final["steps"]}
    assert steps["listen"]["problems"] == [message_for("npcap_missing")]
    assert steps["nearby"]["problems"] == [message_for("bluetooth_off")]
    assert final["devices"] == 4
    assert (final["done_steps"], final["total_steps"]) == (5, 5)
    assert final["current_step"] is None and final["result"] is None  # the result comes by GET

    status = client.get(f"/api/scans/{job_id}").json()
    assert status["state"] == "done"
    assert status["result"]["mode"] == "full"
    assert status["result"]["explanations"]["ai_status"]
    assert client.seen["consent"] is True


def test_polling_during_a_scan_returns_the_real_step_states(client, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(main, "run_scan", scripted_run({}, gate))
    job_id = client.post("/api/scans", json={}).json()["id"]
    assert wait_until(lambda: client.get(f"/api/scans/{job_id}").json()["current_step"] == "router")
    live = client.get(f"/api/scans/{job_id}").json()
    assert live["state"] == "running"
    assert statuses(live) == {
        "listen": "failed",
        "services": "skipped",  # listening-only: needs permission
        "router": "active",
        "nearby": "active",
        "explain": "upcoming",
    }
    assert (live["current_step"], live["done_steps"], live["total_steps"]) == ("router", 1, 4)
    steps = {s["key"]: s for s in live["steps"]}
    assert steps["services"]["reason"] == "needs_permission"
    assert steps["listen"]["detail"] == {"devices": 4}
    assert steps["nearby"]["detail"] == {"wifi": 12}
    assert live["devices"] == 4
    assert live["elapsed_seconds"] >= 0
    started = datetime.fromisoformat(live["started_at"])
    assert started <= datetime.fromisoformat(live["last_update_at"])
    assert live["result"] is None
    gate.set()
    assert wait_until(lambda: client.get(f"/api/scans/{job_id}").json()["state"] == "done")


def test_a_dropped_websocket_loses_nothing_polling_keeps_the_step_states(client, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(main, "run_scan", scripted_run({}, gate))
    job_id = client.post("/api/scans", json={}).json()["id"]
    with client.websocket_connect(f"/api/scans/{job_id}/events") as ws:
        last = ws.receive_json()
        while statuses(last)["router"] != "active":
            last = ws.receive_json()
    # The socket is gone; the scan isn't, and polling shows exactly where it is.
    polled = client.get(f"/api/scans/{job_id}").json()
    assert statuses(polled) == statuses(last)
    assert polled["devices"] == last["devices"] == 4
    assert polled["version"] >= last["version"]
    gate.set()
    # A new connection picks up the current state, never "Not started".
    assert statuses(states_for(client, job_id)[-1])["explain"] == "done"


def test_heartbeats_keep_coming_while_a_scan_is_quiet(client, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(main, "run_scan", scripted_run({}, gate))
    job_id = client.post("/api/scans", json={}).json()["id"]
    assert wait_until(lambda: client.get(f"/api/scans/{job_id}").json()["current_step"] == "router")
    with client.websocket_connect(f"/api/scans/{job_id}/events") as ws:
        snaps = [ws.receive_json() for _ in range(4)]
    assert len({s["version"] for s in snaps}) == 1  # nothing new: these are heartbeats
    assert len({s["last_update_at"] for s in snaps}) == 1  # and heartbeats aren't updates
    gate.set()


def test_listen_only_without_consent(client):
    job_id = client.post("/api/scans", json={"consent": False}).json()["id"]
    states_for(client, job_id)
    assert client.seen["consent"] is False


def test_unknown_scan(client):
    r = client.get("/api/scans/nope")
    assert r.status_code == 404
    assert r.json()["detail"] == message_for("scan_unknown")
    assert client.post("/api/scans/nope/cancel").status_code == 404
    with client.websocket_connect("/api/scans/nope/events") as ws:
        assert ws.receive_json() == {"type": "failed", "text": message_for("scan_unknown")}
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
    assert e.value.code == main.WS_UNKNOWN_ITEM


def test_only_one_scan_at_a_time(client, monkeypatch):
    release = threading.Event()

    def slow(consent, scanner, duration_seconds, online=True, **kwargs):
        release.wait(5)
        return fake_result("passive")

    monkeypatch.setattr(main, "run_scan", slow)
    first = client.post("/api/scans", json={})
    second = client.post("/api/scans", json={})
    release.set()
    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["detail"] == message_for("scan_running")
    assert states_for(client, first.json()["id"])[-1]["state"] == "done"


def test_a_crashed_scan_says_so_in_plain_words(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret detail 192.168.1.10")

    monkeypatch.setattr(main, "run_scan", boom)
    job_id = client.post("/api/scans", json={}).json()["id"]
    final = states_for(client, job_id)[-1]
    assert (final["state"], final["error"]) == ("failed", message_for("scan_failed"))
    status = client.get(f"/api/scans/{job_id}").json()
    assert status["state"] == "failed" and status["result"] is None
    assert "secret detail" not in str(status)


def test_old_jobs_are_forgotten():
    jobs = ScanJobs(keep=2)
    ids = []
    for _ in range(3):
        job = jobs.start(lambda job: fake_result("passive"))
        assert job.wait(5)
        job.thread.join(5)
        ids.append(job.id)
    assert jobs.get(ids[0]) is None and jobs.get(ids[2]) is not None


def test_busy_registry_raises():
    jobs = ScanJobs()
    release = threading.Event()
    job = jobs.start(lambda job: (release.wait(5), fake_result("passive"))[1])
    with pytest.raises(ScanBusy):
        jobs.start(lambda job: fake_result("passive"))
    release.set()
    assert job.wait(5)


# --- cancelling --------------------------------------------------------------------------------


class BlockingScanner:
    """A scanner worker whose listening job runs until the worker is killed."""

    def __init__(self):
        self.killed = threading.Event()
        self.started = threading.Event()

    def run(self, job, params, timeout):
        self.started.set()
        self.killed.wait(10)
        raise ScannerError("scanner_unavailable")  # what a killed worker's job looks like


class FakeProcess:
    def __init__(self, scanner):
        self.scanner, self.restarts = scanner, 0

    def restart(self):
        self.restarts += 1
        self.scanner.killed.set()
        return "fresh-client"


def test_cancel_stops_the_scan_and_the_scanner_workers_jobs(client, monkeypatch):
    # The real run_scan and _run_check; only the network is replaced. Discovery waits in a
    # scanner-worker job, as the 60 s passive listen does.
    monkeypatch.setattr(main, "run_scan", scan_mod.run_scan)
    blocking = BlockingScanner()
    proc = FakeProcess(blocking)
    monkeypatch.setattr(main.app.state, "scanner", blocking)
    monkeypatch.setattr(main.app.state, "scanner_process", proc)
    monkeypatch.setattr(main.app.state, "last_result", None)
    monkeypatch.setattr(main.app.state, "locator_targets", {"keep": "me"})

    def listen(scanner, duration):
        def run(net):
            return scanner.run("passive_listen", {}, 90) or []

        return [Collector("passive_listen", "Listening for devices", active=False, run=run)]

    monkeypatch.setattr(scan_mod, "default_collectors", listen)
    real_discovery = scan_mod.run_discovery
    monkeypatch.setattr(
        scan_mod,
        "run_discovery",
        lambda mode, cols, **kw: real_discovery(mode, cols, get_network=lambda: NET, **kw),
    )
    later = []
    monkeypatch.setattr(main, "explain", lambda *a, **k: later.append("explain"))
    monkeypatch.setattr(scan_mod, "fingerprint_devices", lambda *a, **k: later.append("fp"))

    job_id = client.post(
        "/api/scans", json={"consent": True, "nearby": False, "online": False}
    ).json()["id"]
    assert blocking.started.wait(5)  # the worker's job is running
    r = client.post(f"/api/scans/{job_id}/cancel")
    assert r.status_code == 200
    assert (r.json()["state"], r.json()["error"]) == ("cancelled", message_for("scan_cancelled"))
    # The worker restarts in the background (B7), so Cancel answers at once; the job says
    # "stopping" until it has.
    job = main.app.state.scan_jobs.get(job_id)
    assert job.wait_stopped(5)
    assert proc.restarts == 1 and blocking.killed.is_set()  # the worker's job was stopped
    assert main.app.state.scanner == "fresh-client"

    job.thread.join(5)
    assert not job.thread.is_alive()  # the scan itself returned
    assert later == []  # nothing after the cancel point ran
    assert main.app.state.last_result is None  # nothing was kept
    assert main.app.state.locator_targets == {"keep": "me"}
    status = client.get(f"/api/scans/{job_id}").json()
    assert (status["state"], status["result"]) == ("cancelled", None)
    assert states_for(client, job_id)[-1]["state"] == "cancelled"
    # Cancelling again changes nothing and doesn't restart the worker twice.
    assert client.post(f"/api/scans/{job_id}/cancel").json()["state"] == "cancelled"
    assert proc.restarts == 1


def test_a_new_check_waits_until_a_cancelled_one_has_stopped(client, monkeypatch):
    release = threading.Event()

    def stubborn(consent, scanner, duration_seconds, online=True, *, progress, **kwargs):
        release.wait(5)  # e.g. a 15 s listening window that can't be interrupted
        progress.raise_if_cancelled()
        return fake_result("passive")

    monkeypatch.setattr(main, "run_scan", stubborn)
    monkeypatch.setattr(main.app.state, "scanner_process", None)
    job_id = client.post("/api/scans", json={}).json()["id"]
    assert client.post(f"/api/scans/{job_id}/cancel").json()["state"] == "cancelled"
    busy = client.post("/api/scans", json={})
    assert (busy.status_code, busy.json()["detail"]) == (409, message_for("scan_stopping"))
    release.set()
    main.app.state.scan_jobs.get(job_id).thread.join(5)
    monkeypatch.setattr(main, "run_scan", scripted_run({}))
    assert client.post("/api/scans", json={}).status_code == 202


def test_a_job_cancelled_while_finishing_drops_its_result():
    job = ScanJob("x")
    assert job.cancel()
    job.finish(fake_result("passive"))
    assert (job.state, job.result) == ("cancelled", None)
    assert not job.cancel()  # already over


def test_killing_the_worker_ends_its_children_with_a_fixed_command(monkeypatch):
    calls = []

    class Proc:
        pid = 4321

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(scanner_mod.os, "name", "nt")
    monkeypatch.setattr(scanner_mod.subprocess, "run", lambda args, **kw: calls.append((args, kw)))
    proc = ScannerProcess()
    proc._proc = Proc()
    proc.kill()
    ((args, kw),) = calls
    assert args[0].lower().endswith(r"system32\taskkill.exe")
    assert args[1:] == ["/PID", "4321", "/T", "/F"]
    assert "shell" not in kw
    assert proc.client is None


# --- the progress hooks in the existing scan code ----------------------------------------------


def test_discovery_reports_each_collector_and_the_device_count_so_far():
    calls = []
    cols = [
        collector("passive_listen", [o("arp_passive", "192.168.1.64", "00:12:34:56:78:9a")]),
        collector("mdns", ScannerError("npcap_missing")),
        collector("ssdp", [o("ssdp", "192.168.1.65", "00:12:34:56:78:9b")]),
    ]
    result = run_discovery(
        "passive",
        cols,
        get_network=lambda: NET,
        on_collector=lambda status, count: calls.append((status.name, status.status, count)),
    )
    assert sorted(c[0] for c in calls) == ["mdns", "passive_listen", "ssdp"]
    assert max(c[2] for c in calls) == len(result.devices) == 2
    assert ("mdns", "failed") in [(c[0], c[1]) for c in calls]


def test_run_scan_sends_steps_counts_and_failures_for_their_step(monkeypatch):
    def fake_discovery(mode, collectors, *, on_collector):
        failed = CheckStatus(
            name="passive_listen",
            label="Listening for devices",
            status="failed",
            reason=message_for("npcap_missing"),
        )
        on_collector(failed, 1)
        return fake_result(mode).model_copy(update={"messages": [message_for("no_network")]})

    monkeypatch.setattr(scan_mod, "run_discovery", fake_discovery)
    monkeypatch.setattr(scan_mod, "default_collectors", lambda scanner, duration: [])

    class Recorder(scan_mod.ScanProgress):
        def __init__(self):
            self.log = []

        def step(self, step, state, reason=None):
            self.log.append(("step", step, state, reason) if reason else ("step", step, state))

        def devices(self, count):
            self.log.append(("devices", count))

        def problem(self, text, step=None):
            self.log.append(("problem", step, text))

    rec = Recorder()
    scan_mod.run_scan(False, None, 10, online=False, include_nearby=False, progress=rec)
    assert rec.log == [
        ("step", "listen", "running"),
        ("step", "services", "skipped", "needs_permission"),  # from the start
        ("step", "nearby", "skipped", "not_chosen"),
        ("devices", 1),
        ("problem", "listen", message_for("npcap_missing")),
        ("devices", 0),
        ("problem", "listen", message_for("no_network")),
        ("step", "listen", "done"),
        ("step", "router", "skipped", "no_network"),
    ]


# --- task order --------------------------------------------------------------------------------


def test_tasks_are_listed_in_the_order_they_start():
    # Listening and nearby start together, so they sit next to each other.
    assert scan_mod.STEPS == ["listen", "nearby", "services", "router", "explain"]


def test_the_current_task_is_the_one_that_started_last():
    job = ScanJob("j")
    job.step("listen", "running")
    job.step("nearby", "running")
    assert job.snapshot().current_step == "nearby"
    job.step("listen", "done")
    job.step("services", "running")
    snap = job.snapshot()
    assert (snap.current_step, snap.current_index) == ("services", 3)
    job.step("services", "done")
    job.step("router", "running")
    assert job.snapshot().current_step == "router"  # nearby is still running too
    job.step("router", "done")
    assert job.snapshot().current_step == "nearby"
    assert [s.key for s in job.snapshot().steps] == scan_mod.STEPS


def test_a_real_full_check_lists_tasks_in_start_order(monkeypatch):
    """run_scan itself (with fake collectors): the order the steps start in matches STEPS."""
    started: list[str] = []

    class Recorder(scan_mod.ScanProgress):
        def step(self, step, state, reason=None):
            if state != "done" and step not in started:
                started.append(step)

    monkeypatch.setattr(scan_mod, "run_discovery", lambda *a, **k: fake_result("full"))
    monkeypatch.setattr(scan_mod, "default_collectors", lambda *a: [])
    survey = scan_mod.NearbySurvey()
    scan_mod.run_scan(True, None, 1, nearby_fn=lambda: (survey, [], []), progress=Recorder())
    # No network in this fake, so services and router are skipped (no_network), in order.
    assert started == ["listen", "nearby", "services", "router"]


# --- the real server accepts WebSockets (the 3 Nov "connection lost" bug) ----------------------


def test_the_real_uvicorn_server_accepts_the_progress_websocket():
    """TestClient talks to the app directly, so it never noticed that uvicorn had no WebSocket
    library and answered every upgrade with 404. This goes through a real uvicorn server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(main.app, host="127.0.0.1", port=port, lifespan="off", log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        assert wait_until(lambda: server.started)
        with connect(f"ws://127.0.0.1:{port}/api/scans/nope/events", open_timeout=5) as ws:
            assert '"failed"' in ws.recv(timeout=5)
    finally:
        server.should_exit = True
        thread.join(5)


# --- WebSocket origins and the Content-Security-Policy -----------------------------------------


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:8765",
        "http://127.0.0.1:5173",
        "http://localhost:8765",  # the same dashboard, opened as localhost
        "http://localhost:5173",
    ],
)
def test_scan_events_accept_the_production_and_dev_origins(client, origin):
    job_id = client.post("/api/scans", json={}).json()["id"]
    assert states_for(client, job_id, origin=origin)[-1]["state"] == "done"


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "http://127.0.0.1:9999",  # another local page
        "http://localhost:9999",
        "http://localhost",
        "http://127.0.0.1",
        "https://127.0.0.1:8765",
        "null",
    ],
)
@pytest.mark.parametrize("path", ["/api/scans/x/events", "/api/nearby/locate/bluetooth:abc"])
def test_every_other_origin_is_refused(client, origin, path):
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(path, headers={"origin": origin}) as ws:
            ws.receive_json()
    assert e.value.code == main.WS_BAD_ORIGIN


def test_allowed_origins_are_exactly_production_and_dev():
    assert main.ALLOWED_ORIGINS == {
        "http://127.0.0.1:8765",
        "http://127.0.0.1:5173",
        "http://localhost:8765",
        "http://localhost:5173",
    }


def test_a_refused_origin_is_logged_with_the_address_to_use(client, caplog):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/api/scans/x/events", headers={"origin": "http://127.0.0.1:9999"}
        ) as ws:
            ws.receive_json()
    assert "refused a live connection from a page at http://127.0.0.1:9999" in caplog.text
    assert "open RoomCheck at http://127.0.0.1:8765" in caplog.text


def test_content_security_policy_allows_only_self_and_the_local_websocket(client):
    for path in ("/api/health", "/", "/api/scans/nope"):
        csp = client.get(path).headers["content-security-policy"]
        directives = dict(d.strip().split(" ", 1) for d in csp.split(";"))
        assert directives["default-src"] == "'self'"
        assert directives["connect-src"] == "'self' ws://127.0.0.1:8765"
        assert directives["object-src"] == "'none'"
        assert directives["frame-ancestors"] == "'none'"
        for name, value in directives.items():
            sources = value.split()
            if name == "connect-src":
                sources.remove("ws://127.0.0.1:8765")
            assert set(sources) <= {"'self'", "'none'"}, (name, value)
        assert "unsafe" not in csp
        assert not re.search(r"https?://", csp)


# --- FastAPI serves the built dashboard itself (one origin) -----------------------------------


def test_the_dashboard_is_served_from_the_same_origin_with_the_csp(client):
    r = client.get("/")
    assert r.headers["content-security-policy"] == main.CONTENT_SECURITY_POLICY
    if not main.WEB_DIST.is_dir():
        assert "npm --prefix web run build" in r.text  # says how to build it
        return
    assert r.headers["content-type"].startswith("text/html")
    html = r.text
    # Bundled scripts and styles from this server only; nothing inline, nothing remote.
    assert "<script>" not in html and "style=" not in html
    assert not re.search(r"(src|href)=\"(https?:)?//", html)
    asset = re.search(r"src=\"(/assets/[^\"]+\.js)\"", html).group(1)
    js = client.get(asset)
    assert js.status_code == 200 and "content-security-policy" in js.headers
    assert client.get("/api/health").json()["ok"] is True  # /api isn't shadowed


# --- the services task, live details and skip reasons (Scanning screen refinements) ----------


def test_heard_counts_are_recorded_only_when_a_number_changes():
    job = ScanJob("x")
    job.heard("nearby", {"wifi": 3})
    v = job.version
    job.heard("nearby", {"wifi": 3})  # the same numbers: no update
    assert job.version == v
    job.heard("nearby", {"wifi": 3, "bluetooth": 2})
    assert job.version == v + 1
    snap = job.snapshot()
    assert {s.key: s.detail for s in snap.steps}["nearby"] == {"wifi": 3, "bluetooth": 2}


def test_total_and_done_tasks_leave_skipped_ones_out():
    job = ScanJob("x")
    job.step("listen", "running")
    job.step("nearby", "running")
    job.step("services", "skipped", "needs_permission")
    snap = job.snapshot()
    assert (snap.done_steps, snap.total_steps) == (0, 4)
    job.step("listen", "done")
    assert (job.snapshot().done_steps, job.snapshot().total_steps) == (1, 4)


def test_run_scan_reports_the_services_task_and_nearby_counts(monkeypatch):
    calls = []

    class Recorder(scan_mod.ScanProgress):
        def step(self, step, state, reason=None):
            calls.append((step, state, reason))

        def heard(self, step, counts):
            calls.append(("heard", step, dict(counts)))

    def fake_discovery(mode, collectors, *, on_collector):
        return fake_result(mode).model_copy(update={"network": NET})

    monkeypatch.setattr(scan_mod, "run_discovery", fake_discovery)
    monkeypatch.setattr(scan_mod, "default_collectors", lambda scanner, duration: [])
    monkeypatch.setattr(scan_mod, "fingerprint_devices", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan_mod, "run_network_checks", lambda *a, **k: (None, [], []))

    def wifi():
        from app.wireless.ie import make_security
        from app.wireless.models import BssReading

        reading = BssReading(
            bssid="02:00:00:00:00:01", ssid="Example", rssi_dbm=-50, security=make_security("wpa2")
        )
        return "wlanapi", [[reading], [reading]]

    import app.wireless.survey as survey_mod

    real_collect = survey_mod.collect_nearby
    monkeypatch.setattr(
        survey_mod,
        "collect_nearby",
        lambda **kw: real_collect(wifi_fn=wifi, ble_fn=lambda: [], **kw),
    )
    import app.checks.wifi as wifi_mod

    monkeypatch.setattr(wifi_mod, "connected_wifi", lambda: None)
    scan_mod.run_scan(False, None, 10, online=False, progress=Recorder())
    assert ("services", "skipped", "needs_permission") in calls
    assert ("router", "running", None) in calls
    assert ("heard", "nearby", {"wifi": 1}) in calls  # one distinct network, from real data
    calls.clear()
    scan_mod.run_scan(True, None, 10, online=False, progress=Recorder())
    assert [c for c in calls if c[0] == "services"] == [
        ("services", "running", None),
        ("services", "done", None),
    ]


def test_health_says_which_version_and_whether_the_code_changed_since_start(monkeypatch):
    from datetime import timedelta

    import app.version as version_mod

    with TestClient(main.app) as c:
        h = c.get("/api/health").json()
        assert h["version"] == version_mod.version() and h["stale"] is False
        started = main.app.state.code_time
        monkeypatch.setattr(version_mod, "code_time", lambda: started + timedelta(minutes=5))
        assert c.get("/api/health").json()["stale"] is True


def test_startup_line_names_version_code_and_dashboard_times():
    import app.version as version_mod

    line = version_mod.startup_line(version_mod.code_time())
    assert line.startswith(f"RoomCheck {version_mod.version()} | code from ")
    assert " | dashboard built " in line


@contextmanager
def real_server():
    """The app behind a real uvicorn server on a free port, as the browser reaches it."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(main.app, host="127.0.0.1", port=port, lifespan="off", log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        assert wait_until(lambda: server.started)
        yield port
    finally:
        server.should_exit = True
        thread.join(5)


def start_check(port, consent):
    r = httpx.post(f"http://127.0.0.1:{port}/api/scans", json={"consent": consent}, timeout=5)
    return r.json()["id"]


@pytest.mark.parametrize("consent", [True, False])
def test_a_check_stays_connected_through_the_real_server(monkeypatch, consent):
    """A full check (with permission) and a listening-only one, followed over a real uvicorn
    WebSocket from the dashboard's own origin: heartbeats while it's quiet, every change, then
    a normal close after the final state. Never closed early."""
    gate = threading.Event()
    monkeypatch.setattr(main, "run_scan", scripted_run({}, gate))
    monkeypatch.setattr(main, "SCAN_HEARTBEAT_SECONDS", 0.1)
    try:
        with real_server() as port:
            job_id = start_check(port, consent)
            messages = []
            with connect(
                f"ws://127.0.0.1:{port}/api/scans/{job_id}/events",
                open_timeout=5,
                additional_headers={"Origin": main.PRODUCTION_ORIGIN},
            ) as ws:
                threading.Timer(0.6, gate.set).start()  # a quiet stretch first
                try:
                    while True:
                        messages.append(json.loads(ws.recv(timeout=5)))
                except ConnectionClosedOK:
                    pass
                assert ws.close_code == 1000
    finally:
        gate.set()
    assert messages[-1]["state"] == "done"
    router = [
        m for m in messages if m["state"] == "running" and m["steps"][3]["status"] == "active"
    ]
    assert len(router) >= 3  # heartbeats kept coming while nothing changed
    assert [st["key"] for st in messages[0]["steps"]] == scan_mod.STEPS
    services = {m["steps"][2]["status"] for m in messages}
    assert ("done" in services) if consent else (services == {"skipped"})


def test_a_live_connection_closed_mid_check_is_logged(monkeypatch, caplog):
    """So a dropped live connection can be traced from the terminal: which check, the close
    code and when. The check itself carries on."""
    caplog.set_level(logging.INFO, logger="app.main")
    gate = threading.Event()
    monkeypatch.setattr(main, "run_scan", scripted_run({}, gate))
    monkeypatch.setattr(main, "SCAN_HEARTBEAT_SECONDS", 0.05)
    try:
        with real_server() as port:
            job_id = start_check(port, True)
            with connect(f"ws://127.0.0.1:{port}/api/scans/{job_id}/events", open_timeout=5) as ws:
                assert json.loads(ws.recv(timeout=5))["state"] == "running"
            assert wait_until(lambda: "live connection closed by the page" in caplog.text)
            assert main.app.state.scan_jobs.get(job_id).state == "running"
    finally:
        gate.set()
    # The server sees the close when its next heartbeat can't be sent, so the code varies.
    assert re.search(
        rf"check {job_id}: live connection closed by the page \(code \d+\) at \d+ s", caplog.text
    )


def test_a_known_issues_lookup_note_goes_under_the_services_step_not_the_router(monkeypatch):
    # The lookup is about the devices' models and needs permission, as the services step does.
    from app.checks.models import NetworkFacts

    monkeypatch.setattr(
        scan_mod,
        "run_discovery",
        lambda mode, collectors, *, on_collector: fake_result(mode).model_copy(
            update={"network": NET}
        ),
    )
    monkeypatch.setattr(scan_mod, "default_collectors", lambda scanner, duration: [])
    monkeypatch.setattr(scan_mod, "fingerprint_devices", lambda *a, **k: ([], []))
    upnp = CheckStatus(name="upnp", label="UPnP", status="failed", reason="UPnP didn't answer.")
    cve = CheckStatus(
        name="cve", label="Known issues", status="skipped", reason=message_for("nvd_unavailable")
    )
    monkeypatch.setattr(
        scan_mod, "run_network_checks", lambda *a, **k: (NetworkFacts(), [upnp, cve], [])
    )
    job = ScanJob("j")
    scan_mod.run_scan(True, None, 10, include_nearby=False, progress=job)
    steps = {s.key: s for s in job.snapshot().steps}
    assert steps["services"].problems == [message_for("nvd_unavailable")]
    # The services step had finished; the lookup's note goes under it and it stays Done.
    assert steps["services"].status == "done"
    assert steps["router"].problems == ["UPnP didn't answer."]
