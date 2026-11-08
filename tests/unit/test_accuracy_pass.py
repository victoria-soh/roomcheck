"""Fixes and accuracy pass: app logging, stable identification, honest Compare, wording."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
import yaml

from app import logsetup
from app.baseline.compare import compare, identification_varied, snapshot
from app.discovery.models import CoverageItem
from app.fingerprint.facts import device_facts
from app.fingerprint.models import Identity
from app.fingerprint.scoring import fingerprint
from app.rules.engine import load_rules
from scannerd import session
from scannerd.jobs import ports
from tests.unit import devices as dev
from tests.unit.test_layer6 import SALT, T0, camera, check, scored

ROOT = Path(__file__).resolve().parents[2]

# --- 1. logging -------------------------------------------------------------------------------


@pytest.fixture
def clean_logging():
    app_log, aio = logging.getLogger("app"), logging.getLogger("asyncio")
    saved = (list(app_log.handlers), app_log.level, list(aio.filters))
    yield
    app_log.handlers[:], aio.filters[:] = saved[0], saved[2]
    app_log.setLevel(saved[1])


def test_app_logs_reach_the_terminal_in_the_workers_format(clean_logging, capsys):
    logsetup.configure_logging()
    logsetup.configure_logging()  # idempotent: one handler, one filter
    app_log = logging.getLogger("app")
    ours = [h for h in app_log.handlers if h.get_name() == "roomcheck-app"]
    assert len(ours) == 1
    assert (
        sum(
            isinstance(f, logsetup.QuietConnectionReset)
            for f in logging.getLogger("asyncio").filters
        )
        == 1
    )
    # A handler made at configure time holds the stderr of that moment; point it at capsys's.
    ours[0].setStream(sys.stderr)  # type: ignore[attr-defined]
    logging.getLogger("app.report.render").info("report: PDF in %.1f s", 1.25)
    assert "app: report: PDF in 1.2 s" in capsys.readouterr().err


def _record(exc: BaseException | None, level: int = logging.ERROR) -> logging.LogRecord:
    info = (type(exc), exc, None) if exc else None
    return logging.LogRecord("asyncio", level, __file__, 1, "Exception in callback", None, info)


def test_a_dropped_websocket_is_a_debug_line_not_a_traceback():
    f = logsetup.QuietConnectionReset()
    reset = ConnectionResetError(10054, "An existing connection was forcibly closed")
    reset.winerror = 10054  # type: ignore[attr-defined]  # set by Windows only
    rec = _record(reset)
    assert f.filter(rec) is False  # asyncio's logger isn't at DEBUG: dropped
    assert (rec.levelno, rec.exc_info) == (logging.DEBUG, None)
    assert "10054" in rec.getMessage()
    # Anything else still goes through, with its traceback.
    other = _record(OSError(5, "Access is denied"))
    assert f.filter(other) is True and other.levelno == logging.ERROR and other.exc_info
    assert f.filter(_record(None)) is True


def test_at_debug_the_reset_is_kept_as_one_line(clean_logging):
    aio = logging.getLogger("asyncio")
    old = aio.level
    aio.setLevel(logging.DEBUG)
    try:
        reset = ConnectionResetError(10054, "reset")
        assert logsetup.QuietConnectionReset().filter(_record(reset)) is True
    finally:
        aio.setLevel(old)


# --- 2. stable identification ------------------------------------------------------------------


@pytest.fixture
def fresh_session():
    session.clear()
    yield
    session.clear()


def test_port_targets_include_hosts_heard_but_not_swept(fresh_session):
    # The live case: the camera missed this run's sweep but was heard by the listener.
    session.record_heard(["192.0.2.64", "192.0.2.1"])
    assert session.port_targets() == []  # nothing before a (consented) sweep
    session.record_swept(["192.0.2.1", "192.0.2.10"])
    assert session.port_targets() == ["192.0.2.1", "192.0.2.10", "192.0.2.64"]
    session.record_swept(["192.0.2.1"])  # a later sweep replaces the swept list only
    assert session.port_targets() == ["192.0.2.1", "192.0.2.64"]
    session.record_heard(["not-an-ip"])  # junk never becomes a target
    assert session.port_targets() == ["192.0.2.1"]


def test_the_port_job_scans_every_host_the_worker_saw(fresh_session, monkeypatch):
    from app.discovery.models import NetworkInfo

    net = NetworkInfo(
        interface="Wi-Fi",
        own_ip="192.0.2.50",
        own_mac=None,
        gateway_ip="192.0.2.1",
        netmask="255.255.255.0",
        cidr="192.0.2.0/24",
        prefixlen=24,
        sweep_allowed=True,
    )
    seen: dict[str, str] = {}

    class FakeScanner:
        def __init__(self, nmap_search_path):
            pass

        def scan(self, hosts, ports, arguments, timeout):
            seen["hosts"] = hosts
            return {"scan": {}}

    import nmap

    monkeypatch.setattr(ports.shutil, "which", lambda _: "nmap.exe")
    monkeypatch.setattr(ports, "get_network_info", lambda: net)
    monkeypatch.setattr(nmap, "PortScanner", FakeScanner)
    session.record_swept(["192.0.2.1"])
    session.record_heard(["192.0.2.64", "192.0.2.50"])  # .50 is this laptop: never scanned
    ports.port_scan(ports.PortScanParams())
    assert seen["hosts"] == "192.0.2.1 192.0.2.64"


def test_onvif_alone_is_possible_and_with_its_ports_likely():
    """Why the CLI said Possible and the dashboard Likely: the same scoring, given fewer
    clues when the camera wasn't port-checked."""
    full = camera()
    assert full.fingerprint.band == "Likely"
    quiet = dev.hikvision_camera()
    quiet.identity = Identity(open_ports=None)
    quiet.fingerprint = fingerprint(device_facts(quiet), "full")
    assert quiet.fingerprint.band == "Possible"


