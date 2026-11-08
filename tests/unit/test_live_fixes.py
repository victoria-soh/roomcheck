"""Fixes for the bugs found in the live tests of 4 Nov 2026 (docs/bugs-from-live-tests.md).
One section per bug. No real network, scanner worker or API call is used."""

from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
from scapy.layers.l2 import ARP, Ether

import app.checks.wifi as wifi_mod
import app.main as main
import app.scan as scan_mod
from app.discovery import netinfo
from app.discovery import runner as runner_mod
from app.discovery.messages import message_for
from app.discovery.models import NetworkInfo
from app.explain.models import LandlordMessage
from app.explain.service import explain
from app.explain.validator import (
    check_landlord_message,
    hedge_camera,
    problem_with_text,
    template_problem,
)
from app.handover import tasks as task_rules
from app.handover.models import Task
from app.report import render, tamper
from app.rules.engine import load_rules
from app.scanner import ScannerClient, ScannerError
from app.setup_check import connected_network
from scannerd.jobs import arp as arp_job
from scannerd.server import Job, Server
from tests.unit.test_explain import WITH_KEY
from tests.unit.test_explain import room as explain_room
from tests.unit.test_report import SAMPLE_PDF
from tests.unit.test_report import scan_result as report_scan_result

# --- B10: rejoining Wi-Fi with a new address works without a restart ---------------------------


class FakeRoutes:
    """Stands in for scapy's conf.route: route() answers from the table read at the last
    resync(), like scapy's, so a stale table keeps the old address until it's re-read."""

    def __init__(self, live: tuple[str, str, str]) -> None:
        self.live = live  # what Windows says now
        self.table = live  # what scapy last read
        self.resyncs = 0

    def resync(self) -> None:
        self.resyncs += 1
        self.table = self.live

    def route(self, dst: str) -> tuple[str, str, str]:
        return self.table


@pytest.fixture
def routes(monkeypatch):
    import scapy.route  # noqa: F401 - populates conf.route
    from scapy.config import conf

    fake = FakeRoutes(("wifi0", "192.0.2.52", "192.0.2.1"))
    reloads = []
    monkeypatch.setattr(conf, "route", fake)
    monkeypatch.setattr(conf.ifaces, "reload", lambda: reloads.append(1))
    fake.reloads = reloads
    return fake


def test_default_route_rereads_after_the_address_changes(routes):
    assert netinfo.default_route()[1] == "192.0.2.52"
    routes.live = ("wifi0", "192.0.2.62", "192.0.2.1")  # the laptop rejoined
    assert netinfo.default_route()[1] == "192.0.2.62"
    assert routes.resyncs == 2 and len(routes.reloads) == 2  # read fresh on every call


def test_disconnect_then_rejoin_is_seen_each_time(routes):
    routes.live = ("wifi0", "0.0.0.0", "0.0.0.0")
    with pytest.raises(netinfo.NoNetworkError):
        netinfo.default_route()
    routes.live = ("wifi0", "192.0.2.62", "192.0.2.1")
    assert netinfo.default_route()[1:] == ("192.0.2.62", "192.0.2.1")


def test_network_info_and_setup_follow_the_new_address(routes, monkeypatch):
    seen = []

    def find_interface(ip):
        seen.append(ip)
        return "Wi-Fi", "255.255.255.0", "aa:bb:cc:00:00:01"

    monkeypatch.setattr(netinfo, "_find_interface", find_interface)
    monkeypatch.setattr(
        wifi_mod, "connected_wifi", lambda: type("W", (), {"ssid": "Example-Home"})()
    )
    assert netinfo.get_network_info().own_ip == "192.0.2.52"
    routes.live = ("wifi0", "0.0.0.0", "0.0.0.0")
    assert connected_network().kind == "none"
    routes.live = ("wifi0", "192.0.2.62", "192.0.2.1")
    assert connected_network().kind == "wifi"  # /api/setup's answer, without a restart
    info = netinfo.get_network_info()  # what the next check starts from
    assert (info.own_ip, info.cidr) == ("192.0.2.62", "192.0.2.0/24")
    assert seen[-1] == "192.0.2.62"


# --- B5: the sweep ends by its own budget; the app waits longer than that -----------------------

