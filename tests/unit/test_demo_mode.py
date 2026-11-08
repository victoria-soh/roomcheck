"""`python -m app --demo`: every screen's API works on the pipeline-built demo data, with no
scans, probes, radios or outside calls."""

from __future__ import annotations

import ipaddress
import socket
import time

import pytest
from fastapi.testclient import TestClient

from app import demo, main, setup_check
from app import scan as scan_mod


def _loopback(address: object) -> bool:
    host = address[0] if isinstance(address, tuple) else address
    try:
        return ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        return str(host) in ("localhost", "testserver")


@pytest.fixture
def client(monkeypatch):
    """The app in demo mode, failing on any connection off this laptop or any real scan."""
    real_connect = socket.socket.connect

    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not _loopback(address):
            raise AssertionError(f"demo mode connected to {address!r}")
        return real_connect(sock, address)

    def forbidden(*args, **kwargs):
        raise AssertionError("demo mode ran a real scan or read the real setup")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(main, "ScannerProcess", forbidden)
    monkeypatch.setattr(main, "run_scan", forbidden)
    monkeypatch.setattr(scan_mod, "run_scan", forbidden)
    monkeypatch.setattr(main, "run_nearby_check", forbidden)
    monkeypatch.setattr(main, "check_setup", forbidden)
    monkeypatch.setattr(setup_check, "connected_network", forbidden)
    monkeypatch.setattr(demo, "STEP_SECONDS", 0.01)
    main.app.state.demo_requested = True
    try:
        with TestClient(main.app) as c:
            yield c
    finally:
        state = main.app.state
        state.demo_requested = False
        state.demo = False
        state.report_dir = None
        state.handover = None
        state.last_result = None
        state.demo_folder = None


def _check(client, consent=True, stay="short_stay"):
    job = client.post("/api/scans", json={"consent": consent, "stay": stay}).json()["id"]
    end = time.monotonic() + 10
    while time.monotonic() < end:
        snap = client.get(f"/api/scans/{job}").json()
        if snap["state"] == "done":
            return snap
        time.sleep(0.02)
    raise AssertionError("the demo check didn't finish")


def test_health_and_setup_say_demo_and_show_a_made_up_laptop(client):
    assert client.get("/api/health").json()["demo"] is True
    setup = client.get("/api/setup").json()
    assert setup["network"] == {"kind": "wifi", "name": "Example-Home"}
    assert setup["all_ready"] is True
    assert setup["outside"] == {"ai": False, "known_issues": False, "timestamp": None}


def test_a_demo_check_replays_the_steps_and_shows_the_demo_check(client):
    snap = _check(client)
    assert [s["status"] for s in snap["steps"]] == ["done"] * 5
    result = snap["result"]
    assert result["mode"] == "full"
    assert {f["rule_id"] for f in result["findings"]} >= {"R-CAM", "R-WPS", "R-TRACKER"}
    assert all(d["ip"].startswith("192.0.2.") for d in result["devices"] if d["ip"])
    assert result["explanations"]["ai_status"] != "used"  # no key: standard words


def test_listening_only_shows_the_listening_check(client):
    snap = _check(client, consent=False, stay="other")
    assert snap["result"]["mode"] == "passive"
    assert snap["steps"][2]["status"] == "skipped"  # services needs permission


def test_compare_has_a_demo_move_in_scan(client):
    assert client.get("/api/baseline").json()["state"] == "saved"
    _check(client)
    compare = client.get("/api/compare").json()
    assert compare["state"] == "ready"
    comparison = compare["comparison"]
    assert comparison["new"] or comparison["changed"] or comparison["gone"]
    assert comparison["scan_at"] > comparison["baseline_saved_at"]  # the check is the later one


def test_the_report_builds_locally_without_a_timestamp(client, tmp_path):
    _check(client)
    body = client.post("/api/report", json={"timestamp": True, "ai": True}).json()
    assert body["tsr"] is None
    assert body["timestamp"]["state"] == "unavailable"
    assert body["timestamp"]["reason"].startswith("Demo mode")
    pdf = client.get(f"/api/report/files/{body['pdf']}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    # Saved in the demo's temporary folder, never the real reports folder.
    assert main.app.state.report_dir.name == "reports"
    assert "roomcheck-demo-" in str(main.app.state.report_dir)
    verified = client.post("/api/verify", files={"pdf": ("r.pdf", pdf.content)}).json()
    assert verified["sha256"] == body["sha256"]


def test_handover_and_recheck_use_made_up_readings(client):
    _check(client)
    tasks = client.get("/api/handover").json()["tasks"]
    wps = next(t for t in tasks if t["rule_id"] == "R-WPS")
    client.patch(f"/api/tasks/{wps['id']}", json={"status": "resolved"})
    after = client.post(f"/api/tasks/{wps['id']}/recheck").json()
    rechecked = next(t for t in after["tasks"] if t["id"] == wps["id"])
    assert rechecked["recheck"]["outcome"] == "fixed"


def test_the_nearby_only_check_says_demo_mode_never_listens(client):
    r = client.post("/api/nearby", json={})
    assert r.status_code == 409 and "Demo mode" in r.json()["detail"]


def test_the_locator_streams_made_up_readings(client):
    result = _check(client)["result"]
    ref = next(i["ref"] for i in result["nearby_items"])
    with client.websocket_connect(f"/api/nearby/locate/{ref}") as ws:
        reading = ws.receive_json()
    assert "level" in reading


def test_the_real_store_is_never_used(client, monkeypatch):
    # The demo's store is its own temporary file, with the demo's fixed salt.
    from app import demo_data

    assert main.app.state.handover.salt == demo_data.SALT
    assert "roomcheck-demo-" in str(main.app.state.handover.store.path)
