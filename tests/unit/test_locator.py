"""Layer 4 locator: rolling median, warmer/colder, unstable signal, lost signal, the Bluetooth
and Wi-Fi reading sources, and the API (nearby check, WebSocket stream, safeguards)."""

import asyncio
import json
import time
from datetime import UTC, datetime

import pytest
from bleak.exc import BleakError
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.main as main
from app.discovery.messages import message_for
from app.wireless import locator, wlanapi
from app.wireless.locator import LocatorTarget, Smoother, bar, ble_source, locate, wifi_source
from app.wireless.models import BssReading, HeardCounts, NearbyItem
from app.wireless.privacy import ble_ref, wifi_ref
from app.wireless.survey import NearbyResult
from app.wireless.wlanapi import WirelessError

SALT = b"test-salt"
PLAN_UNSTABLE = "The signal is jumping around. Move more slowly and hold the laptop still."


def feed(smoother, values):
    return [smoother.add(v) for v in values]


# --- smoothing and trend -------------------------------------------------------------------


def test_rolling_median_of_five():
    s = Smoother("bluetooth:x", "bluetooth")
    out = feed(s, [-70, -60, -90, -65, -62, -61])
    assert out[2].smoothed_dbm == -70  # median of -70, -60, -90
    assert out[-1].smoothed_dbm == -62  # median of the last five: -60 -90 -65 -62 -61
    assert len(s.raw) == 5


def test_starting_message_before_a_trend():
    s = Smoother("bluetooth:x", "bluetooth")
    first = s.add(-70)
    assert (first.trend, first.message) == (None, message_for("locator_starting"))


def test_warmer_as_the_signal_rises_and_colder_as_it_falls():
    s = Smoother("bluetooth:x", "bluetooth")
    rising = feed(s, [-80, -79, -78, -76, -74, -72, -70, -68])
    assert rising[-1].trend == "warmer"
    falling = feed(s, [-70, -72, -74, -76, -78, -80])
    assert falling[-1].trend == "colder"
    steady = feed(s, [-80, -80, -80, -80, -80, -80])
    assert steady[-1].trend == "same"


def test_unstable_signal_shows_raw_bar_without_words():
    s = Smoother("bluetooth:x", "bluetooth")
    feed(s, [-60, -61, -60, -62])
    r = s.add(-90)
    assert r.unstable and r.trend is None
    assert r.message == PLAN_UNSTABLE
    assert r.level == locator._level(-90)  # raw, not smoothed
    assert "(raw)" in bar(r) and "WARMER" not in bar(r) and "colder" not in bar(r)


def test_lost_signal_keeps_the_last_level():
    s = Smoother("wifi:x", "wifi")
    feed(s, [-60, -60, -60])
    r = s.add(None)
    assert not r.heard and r.trend is None
    assert r.message == message_for("locator_lost")
    assert r.smoothed_dbm == -60


def test_wifi_says_it_is_slow_and_compares_with_the_previous_scan():
    s = Smoother("wifi:x", "wifi")
    out = feed(s, [-80, -78, -74, -70])
    assert out[-1].note == message_for("locator_wifi_slow")
    assert out[-1].trend == "warmer"


def test_bar_text():
    r = locator.LocatorReading(ref="x", heard=True, smoothed_dbm=-65.0, level=0.5, trend="warmer")
    assert bar(r) == "[##########----------]        -65 dBm  WARMER"


def test_locate_stops_after_the_session_limit():
    async def source():
        while True:
            yield -60

    times = iter(range(100))

    async def run():
        target = LocatorTarget(ref="bluetooth:x", kind="bluetooth", label="Tag")
        return [r async for r in locate(target, source(), max_seconds=3, clock=lambda: next(times))]

    assert len(asyncio.run(run())) == 3


# --- reading sources -----------------------------------------------------------------------


