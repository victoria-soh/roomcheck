from datetime import UTC, datetime

from fastapi.testclient import TestClient

import app.main as main
from app.discovery.models import DiscoveryResult


def fake_result(mode):
    now = datetime(2026, 11, 2, tzinfo=UTC)
    return DiscoveryResult(
        started_at=now, finished_at=now, mode=mode, network=None, devices=[], checks=[]
    )


def make_client(monkeypatch):
    seen = {}

    def fake_run(consent, scanner, duration_seconds, online=True):
        seen["online"] = online
        mode = "full" if consent else "passive"
        seen["mode"] = mode
        return fake_result(mode)

    monkeypatch.setattr(main, "run_scan", fake_run)
    return TestClient(main.app), seen


def test_server_is_configured_for_loopback_only():
    assert main.HOST == "127.0.0.1"


def test_discovery_is_passive_without_consent(monkeypatch):
    client, seen = make_client(monkeypatch)
    with client:
        r = client.post("/api/discovery", json={})
    assert r.status_code == 200
    assert seen["mode"] == "passive"


def test_discovery_full_with_consent(monkeypatch):
    client, seen = make_client(monkeypatch)
    with client:
        r = client.post("/api/discovery", json={"consent": True, "duration_seconds": 30})
        health = client.get("/api/health").json()
    assert r.json()["mode"] == "full"
    assert seen["mode"] == "full"
    assert health["ok"] is True


def test_duration_is_bounded(monkeypatch):
    client, _ = make_client(monkeypatch)
    with client:
        assert client.post("/api/discovery", json={"duration_seconds": 3600}).status_code == 422
