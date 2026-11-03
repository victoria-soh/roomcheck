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

    def fake_run(consent, scanner, duration_seconds, online=True, **kwargs):
        seen["online"] = online
        seen.update(kwargs)
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


def test_discovery_passes_nearby_options(monkeypatch):
    client, seen = make_client(monkeypatch)
    with client:
        client.post("/api/discovery", json={"nearby": False, "room_network": "HomeNet"})
    assert (seen["include_nearby"], seen["typed_room"]) == (False, "HomeNet")


# --- the full scan runs the nearby check alongside discovery -----------------------------


def _scan(monkeypatch, **kwargs):
    import app.checks.wifi as wifi_mod
    import app.scan as scan_mod
    from app.wireless.ie import make_security
    from app.wireless.models import BssReading, NearbySurvey
    from app.wireless.survey import aggregate_wifi

    monkeypatch.setattr(scan_mod, "run_discovery", lambda mode, collectors: fake_result(mode))
    monkeypatch.setattr(scan_mod, "default_collectors", lambda scanner, duration: [])
    monkeypatch.setattr(wifi_mod, "connected_wifi", lambda: None)

    def nearby_fn():
        rounds = [
            [
                BssReading(bssid="cc:ba:bd:ac:94:d9", ssid="HomeNet", rssi_dbm=-40,
                           security=make_security("wpa2", pairwise=["CCMP"])),
                BssReading(bssid="9a:3b:4c:00:11:22", ssid="HomeNet", rssi_dbm=-42,
                           security=make_security("open")),
            ]
        ] * 2
        survey = NearbySurvey(access_points=aggregate_wifi(rounds), wifi_method="wlanapi",
                              ble_devices=[], ble_rounds=3)
        return survey, [], []

    return scan_mod.run_scan(False, None, 10, online=False, nearby_fn=nearby_fn, **kwargs)


def test_full_scan_includes_nearby_findings(monkeypatch):
    result = _scan(monkeypatch, typed_room="HomeNet")
    assert [f.rule_id for f in result.findings] == ["R-TWIN"]
    assert result.room_network == "HomeNet"
    assert [i.rule_ids for i in result.nearby_items] == [["R-TWIN"]]
    assert result.nearby_heard.wifi_access_points == 2
    assert "9a:3b:4c" not in result.model_dump_json()


def test_full_scan_without_nearby_says_so(monkeypatch):
    result = _scan(monkeypatch, include_nearby=False)
    skipped = {c.name: c.reason for c in result.checks if c.status == "skipped"}
    assert skipped["nearby_wifi"] == "Skipped because you chose not to run the nearby check."
    assert result.nearby_heard is None and result.nearby_items == []