class FakeScanner:
    def __init__(self, adverts, fail=None):
        self.adverts = adverts
        self.fail = fail
        self.stopped = False

    def __call__(self, detection_callback, scanning_mode):
        self.cb = detection_callback
        return self

    async def start(self):
        if self.fail:
            raise self.fail
        for address, rssi in self.adverts:
            self.cb(type("D", (), {"address": address})(), type("A", (), {"rssi": rssi})())

    async def stop(self):
        self.stopped = True


def take(agen, n):
    async def run():
        out = []
        async for x in agen:
            out.append(x)
            if len(out) == n:
                break
        await agen.aclose()
        return out

    return asyncio.run(run())


def test_ble_source_only_follows_the_flagged_device():
    target = "D1:22:33:44:55:66"
    fake = FakeScanner([(target, -60), ("AA:00:00:00:00:01", -30), (target.lower(), -58)])
    readings = take(ble_source(ble_ref(target, SALT), SALT, scanner_factory=fake, silence=0.01), 3)
    assert readings == [-60, -58, None]  # then silence
    assert fake.stopped


def test_ble_source_bluetooth_off():
    fake = FakeScanner([], fail=BleakError("Bluetooth is turned off"))
    with pytest.raises(WirelessError) as e:
        take(ble_source("bluetooth:x", SALT, scanner_factory=fake), 1)
    assert e.value.code == "bluetooth_off"


class FakeApi:
    def __init__(self, rounds):
        self.rounds = list(rounds)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def interfaces(self):
        return [wlanapi.Interface(wlanapi.GUID(), "Wi-Fi", wlanapi.INTERFACE_CONNECTED)]

    def scan(self, iface):
        pass

    def bss_list(self, iface):
        return self.rounds.pop(0)


def test_wifi_source_reads_once_per_scan_and_skips_stale_entries(monkeypatch):
    monkeypatch.setattr(wlanapi, "reading_from_raw", lambda raw: raw)
    from app.wireless.ie import make_security

    def r(rssi, ts, bssid="9a:3b:4c:00:11:22"):
        return BssReading(
            bssid=bssid, ssid="x", rssi_dbm=rssi, security=make_security("open"), host_timestamp=ts
        )

    api = FakeApi([[r(-60, 1)], [r(-60, 1)], [r(-55, 2), r(-30, 9, "00:0c:6e:00:00:01")], []])
    src = wifi_source(wifi_ref("9a:3b:4c:00:11:22", SALT), SALT, api_factory=lambda: api, settle=0)
    assert take(src, 4) == [-60, None, -55, None]


def test_wifi_locator_needs_the_wlan_api():
    def unavailable():
        raise WirelessError("wlanapi_unavailable")

    with pytest.raises(WirelessError) as e:
        take(wifi_source("wifi:x", SALT, api_factory=unavailable), 1)
    assert e.value.code == "locator_wifi_unavailable"


# --- API -----------------------------------------------------------------------------------

ITEM = NearbyItem(
    ref="bluetooth:abc",
    kind="bluetooth",
    label="Apple AirTag",
    signal_dbm=-50,
    rule_ids=["R-TRACKER"],
)


def nearby_result(items):
    now = datetime(2026, 11, 2, tzinfo=UTC)
    return NearbyResult(
        started_at=now,
        finished_at=now,
        room_network="HomeNet",
        wifi_method="wlanapi",
        checks=[],
        items=items,
        heard=HeardCounts(),
    )


@pytest.fixture
def client(monkeypatch):
    seen = {}

    def fake_check(typed_room=None):
        seen["typed_room"] = typed_room
        return nearby_result([ITEM])

    async def source():
        for v in (-70, -68, -66, -64):
            yield v

    monkeypatch.setattr(main, "run_nearby_check", fake_check)
    monkeypatch.setattr(main, "locator_source", lambda target: source())
    with TestClient(main.app) as c:
        c.seen = seen
        yield c


def test_nearby_endpoint_returns_flagged_items(client):
    r = client.post("/api/nearby", json={"room_network": "HomeNet"})
    assert r.status_code == 200
    assert [i["ref"] for i in r.json()["items"]] == ["bluetooth:abc"]
    assert client.seen["typed_room"] == "HomeNet"
    assert client.post("/api/nearby", json={"room_network": "x" * 33}).status_code == 422