SLASH22 = NetworkInfo(
    interface="Wi-Fi",
    own_ip="192.168.1.10",
    own_mac="00:00:00:00:00:10",
    gateway_ip="192.168.1.1",
    netmask="255.255.252.0",
    cidr="192.168.0.0/22",
    prefixlen=22,
    sweep_allowed=True,
)
# A /22 is needed (no documentation range is that big): made-up hosts across it.
LIVE_HOSTS = ["192.168.0.1", "192.168.1.1", "192.168.1.20", "192.168.2.30", "192.168.3.200"]


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def fake_worker_network(monkeypatch, clock, seconds_per_batch):
    """The sweep job's network side: a /22 where LIVE_HOSTS answer, and sending a batch of
    requests takes seconds_per_batch (slow, as from Python on Windows)."""
    listener = {}
    sent = []

    class Stop:
        def stop(self):
            listener["stopped"] = True

    def listen(iface, on_packet):
        listener["on_packet"] = on_packet
        return Stop()

    def send(packets, iface):
        clock.t += seconds_per_batch
        targets = [p[ARP].pdst for p in packets]
        sent.extend(targets)
        for ip in targets:
            if ip in LIVE_HOSTS:
                mac = "aa:bb:cc:00:00:01"
                listener["on_packet"](Ether(src=mac) / ARP(op=2, psrc=ip, hwsrc=mac))

    route = ("wifi0", SLASH22.own_ip, SLASH22.gateway_ip)
    monkeypatch.setattr(arp_job, "require_pcap", lambda: None)
    monkeypatch.setattr(arp_job, "default_route", lambda: route)
    monkeypatch.setattr(arp_job, "get_network_info", lambda: SLASH22)
    monkeypatch.setattr(arp_job, "_listen", listen)
    monkeypatch.setattr(arp_job, "_send", send)
    return sent, listener


def test_a_normal_sweep_runs_both_passes_within_its_budget(monkeypatch):
    clock = FakeClock()
    sent, listener = fake_worker_network(monkeypatch, clock, seconds_per_batch=0.2)
    params = arp_job.ArpSweepParams(gap_seconds=20, budget_seconds=60)
    out = arp_job.arp_sweep(params, clock=clock, sleep=clock.sleep)
    assert sorted(o["ip"] for o in out) == sorted(LIVE_HOSTS)
    assert len(sent) == 2 * 1021  # every address but our own, twice
    assert clock.t <= 60 and listener["stopped"]


def test_a_slow_sweep_stops_at_its_budget_and_keeps_what_it_heard(monkeypatch):
    clock = FakeClock()
    sent, listener = fake_worker_network(monkeypatch, clock, seconds_per_batch=8.0)
    params = arp_job.ArpSweepParams(gap_seconds=20, budget_seconds=45)
    out = arp_job.arp_sweep(params, clock=clock, sleep=clock.sleep)
    assert clock.t <= 45 + 8.0  # at most one batch past the budget
    assert len(sent) < 1021  # it didn't finish even one pass...
    assert {o["ip"] for o in out} == {ip for ip in LIVE_HOSTS if ip in sent}  # ...but kept replies
    assert out and listener["stopped"]


def test_sweep_budget_fits_inside_the_listening_window():
    for duration in (10, 30, 60, 120):
        gap = min(20.0, max(0.0, duration - 5))
        budget = runner_mod.sweep_budget(duration, gap)
        assert 5 <= budget <= 90 and budget >= gap + 25
        arp_job.ArpSweepParams(gap_seconds=gap, budget_seconds=budget)  # the worker accepts it


class SweepingScanner:
    """Plays the scanner worker on the dashboard path: arp_sweep runs the real job function
    (with a slow fake network), the other jobs answer at once. Records how long the worker
    took against how long the app was willing to wait."""

    def __init__(self, monkeypatch, seconds_per_batch):
        self.clock = FakeClock()
        fake_worker_network(monkeypatch, self.clock, seconds_per_batch)
        self.sweeps = []
        self.abandoned = False

    def run(self, job, params, timeout):
        if job != "arp_sweep":
            return []
        start = self.clock.t
        out = arp_job.arp_sweep(
            arp_job.ArpSweepParams(**params), clock=self.clock, sleep=self.clock.sleep
        )
        took = self.clock.t - start
        self.sweeps.append((took, timeout))
        if took > timeout:  # what the real client does when the worker is slower than its wait
            raise ScannerError("timeout")
        return out


