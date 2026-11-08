"""The Results redesign's backend: scan coverage from the real check statuses, the fixed
"observed" sentence on every finding, the "Host's" follow-up feeding "Host confirmed", and the
user's short device names (plain text, encrypted with the baseline, shown in Compare and the
report)."""

import re

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.baseline.compare import compare, snapshot
from app.baseline.store import BaselineStore
from app.coverage import coverage, is_partial, line
from app.discovery.messages import message_for
from app.discovery.models import CheckStatus, DiscoveryResult
from app.explain.models import Explanations
from app.handover.models import clean_name
from app.handover.session import HandoverSession
from app.report import render
from app.rules.engine import load_rules
from tests.conftest import FakeProtector
from tests.unit.test_layer6 import SALT, T0, T1, camera, check
from tests.unit.test_rules import _SAFE

# --- coverage ----------------------------------------------------------------------------------


def c(name, status="ran", code=None):
    return CheckStatus(
        name=name, label=name, status=status, reason=message_for(code) if code else None
    )


def result_with(checks, mode="full"):
    return DiscoveryResult(
        started_at=T1, finished_at=T1, mode=mode, network=None, devices=[], checks=checks
    )


FULL = [
    c("passive_listen"),
    c("mdns"),
    c("arp_sweep"),
    c("ssdp"),
    c("onvif"),
    c("vendor_lookup"),
    c("port_check"),
    c("identity_check"),
    c("wifi_encryption"),
    c("dns"),
    c("arp"),
    c("dhcp"),
    c("upnp"),
    c("cve"),
    c("nearby_wifi"),
    c("lookalike"),
    c("wps"),
    c("bluetooth"),
]


def rows(checks, mode="full"):
    return {r.area: r for r in coverage(result_with(checks, mode))}


def test_everything_ran_is_completed_and_not_partial():
    got = rows(FULL)
    assert list(got) == [
        "devices",
        "services",
        "router",
        "known_issues",
        "nearby_wifi",
        "bluetooth",
    ]
    assert {r.state for r in got.values()} == {"completed"}
    assert not is_partial(list(got.values()))


def test_listening_only_says_it_was_the_users_choice():
    passive = {"arp_sweep", "ssdp", "onvif", "port_check", "identity_check", "dhcp"}
    checks = [c(x.name, "skipped", "passive_mode") if x.name in passive else x for x in FULL]
    got = rows(checks, mode="passive")
    assert line(got["services"]) == "Not checked (partly): you chose a listen-only check"
    assert line(got["devices"]) == "Not checked (partly): you chose a listen-only check"
    assert got["router"].state == "limited"
    assert got["bluetooth"].state == "completed"
    assert is_partial(list(got.values()))


def test_bluetooth_off_is_not_run_with_a_plain_reason():
    checks = [
        c("bluetooth", "failed", "bluetooth_off") if x.name == "bluetooth" else x for x in FULL
    ]
    assert line(rows(checks)["bluetooth"]) == "Not checked: Bluetooth is off"


def test_a_failure_with_an_unknown_message_keeps_its_own_words():
    checks = [
        CheckStatus(name="cve", label="cve", status="failed", reason="Something unusual.")
        if x.name == "cve"
        else x
        for x in FULL
    ]
    assert line(rows(checks)["known_issues"]) == "Not checked: Something unusual"


def test_areas_with_no_checks_are_left_out():
    got = rows([c("nearby_wifi"), c("lookalike"), c("wps"), c("bluetooth")])
    assert list(got) == ["nearby_wifi", "bluetooth"]


def test_a_real_scan_result_carries_its_coverage(monkeypatch):
    import app.scan as scan_mod

    monkeypatch.setattr(scan_mod, "run_discovery", lambda *a, **k: result_with([c("mdns")]))
    monkeypatch.setattr(scan_mod, "default_collectors", lambda *a: [])
    r = scan_mod.run_scan(True, None, 1, include_nearby=False)
    assert [x.area for x in r.coverage][0] == "devices"
    assert r.coverage[0].state == "completed"
    nearby = {x.area: x for x in r.coverage}["nearby_wifi"]
    assert line(nearby) == "Not checked: you chose not to run the nearby check"


# --- the fixed "observed" sentence --------------------------------------------------------------


def test_every_rule_says_what_was_observed_in_one_plain_sentence():
    for rule in load_rules().rules:
        texts = rule.observed.values() if isinstance(rule.observed, dict) else [rule.observed]
        for text in texts:
            assert text.endswith(".") and text.count(". ") == 0, rule.id
            assert not _SAFE.search(text), rule.id


def test_findings_carry_the_observed_sentence():
    cam = next(f for f in check([camera()]).findings if f.rule_id == "R-CAM")
    assert cam.observed.startswith("A device on this network gave camera-like clues")


# --- "Host's" and "Has the host confirmed this?" ------------------------------------------------


def session(tmp_path):
    return HandoverSession(BaselineStore(tmp_path / "b.db", FakeProtector()))


def cam_task(s, result):
    return next(t for t in s.state_for(result).tasks if t.rule_id == "R-CAM")