def _possible_camera():
    d = dev.hikvision_camera()
    d.identity = Identity(open_ports=[80])  # checked, but no RTSP or recorder ports this time
    return scored(d)


def test_compare_doesnt_call_a_confidence_change_a_change():
    base = snapshot(check([camera()], at=T0), SALT, T0)
    assert base.devices[0].band == "Likely"
    out = compare(base, check([_possible_camera()]), SALT)
    # Ports did change (554 and 8000 not seen), so it's listed as Changed for that reason,
    # with the higher band and the note; never "Now looks like".
    (item,) = out.changed
    assert not [c for c in item.changes if c.startswith("Now looks like")]
    assert (item.band, item.identification_varied) == ("Likely", True)


def test_only_the_confidence_moved_means_unchanged_and_listed_as_varied():
    likely = camera()
    base = snapshot(check([likely], at=T0), SALT, T0)
    now = camera()
    # Same ports (so nothing else changed), but fewer clues scored this time.
    now.fingerprint = now.fingerprint.model_copy(
        update={
            "band": "Possible",
            "confidence": 0.72,
            "evidence": [e for e in now.fingerprint.evidence if e.signal == "onvif_nvt"],
        }
    )
    out = compare(base, check([now]), SALT)
    assert out.changed == [] and out.unchanged == 1
    (item,) = out.varied
    assert (item.label, item.band, item.identification_varied) == ("Camera", "Likely", True)


def test_no_shared_clues_is_not_varied_identification():
    base = snapshot(check([camera()], at=T0), SALT, T0)
    old = base.devices[0]
    now = camera()
    now.fingerprint = now.fingerprint.model_copy(
        update={
            "band": "Possible",
            "evidence": [
                e.model_copy(update={"signal": "something_else"}) for e in now.fingerprint.evidence
            ],
        }
    )
    assert identification_varied(old, now) is False
    old_unclear = old.model_copy(update={"band": "Unclear"})
    assert identification_varied(old_unclear, camera()) is False  # Unclear isn't a type guess
    assert identification_varied(old.model_copy(update={"band": None}), camera()) is False


# --- 3. Compare honesty -------------------------------------------------------------------------


def _coverage(result, services="completed"):
    result.coverage = [
        CoverageItem(area=a, label=a.title(), state=services if a == "services" else "completed")
        for a in ("devices", "services", "router", "known_issues", "nearby_wifi", "bluetooth")
    ]
    return result


def test_a_listening_only_check_shows_no_port_or_guess_differences():
    base = snapshot(_coverage(check([camera()], at=T0)), SALT, T0)
    listened = dev.hikvision_camera()
    listened.identity = None  # a listening-only check never looked at its services
    listened.fingerprint = fingerprint(device_facts(listened), "passive")
    later = _coverage(check([listened]), services="not_run")
    later.mode = "passive"
    out = compare(base, later, SALT)
    assert out.ran_differently and out.warnings == []
    changes = [c for item in out.changed for c in item.changes]
    assert not [c for c in changes if "port" in c.lower() or c.startswith("Now looks like")]


def test_a_finding_the_move_in_check_couldnt_look_for_isnt_new():
    router = scored(dev.tp_link_gateway())
    router.identity = None
    base = _coverage(check([router], at=T0), services="not_run")
    base.mode = "passive"
    baseline = snapshot(base, SALT, T0)
    now = scored(dev.tp_link_gateway())
    now.identity.open_ports = [23, 80]
    now.fingerprint = fingerprint(device_facts(now), "full")
    out = compare(baseline, _coverage(check([now])), SALT)
    assert out.ran_differently
    changes = [c for item in out.changed for c in item.changes]
    assert not [c for c in changes if c.startswith("New finding") or "port" in c.lower()]


# --- 5. wording -------------------------------------------------------------------------------


def test_the_wps_card_title_and_observation_differ():
    wps = next(r for r in load_rules().rules if r.id == "R-WPS")
    assert wps.title == "Router advertises WPS"
    assert wps.observed == "The router's Wi-Fi broadcast says WPS is on."
    assert isinstance(wps.observed, str) and isinstance(wps.title, str)
    assert wps.title.rstrip(".").lower() != wps.observed.rstrip(".").lower()


def test_no_rule_has_a_comment_inside_it():
    """Section comments sit between rules, never between one rule's keys (R-CVE had one)."""
    lines = (ROOT / "app" / "rules" / "rules.yaml").read_text("utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("  # ---"):
            nxt = next(x for x in lines[i + 1 :] if x.strip())
            assert nxt.startswith("  - id:"), f"comment on line {i + 1} sits inside a rule"
    assert yaml.safe_load("\n".join(lines))  # still valid


def test_the_header_mode_and_coverage_wording():
    import json

    strings = json.loads((ROOT / "web" / "src" / "strings" / "en.json").read_text("utf-8"))
    assert strings["compare"]["mode"] == {"full": "With permission", "passive": "Listening only"}
    assert (strings["scanning"]["modeFull"], strings["scanning"]["modeListen"]) == (
        "With permission",
        "Listening only",
    )
    assert strings["results"]["coverageLine"]["partial"] == "{{checked}} of {{total}} checks ran"
    assert strings["results"]["viewPartial"] == "See what didn't"
    # The priority filter chips (and their "Choose a priority to filter." hint) are gone:
    # Results is organised by the renter's questions, with priority as a label on each card.
    assert "counts" not in strings["results"]
    assert (
        strings["compare"]["ranDifferently"]
        == "These checks ran differently, so some differences may come from that."
    )