@pytest.mark.parametrize("seconds_per_batch", [0.5, 4.0])
def test_dashboard_check_keeps_the_sweep_even_when_it_is_slow(monkeypatch, seconds_per_batch):
    """The dashboard path: POST /api/scans → the job thread → _run_check → run_scan →
    default_collectors → the scanner worker's arp_sweep. On 4 Nov a slow sweep outlasted the
    app's 50 s wait, so the whole sweep was thrown away. Now the worker stops at its budget
    and the app waits for it, so the step always reports what the sweep heard."""
    scanner = SweepingScanner(monkeypatch, seconds_per_batch)
    real_discovery = scan_mod.run_discovery
    monkeypatch.setattr(
        scan_mod,
        "run_discovery",
        lambda mode, cols, **kw: real_discovery(
            mode, [c for c in cols if c.name == "arp_sweep"], get_network=lambda: SLASH22, **kw
        ),
    )
    monkeypatch.setattr(scan_mod, "fingerprint_devices", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan_mod, "run_network_checks", lambda *a, **k: (None, [], []))
    monkeypatch.setattr(main, "explain", lambda *a, **k: None)
    with TestClient(main.app) as c:
        monkeypatch.setattr(main.app.state, "scanner", scanner)
        monkeypatch.setattr(main.app.state, "scanner_process", None)
        job_id = c.post(
            "/api/scans", json={"consent": True, "nearby": False, "online": False}
        ).json()["id"]
        job = main.app.state.scan_jobs.get(job_id)
        assert job.wait(10)
        result = c.get(f"/api/scans/{job_id}").json()["result"]
    sweep = next(ch for ch in result["checks"] if ch["name"] == "arp_sweep")
    assert sweep["status"] == "ran", sweep  # not "This step took too long and was stopped"
    assert sweep["found"] >= 1
    ((took, waited),) = scanner.sweeps
    assert took < waited  # the worker always answers before the app stops waiting


# --- B6: a check right after another; the admin advice only when it's the cause -----------------


def test_only_a_scanner_that_never_started_gets_the_admin_advice():
    assert "administrator" in message_for("scanner_not_started")
    assert "administrator" in message_for("permission")  # a real permission error
    assert "administrator" not in message_for("scanner_unavailable")
    assert message_for("scan_preparing") == "Finishing the previous check…"


class NoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


def test_a_client_that_stops_waiting_marks_the_worker_as_left_busy():
    key = secrets.token_bytes(32)
    release = threading.Event()
    srv = Server(key, {"slow": Job(NoParams, lambda p: release.wait(5) and [])})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        client = ScannerClient(srv.address[1], key)
        assert not client.abandoned
        with pytest.raises(ScannerError) as e:
            client.run("slow", {}, timeout=0.2)
        assert e.value.code == "timeout" and client.abandoned
    finally:
        release.set()
        srv.stop()


class FakeWorkerProcess:
    def __init__(self, restart_seconds=0.0, alive=True):
        self.restarts = 0
        self.restart_seconds = restart_seconds
        self._alive = alive

    def alive(self):
        return self._alive

    def restart(self):
        time.sleep(self.restart_seconds)
        self.restarts += 1
        self._alive = True
        return type("Client", (), {"abandoned": False})()


class Recorder(scan_mod.ScanProgress):
    def __init__(self):
        self.seen = []

    def preparing(self, on):
        self.seen.append(on)


@pytest.mark.parametrize(
    ("abandoned", "alive", "restarts"),
    [(False, True, 0), (True, True, 1), (False, False, 1)],
)
def test_a_new_check_restarts_a_worker_left_busy_or_stopped(abandoned, alive, restarts):
    class State:
        scanner = type("C", (), {"abandoned": abandoned})()
        scanner_process = FakeWorkerProcess(alive=alive)

    state, progress = State(), Recorder()
    got = main._scanner_for_check(state, progress)
    assert state.scanner_process.restarts == restarts
    assert progress.seen == ([True, False] if restarts else [])  # "Finishing the previous check…"
    assert got is state.scanner


# --- B7: Cancel takes effect within about 3 s ---------------------------------------------------