def test_host_confirmed_feeds_the_host_confirmed_status(tmp_path):
    s = session(tmp_path)
    result = check([camera()])
    subject = cam_task(s, result).subject
    s.set_answer(subject, "landlord", confirmed=False)
    assert not cam_task(s, result).host_confirmed  # "Not yet": still to ask
    s.set_answer(subject, "landlord", confirmed=True)
    task = cam_task(s, result)
    assert (task.status, task.host_confirmed) == ("todo", True)  # evidence, not a status
    assert s.state_for(result).confirmed == {subject: True}
    # The finding itself never changes.
    cam = next(f for f in result.findings if f.rule_id == "R-CAM")
    assert cam.severity == "High"


def test_a_done_task_stays_done_and_changing_the_answer_clears_confirmed(tmp_path):
    s = session(tmp_path)
    result = check([camera()])
    task = cam_task(s, result)
    s.update_task(task.id, "resolved", None, now=T1)
    s.set_answer(task.subject, "landlord", confirmed=True)
    assert cam_task(s, result).status == "resolved"
    s.set_answer(task.subject, "unknown")
    assert s.state_for(result).confirmed == {}


def test_confirmed_and_names_are_saved_encrypted_with_the_baseline(tmp_path):
    path = tmp_path / "b.db"
    s = HandoverSession(BaselineStore(path, FakeProtector()))
    result = check([camera()])
    subject = cam_task(s, result).subject
    s.set_answer(subject, "landlord", confirmed=True)
    s.set_name(subject, "Hallway camera")
    assert path.exists()  # saved straight away, with or without a move-in scan
    assert b"Hallway camera" not in path.read_bytes()
    s.save_baseline(result, now=T0)
    s.set_name(subject, "Hall cam")  # later changes are saved straight away
    assert b"Hall cam" not in path.read_bytes()  # encrypted on disk
    again = HandoverSession(BaselineStore(path, FakeProtector()))
    assert again.confirmed == {subject: True}
    assert again.names == {subject: "Hall cam"}


# --- device names ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, name",
    [
        ("  Hallway   camera ", "Hallway camera"),
        ('Tom & Jerry\'s "cam"', 'Tom & Jerry\'s "cam"'),
        ("", ""),
        ("x" * 40, "x" * 40),
    ],
)
def test_names_are_plain_short_text(text, name):
    assert clean_name(text) == name


@pytest.mark.parametrize("text", ["x" * 41, "<b>cam</b>", "a\nb", "tab\there", "nul\x00"])
def test_markup_control_characters_and_long_names_are_refused(text):
    with pytest.raises(ValueError):
        clean_name(text)


@pytest.fixture
def client(no_real_baseline_store, monkeypatch):
    monkeypatch.setattr(main.app.state, "last_result", None, raising=False)
    with TestClient(main.app) as cl:
        yield cl


def test_names_api_sets_clears_and_refuses_markup(client):
    main.app.state.last_result = check([camera()])
    subject = next(f.subject for f in main.app.state.last_result.findings)
    r = client.post("/api/names", json={"subject": subject, "name": "Hallway camera"})
    assert r.status_code == 200 and r.json()["names"] == {subject: "Hallway camera"}
    bad = client.post("/api/names", json={"subject": subject, "name": "<script>x</script>"})
    assert (bad.status_code, bad.json()["detail"]) == (422, message_for("name_invalid"))
    long = client.post("/api/names", json={"subject": subject, "name": "y" * 41})
    assert long.status_code == 422
    cleared = client.post("/api/names", json={"subject": subject, "name": ""})
    assert cleared.json()["names"] == {}


def test_answers_api_takes_the_host_follow_up(client):
    main.app.state.last_result = check([camera()])
    subject = next(f.subject for f in main.app.state.last_result.findings)
    body = client.post(
        "/api/answers", json={"subject": subject, "answer": "landlord", "confirmed": True}
    ).json()
    assert body["answers"] == {subject: "landlord"} and body["confirmed"] == {subject: True}
    task = next(t for t in body["tasks"] if t["subject"] == subject)
    assert (task["status"], task["host_confirmed"]) == ("todo", True)


def test_the_report_shows_the_name_escaped_the_answer_and_the_coverage(tmp_path):
    s = session(tmp_path)
    result = check([camera()])
    result.checks = [c("bluetooth", "failed", "bluetooth_off"), c("mdns")]
    result.coverage = coverage(result)
    subject = cam_task(s, result).subject
    s.set_answer(subject, "landlord", confirmed=True)
    s.set_name(subject, "Tom & Jerry's cam")
    html = render.render_html(
        render.build_view(
            result,
            Explanations(),
            room_label=None,
            generated_at=T1,
            handover=s.state_for(result),
        )
    )
    assert "Your name for it: Tom &amp; Jerry&#39;s cam" in html
    assert "You said this is the host&#39;s, and the host confirmed it." in html
    assert "Coverage and limits" in html
    # One row per check, labelled and worded as Coverage and limits on Results (this test's
    # checks are labelled with their names).
    assert "<td>bluetooth</td><td>Not checked: Bluetooth is off</td>" in html
    # A check that ran, in its own words (what it heard), as on Results.
    assert re.search(
        r"<td>mdns</td><td>(No device announced itself"
        r"|\d+ devices? announced (itself|themselves))</td>",
        html,
    )


def test_compare_items_carry_the_subject_names_attach_to():
    base = check([camera()], at=T0)
    baseline = snapshot(base, SALT, T0)
    later = check([], at=T1)  # the camera is gone
    comparison = compare(baseline, later, SALT)
    (gone,) = comparison.gone
    cam_subject = next(f.subject for f in base.findings if f.rule_id == "R-CAM")
    assert gone.subject == cam_subject