def test_locator_streams_smoothed_readings(client):
    client.post("/api/nearby", json={})
    with client.websocket_connect("/api/nearby/locate/bluetooth:abc") as ws:
        readings = [ws.receive_json() for _ in range(4)]
    assert [r["raw_dbm"] for r in readings] == [-70, -68, -66, -64]
    assert readings[-1]["smoothed_dbm"] == -67.0
    assert readings[-1]["trend"] == "warmer"


def test_locator_refuses_items_that_were_not_flagged(client):
    client.post("/api/nearby", json={})
    with client.websocket_connect("/api/nearby/locate/bluetooth:someone-else") as ws:
        assert ws.receive_json() == {"error": message_for("locator_unknown_item")}
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
    assert e.value.code == main.WS_UNKNOWN_ITEM


def test_locator_refuses_before_any_check(client):
    with client.websocket_connect("/api/nearby/locate/bluetooth:abc") as ws:
        assert "error" in ws.receive_json()


def test_locator_rejects_other_websites(client):
    client.post("/api/nearby", json={})
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(
            "/api/nearby/locate/bluetooth:abc", headers={"origin": "https://evil.example"}
        ) as ws:
            ws.receive_json()
    assert e.value.code == main.WS_BAD_ORIGIN
    with client.websocket_connect(
        "/api/nearby/locate/bluetooth:abc", headers={"origin": "http://127.0.0.1:5173"}
    ) as ws:
        assert ws.receive_json()["raw_dbm"] == -70


def test_locator_reports_radio_failures(client, monkeypatch):
    async def off():
        raise WirelessError("bluetooth_off")
        yield  # pragma: no cover

    monkeypatch.setattr(main, "locator_source", lambda target: off())
    client.post("/api/nearby", json={})
    with client.websocket_connect("/api/nearby/locate/bluetooth:abc") as ws:
        assert ws.receive_json() == {"error": message_for("bluetooth_off")}


def test_a_new_check_replaces_the_locatable_items(client, monkeypatch):
    client.post("/api/nearby", json={})
    monkeypatch.setattr(main, "run_nearby_check", lambda typed_room=None: nearby_result([]))
    client.post("/api/nearby", json={})
    with client.websocket_connect("/api/nearby/locate/bluetooth:abc") as ws:
        assert "error" in ws.receive_json()


# --- the locator stops as soon as the page leaves (Part B: Stop, or leaving the screen) ------


def _slow_source(log):
    async def source():
        try:
            yield -70
            await asyncio.sleep(30)  # e.g. waiting for the next Wi-Fi scan
            yield -60
        finally:
            log.append("closed")

    return source


@pytest.mark.parametrize("how", ["close", "stop"])
def test_locator_stops_at_once_when_the_page_closes_or_says_stop(monkeypatch, how):
    """Through a real uvicorn server, as the browser would see it: the reading source is
    closed straight away, not after the 30 s wait for its next reading."""
    import socket
    import threading

    import uvicorn
    from websockets.sync.client import connect

    log = []
    monkeypatch.setattr(main, "locator_source", lambda target: _slow_source(log)())
    monkeypatch.setattr(
        main.app.state,
        "locator_targets",
        {"bluetooth:abc": LocatorTarget(ref="bluetooth:abc", kind="bluetooth", label="Tracker")},
        raising=False,
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(main.app, host="127.0.0.1", port=port, lifespan="off", log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        assert wait_for(lambda: server.started)
        start = time.monotonic()
        with connect(f"ws://127.0.0.1:{port}/api/nearby/locate/bluetooth:abc") as ws:
            assert json.loads(ws.recv(timeout=5))["raw_dbm"] == -70
            if how == "stop":
                ws.send("stop")
                assert wait_for(lambda: log == ["closed"])
        assert wait_for(lambda: log == ["closed"])
        assert time.monotonic() - start < 5
    finally:
        server.should_exit = True
        thread.join(5)


def wait_for(condition, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False