def test_run_scan_returns_quickly_when_cancelled_mid_stage(monkeypatch):
    """Discovery and the nearby survey both block for 30 s; a cancel still ends run_scan in
    well under a second."""
    hold = threading.Event()
    monkeypatch.setattr(scan_mod, "run_discovery", lambda *a, **k: hold.wait(30))

    class Job(scan_mod.ScanProgress):
        def __init__(self):
            self.cancelled = threading.Event()

        def raise_if_cancelled(self):
            if self.cancelled.is_set():
                raise scan_mod.ScanCancelled

    job = Job()
    threading.Timer(0.3, job.cancelled.set).start()
    start = time.monotonic()
    try:
        with pytest.raises(scan_mod.ScanCancelled):
            scan_mod.run_scan(True, None, 60, nearby_fn=lambda: hold.wait(30), progress=job)
        assert time.monotonic() - start < 1.5
    finally:
        hold.set()


def stuck_scan(hold):
    def run(consent, scanner, duration_seconds, online=True, *, progress, **kwargs):
        while not hold.wait(0.05):
            progress.raise_if_cancelled()

    return run


def test_cancel_says_stopping_until_the_worker_restarted_then_a_new_check_can_start(monkeypatch):
    hold = threading.Event()
    monkeypatch.setattr(main, "run_scan", stuck_scan(hold))
    with TestClient(main.app) as c:
        proc = FakeWorkerProcess(restart_seconds=0.8)
        monkeypatch.setattr(main.app.state, "scanner_process", proc)
        monkeypatch.setattr(main.app.state, "scanner", type("C", (), {"abandoned": False})())
        job_id = c.post("/api/scans", json={}).json()["id"]
        start = time.monotonic()
        snap = c.post(f"/api/scans/{job_id}/cancel").json()
        assert snap["state"] == "cancelled" and snap["stopping"]  # the page shows "Stopping…"
        assert time.monotonic() - start < 0.5  # Cancel answers at once
        busy = c.post("/api/scans", json={})
        assert (busy.status_code, busy.json()["detail"]) == (409, message_for("scan_stopping"))
        job = main.app.state.scan_jobs.get(job_id)
        assert job.wait_stopped(3)
        assert time.monotonic() - start < 3  # stopped within about 3 s
        assert proc.restarts == 1
        assert c.get(f"/api/scans/{job_id}").json()["stopping"] is False
        hold.set()
        monkeypatch.setattr(main, "run_scan", lambda *a, **k: None)
        assert c.post("/api/scans", json={}).status_code == 202  # straight away


def test_the_live_connection_stays_open_until_the_check_has_stopped(monkeypatch):
    hold = threading.Event()
    monkeypatch.setattr(main, "run_scan", stuck_scan(hold))
    monkeypatch.setattr(main, "SCAN_HEARTBEAT_SECONDS", 0.05)
    with TestClient(main.app) as c:
        proc = FakeWorkerProcess(restart_seconds=0.5)
        monkeypatch.setattr(main.app.state, "scanner_process", proc)
        monkeypatch.setattr(main.app.state, "scanner", type("C", (), {"abandoned": False})())
        job_id = c.post("/api/scans", json={}).json()["id"]
        c.post(f"/api/scans/{job_id}/cancel")
        seen = []
        with c.websocket_connect(f"/api/scans/{job_id}/events") as ws:
            while True:
                msg = ws.receive_json()
                seen.append((msg["state"], msg["stopping"]))
                if msg["state"] != "running" and not msg["stopping"]:
                    break
        hold.set()
    assert ("cancelled", True) in seen and seen[-1] == ("cancelled", False)


# --- B11: the host message covers exactly the ticked open tasks --------------------------------


def make_task(rule_id, ask, *, status="todo", host_confirmed=False, who="landlord_or_host"):
    return Task(
        id=f"{rule_id}|subject",
        finding_id=f"{rule_id}:finding",
        rule_id=rule_id,
        subject="subject",
        severity="Medium",
        finding_title=rule_id,
        title=rule_id,
        ask=ask,
        who=who,
        steps=[],
        status=status,
        host_confirmed=host_confirmed,
    )


WPS_ASK = "The Wi-Fi router advertises WPS. Could you turn it off in the router's settings?"
CAM_ASK = "Could you tell me what the device on the Wi-Fi that looks like a camera is?"
# The AI draft from 4 Nov, written for every finding before the camera was marked "Mine".
DRAFT_4_NOV = (
    "Hello, during a Wi-Fi check of the room we found a device on the network that may be a "
    "camera, and our Wi-Fi router advertises WPS. Could you confirm what this device is? Could "
    "you also confirm whether WPS PIN mode is turned off, and whether the router and camera "
    "firmware are up to date? Thank you."
)


