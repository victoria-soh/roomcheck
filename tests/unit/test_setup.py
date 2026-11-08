"""The Start screen's readiness strip (GET /api/setup), the privacy text's configuration, the
permission choice in the report, and the connected network's name never leaving the laptop."""

import json

from fastapi.testclient import TestClient
from pydantic import SecretStr

import app.main as main
from app.checks.cve import model_queries
from app.config import Settings
from app.explain import ai
from app.report import render, tamper
from app.setup_check import ConnectedNetwork, check_setup, outside_calls
from tests.unit.test_explain import room
from tests.unit.test_report import scan_result

NAME = "Example-Home"


def setup_with(radios=None, location=True, npcap=True, nmap=True, network=None, settings=None):
    return check_setup(
        settings or Settings(),
        radios=lambda: radios if radios is not None else {"wifi": True, "bluetooth": True},
        location=lambda: location,
        npcap=lambda: npcap,
        nmap=lambda: nmap,
        network=lambda: network or ConnectedNetwork(kind="wifi", name=NAME),
    )


def test_all_ready_on_wifi():
    s = setup_with()
    assert s.all_ready
    assert [(i.name, i.ready) for i in s.items] == [
        ("wifi", True),
        ("bluetooth", True),
        ("location", True),
        ("npcap", True),
        ("nmap", True),
    ]
    assert (s.network.kind, s.network.name) == ("wifi", NAME)


def test_missing_items_are_reported_not_blocking():
    s = setup_with(radios={"wifi": True, "bluetooth": False}, nmap=False)
    assert not s.all_ready
    assert {i.name for i in s.items if not i.ready} == {"bluetooth", "nmap"}


def test_no_radio_and_a_failing_check_count_as_missing():
    def boom():
        raise RuntimeError("registry unavailable")

    s = check_setup(
        Settings(),
        radios=lambda: {},  # no Wi-Fi or Bluetooth radio at all
        location=boom,
        npcap=lambda: True,
        nmap=lambda: True,
        network=lambda: ConnectedNetwork(kind="cable"),
    )
    assert {i.name for i in s.items if not i.ready} >= {"wifi", "bluetooth", "location"}
    assert s.network == ConnectedNetwork(kind="cable")


def test_not_connected():
    s = setup_with(network=ConnectedNetwork(kind="none"))
    assert s.network.kind == "none" and s.network.name is None


def test_outside_calls_follow_the_configuration():
    off = outside_calls(Settings(tsa_url=""))
    assert (off.ai, off.known_issues, off.timestamp) == (False, True, None)
    on = outside_calls(
        Settings(anthropic_api_key=SecretStr("sk-ant-test"), tsa_url="https://freetsa.org/tsr")
    )
    assert (on.ai, on.timestamp) == (True, "freetsa.org")


def test_setup_endpoint(monkeypatch):
    monkeypatch.setattr(main, "check_setup", lambda settings: setup_with(settings=settings))
    with TestClient(main.app) as c:
        body = c.get("/api/setup").json()
    assert body["network"] == {"kind": "wifi", "name": NAME}
    assert body["all_ready"] is True
    assert body["outside"]["ai"] is False  # the test settings have no key


# --- the network name never leaves the laptop ---------------------------------------------------


def test_the_network_name_is_in_no_outgoing_payload(tmp_path):
    findings, devices, nearby = room()
    nearby = [
        i.model_copy(update={"ssid": NAME, "label": f'Wi-Fi network "{NAME}"'}) for i in nearby
    ]
    payload, _ = ai.build_payload(findings, devices, nearby)
    assert NAME not in json.dumps(payload)  # the AI call
    for d in devices:
        assert NAME not in json.dumps(model_queries(d))  # the known-issue lookups
    # The timestamp request carries the PDF's hash and nothing else.
    sent = []

    def service(digest, url):
        sent.append(digest)
        raise tamper.TimestampUnavailable("offline in this test")

    tamper.save(b"%PDF-1.4 made up", tmp_path, "roomcheck-report-20261103-132509", request=service)
    assert sent == [tamper.sha256(b"%PDF-1.4 made up")]


# --- the permission choice in the report -------------------------------------------------------


def test_the_report_records_the_permission_choice():
    from app.explain.models import Explanations

    full = scan_result()
    html = render.render_html(
        render.build_view(full, Explanations(), room_label=None, generated_at=full.finished_at)
    )
    # In the dashboard's words: "With permission" or "Listening only".
    assert "<td><b>Type of check</b></td><td>With permission</td>" in html
    passive = full.model_copy(update={"mode": "passive"})
    html = render.render_html(
        render.build_view(passive, Explanations(), room_label=None, generated_at=full.finished_at)
    )
    assert "<td><b>Type of check</b></td><td>Listening only</td>" in html
    assert "<td><b>Type of check</b></td><td>With permission</td>" not in html