def ai_draft(text, covers):
    return LandlordMessage(text=text, source="ai", label="AI", covers=covers)


def test_a_device_marked_mine_is_never_in_the_message():
    """The 4 Nov case: the camera was answered Mine, so only the WPS task is open, but the AI
    draft still asked about the camera. Now it falls back to the numbered template."""
    wps = make_task("R-WPS", WPS_ASK)
    msg = task_rules.bundle_message([wps], ai_draft(DRAFT_4_NOV, ["R-CAM:finding", wps.finding_id]))
    assert msg.source == "standard" and msg.covers == [wps.finding_id]
    assert "camera" not in msg.text.lower() and "1. The Wi-Fi router advertises WPS." in msg.text


def test_resolved_and_host_confirmed_tasks_are_left_out():
    tasks = [
        make_task("R-CAM", CAM_ASK, status="resolved"),
        make_task("R-UPNP", "Could UPnP be switched off?", host_confirmed=True),
        make_task("R-WPS", WPS_ASK),
    ]
    msg = task_rules.bundle_message(tasks, None)
    assert msg.text.count("\n1. ") == 1 and "2. " not in msg.text
    assert "UPnP" not in msg.text and "camera" not in msg.text


@pytest.mark.parametrize(
    ("text", "used"),
    [
        ("Hello, I noticed the router advertises WPS. Could you turn WPS off?", True),
        ("Hello, we noticed the router advertises WPS. Could you turn WPS off?", False),  # we
        ("Hello, our router advertises WPS. Could you turn WPS off?", False),  # our
        ("Hello, the router advertises WPS. Is its firmware up to date?", False),  # not a task
        ("Hello, the router advertises WPS and there's a camera. Could you check?", False),
    ],
)
def test_an_ai_draft_is_used_only_if_it_mentions_nothing_outside_the_tasks(text, used):
    wps = make_task("R-WPS", WPS_ASK)
    draft = ai_draft(text, [wps.finding_id])
    assert (task_rules.bundle_message([wps], draft) is draft) is used


def test_an_ai_draft_written_for_other_tasks_is_not_used():
    wps, cam = make_task("R-WPS", WPS_ASK), make_task("R-CAM", CAM_ASK)
    draft = ai_draft("Hello, I noticed the router advertises WPS. Could you turn it off?", ["x"])
    assert task_rules.bundle_message([wps], draft).source == "standard"
    both = ai_draft(
        "Hello, I noticed a device that may be a camera, and the router advertises WPS. "
        "Could you tell me what the device is, and turn WPS off?",
        [wps.finding_id, cam.finding_id],
    )
    assert task_rules.bundle_message([wps, cam], both) is both
    assert task_rules.bundle_message([wps], both).source == "standard"  # camera since dropped


def test_explain_rejects_an_ai_message_about_findings_it_does_not_cover():
    findings, devices, nearby = explain_room()

    def call(settings, payload):
        assert all("in_message" in p for p in payload)
        return {
            "explanations": [],
            "landlord_message": "Hello, I noticed the router advertises WPS. Could you check?",
        }

    out = explain(findings, devices, nearby, settings=WITH_KEY, call=call)
    assert out.ai_rejected.get("landlord_message") == "mentions_excluded"
    assert out.landlord_message.source == "standard"
    assert set(out.landlord_message.covers) == {
        f.id for f in findings if f.severity in ("High", "Medium") and f.landlord_question
    }


# --- B1: an unconfirmed camera is "the device that may be a camera" ----------------------------


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("Hello, could you tell me what the camera device is?", "camera_overclaim"),
        ("Hello, could you tell me where the camera is?", "camera_overclaim"),
        ("Hello, is this camera recording?", "camera_overclaim"),
        ("Hello, could you tell me what the device that may be a camera is?", None),
        ("Hello, I saw a camera-like device. Could you tell me what it is?", None),
        ("Hello, I saw a camera's setup network. Is it yours?", None),
    ],
)
def test_the_message_never_states_an_unconfirmed_camera(text, problem):
    assert check_landlord_message(text) == problem


def test_a_confirmed_camera_may_be_called_the_camera():
    assert check_landlord_message("Hello, where is the camera?", camera_confirmed=True) is None


def test_ai_explanations_for_camera_findings_never_say_the_camera():
    text = "The camera on this network could record you. Do you recognise it?"
    assert problem_with_text(text, "High", "R-CAM") == "camera_overclaim"
    assert problem_with_text(text.replace("The camera", "A device"), "High", "R-CAM") is None


def test_the_templates_pass_the_message_rules():
    """The template guard: every fixed question a message can contain is first person and
    never calls an unconfirmed camera "the camera"."""
    rules = yaml.safe_load(Path("app/rules/rules.yaml").read_text(encoding="utf-8"))
    questions = [r["landlord_question"] for r in rules["rules"] if r.get("landlord_question")]
    asks = [t.ask for t in task_rules.load_templates().templates.values()]
    assert questions and asks
    for text in questions + asks:
        assert template_problem(text) is None, text
    assert hedge_camera("Could you tell me what the camera device is?") == (
        "Could you tell me what the device that may be a camera is?"
    )


def test_the_standard_messages_hedge_a_camera_even_if_a_template_does_not(monkeypatch):
    wps = make_task("R-CAM", "Could you tell me where the camera is?")
    msg = task_rules.bundle_message([wps], None)
    assert "the device that may be a camera" in msg.text and "the camera is" not in msg.text


# --- B9: a report made offline says the timestamp is unavailable, quickly ---------------------


def test_no_network_fails_the_timestamp_at_once_with_its_reason(monkeypatch):
    monkeypatch.setattr(tamper, "has_network", lambda: False)
    start = time.monotonic()
    with pytest.raises(tamper.TimestampUnavailable) as e:
        tamper.request_token(b"\x00" * 32, tamper.FREETSA_URL)
    assert e.value.args[0] == "no_network" and time.monotonic() - start < 0.5


def test_a_timestamp_service_that_never_answers_is_given_up_on_time():
    """The HTTP timeout doesn't cover looking up the name, which Windows can retry for a
    minute while the network changes. The whole request now has one deadline."""
    hold = threading.Event()

    class Hangs:
        def __init__(self, *a, **k):
            pass

        def __call__(self, **kwargs):
            hold.wait(30)

    start = time.monotonic()
    try:
        with pytest.raises(tamper.TimestampUnavailable) as e:
            tamper.request_token(
                b"\x00" * 32, tamper.FREETSA_URL, timestamper_factory=Hangs, timeout=0.5
            )
        assert e.value.args[0] == "timeout" and time.monotonic() - start < 1.5
    finally:
        hold.set()


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("no_network", tamper.NO_NETWORK_MESSAGE),
        ("timeout", tamper.TIMEOUT_MESSAGE),
        ("ConnectionError", tamper.OFFLINE_MESSAGE),
    ],
)
def test_the_report_says_why_there_is_no_timestamp(tmp_path, code, message):
    def unavailable(digest, url):
        raise tamper.TimestampUnavailable(code)

    files = tamper.save(SAMPLE_PDF, tmp_path, "r", request=unavailable)
    assert files.tsr is None and files.timestamp_message == message


def test_the_report_endpoint_answers_quickly_offline_with_unavailable_and_the_reason(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(tamper, "has_network", lambda: False)
    monkeypatch.setattr(render, "render_pdf", lambda html: SAMPLE_PDF)
    with TestClient(main.app) as c:
        monkeypatch.setattr(main.app.state, "last_result", report_scan_result(), raising=False)
        monkeypatch.setattr(main.app.state, "report_dir", tmp_path, raising=False)
        start = time.monotonic()
        r = c.post("/api/report", json={"timestamp": True, "ai": False})
        took = time.monotonic() - start
    assert r.status_code == 200 and took < 5
    body = r.json()
    assert body["tsr"] is None and body["timestamped_at"] is None
    assert body["timestamp"] == {"state": "unavailable", "reason": tamper.NO_NETWORK_MESSAGE}


def test_the_pdf_browser_has_time_limits():
    assert 0 < render.PDF_STEP_TIMEOUT_MS <= 30_000


# --- B4: the WPS next step doesn't repeat the explanation -------------------------------------


def test_the_wps_pin_sentence_is_said_once():
    wps = next(r for r in load_rules().rules if r.id == "R-WPS")
    assert "PIN" not in wps.next_step and "PIN" in wps.why_it_matters
    assert wps.next_step == "Ask the host whether WPS can be switched off."
