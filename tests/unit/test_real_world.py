"""Real-world features: stay type, the physical check, listening only as its own path,
hidden-camera guidance, a report written for its reader, and the summary sentence."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.baseline.store import BaselineStore
from app.explain.models import Explanations
from app.fingerprint.facts import device_facts
from app.fingerprint.scoring import fingerprint, load_weights
from app.handover.models import PHYSICAL_ITEMS, HandoverState, PhysicalCheck, PhysicalItem
from app.handover.session import HandoverSession
from app.questions import question_statuses, top_line
from app.report import render
from app.rules.engine import RoomFacts, evaluate, load_rules
from tests.conftest import FakeProtector
from tests.unit import demo_data
from tests.unit import devices as dev
from tests.unit.test_layer6 import camera, scored
from tests.unit.test_report import scan_result
from tests.unit.test_rules import NET

ROOT = Path(__file__).resolve().parents[2]
STRINGS = json.loads((ROOT / "web/src/strings/en.json").read_text("utf-8"))
T = datetime(2026, 11, 3, 6, 0, tzinfo=UTC)


# --- D9: where you're staying ------------------------------------------------------------------


def _next_steps(stay):
    lock = scored(dev.make("192.0.2.9", "00:11:22:33:44:01", hostnames=["front-door-lock"]))
    findings = evaluate(RoomFacts(devices=[camera(), lock], network=NET, stay=stay))
    return {f.rule_id: f.next_step for f in findings}


def test_camera_and_lock_next_steps_follow_the_stay_type():
    other = _next_steps("other")
    assert other == _next_steps(None)  # "Other" is each rule's default
    # A camera: first find it and say where it is (the stay type adds a line).
    short = _next_steps("short_stay")
    assert short["R-CAM"].startswith("Find it physically, then say where it is.")
    assert "Many platforms don't allow indoor cameras" in short["R-CAM"]
    rental = _next_steps("rental")
    assert "tenancy agreement" in rental["R-CAM"]
    assert "in writing" in rental["R-LOCK"]
    hostel = _next_steps("hostel")
    assert "front desk or management" in hostel["R-LOCK"]
    # Priorities never change with the stay type: fixed rules decide them.
    sev = {f.rule_id: f.severity for f in evaluate(RoomFacts(devices=[camera()], network=NET))}
    for stay in ("short_stay", "rental", "hostel"):
        assert {
            f.rule_id: f.severity
            for f in evaluate(RoomFacts(devices=[camera()], network=NET, stay=stay))
        } == sev


def test_every_stay_dependent_rule_has_all_three_stay_types():
    for rule in load_rules().rules:
        if rule.next_step_by_stay:
            assert set(rule.next_step_by_stay) == {"short_stay", "rental", "hostel"}, rule.id
    assert {r.id for r in load_rules().rules if r.next_step_by_stay} == {
        "R-CAM",
        "R-NEW-CAMERA",
        "R-LOCK",
        "R-CLOUD",
    }


def test_the_report_names_the_stay_type():
    result = scan_result()
    result.stay_type = "short_stay"
    html = render.render_html(
        render.build_view(result, Explanations(), room_label=None, generated_at=T)
    )
    assert "<td><b>Where I&#39;m staying</b></td><td>Short stay</td>" in html


# --- E10: hidden-camera guidance -----------------------------------------------------------


def test_camera_guidance_and_help_say_the_same_steps():
    rule = next(r for r in load_rules().rules if r.id == "R-CAM")
    camera_help = STRINGS["help"]["camera"]
    # The same steps; Help names who to report to for every stay type in one line, and the
    # card's last step is in Help's small note, word for word.
    for guidance in [rule.guidance, *rule.guidance_by_stay.values()]:
        assert [guidance[0], guidance[1]] == [camera_help[k] for k in ("touch", "leave")]
        assert guidance[3] in camera_help["note"]
    assert camera_help["report"] == (
        "Report it to the police, and to whoever runs the place: the platform, the host or "
        "landlord's agent, or the management."
    )
    assert camera_help["note"] == (
        "Many platforms don't allow indoor cameras; Airbnb hasn't since 2024. "
        "Laws differ by country. This isn't legal advice."
    )


# --- B6: the physical check ----------------------------------------------------------------


def _session(tmp_path):
    return HandoverSession(BaselineStore(tmp_path / "b.db", FakeProtector()))


def test_physical_check_is_saved_encrypted_and_survives_a_restart(tmp_path):
    s = _session(tmp_path)
    s.set_physical_item("smoke_detector", True, None)
    s.set_physical_item("mirrors", None, "Bathroom mirror, no gap")
    s.finish_physical(True, now=T)
    raw = (tmp_path / "b.db").read_bytes()
    assert b"Bathroom mirror" not in raw  # encrypted
    again = _session(tmp_path)
    assert again.physical.done_at == T
    assert again.physical.items["smoke_detector"].looked is True
    assert again.physical.items["mirrors"].note == "Bathroom mirror, no gap"
    assert again.state_for(None).physical.looked == 1
    again.delete_all()
    assert _session(tmp_path).physical == PhysicalCheck()


def test_physical_items_match_the_page():
    assert list(PHYSICAL_ITEMS) == list(STRINGS["physical"]["items"])
    assert set(STRINGS["physical"]["hints"]) == set(PHYSICAL_ITEMS)
    ts = (ROOT / "web/src/api/types.ts").read_text("utf-8")
    block = re.search(r"export const PHYSICAL_ITEMS = \[(.*?)\] as const;", ts, re.S).group(1)
    assert re.findall(r'"(\w+)"', block) == list(PHYSICAL_ITEMS)


def test_the_physical_check_never_says_the_room_is_clear():
    words = json.dumps(STRINGS["physical"]) + json.dumps(STRINGS["reportPdf"])
    assert not re.search(r"\b(safe|clear|harmless|all good|nothing there)\b", words, re.I)
    assert STRINGS["physical"]["doneText"] == "Done. Note anything you weren't sure about."


@pytest.fixture
def client(no_real_baseline_store, monkeypatch):
    monkeypatch.setattr(main.app.state, "last_result", None, raising=False)
    with TestClient(main.app) as c:
        yield c


def test_physical_api_ticks_notes_and_finishes(client):
    state = client.post("/api/physical", json={"item": "clocks", "looked": True}).json()
    assert state["physical"]["items"]["clocks"] == {"looked": True, "note": ""}
    state = client.post(
        "/api/physical", json={"item": "clocks", "note": "  Clock faces the bed "}
    ).json()
    assert state["physical"]["items"]["clocks"]["note"] == "Clock faces the bed"
    assert (
        client.post("/api/physical", json={"item": "not_a_place", "looked": True}).status_code
        == 422
    )
    assert (
        client.post("/api/physical", json={"item": "clocks", "note": "<b>x</b>"}).status_code == 422
    )
    state = client.post("/api/physical/done", json={"done": True}).json()
    assert state["physical"]["done_at"]
    assert (
        client.post("/api/physical/done", json={"done": False}).json()["physical"]["done_at"]
        is None
    )


def test_the_scan_request_carries_the_stay_type():
    assert main.DiscoveryRequest(consent=False).stay == "other"
    assert main.DiscoveryRequest(consent=False, stay="hostel").stay == "hostel"
    with pytest.raises(ValueError):
        main.DiscoveryRequest(consent=False, stay="castle")


# --- F11: a report written for its reader ----------------------------------------------------


def _handover(physical: PhysicalCheck | None = None) -> HandoverState:
    return HandoverState(physical=physical or PhysicalCheck())


def _html(result, handover=None, room="Room 4B", notes=False):
    return render.render_html(
        render.build_view(
            result,
            Explanations(),
            room_label=room,
            generated_at=T,
            handover=handover,
            privacy=render.ReportPrivacy(notes=notes),
        )
    )


def test_page_one_starts_with_a_paragraph_for_the_host_then_the_tasks():
    html = _html(scan_result())
    titles = re.findall(r"<h2>(.*?)</h2>", html)
    assert titles[0] == "For the host or platform"
    assert titles.index("Physical check") < titles.index("Findings in detail")
    assert titles.index("Findings in detail") < titles.index("Is anything watching?")
    assert titles.index("Is anything watching?") < titles.index("Coverage and limits")
    para = re.search(r'<p class="for-host">(.*?)</p>', html, re.S).group(1)
    assert para.startswith("On 03 Nov 2026 I checked the devices and Wi-Fi in Room 4B")
    assert "I had permission to ask the devices on the network which services they offer." in para
    assert "I haven&#39;t done a physical check of the room." in para
    assert re.search(r"I&#39;m asking you about \d+ things?", para)


def test_a_listening_only_report_says_what_it_covered_and_what_permission_adds():
    result = scan_result()
    result.mode = "passive"
    html = _html(result)
    para = re.search(r'<p class="for-host">(.*?)</p>', html, re.S).group(1)
    assert "It was a listening-only check" in para
    assert "This was a listening-only check" in html
    assert STRINGS["results"]["listening"]["covered"] in html
    assert STRINGS["results"]["listening"]["adds"].replace("'", "&#39;") in html


def test_the_report_records_the_physical_check_and_follows_the_notes_choice():
    check = PhysicalCheck(
        items={
            "smoke_detector": PhysicalItem(looked=True),
            "mirrors": PhysicalItem(looked=True, note="No gap at the mirror"),
        },
        done_at=T,
    )
    html = _html(scan_result(), _handover(check), notes=False)
    assert "Done on 03 Nov 2026. 2 of 8 places looked at." in html
    assert "Smoke detector · Mirrors" in html
    assert "No gap at the mirror" not in html
    assert "1 note left out" in html
    para = re.search(r'<p class="for-host">(.*?)</p>', html, re.S).group(1)
    assert "I also looked around the room in person on 03 Nov 2026." in para
    html = _html(scan_result(), _handover(check), notes=True)
    assert "<li>Mirrors: No gap at the mirror</li>" in html


def test_without_a_room_label_the_paragraph_still_reads():
    para = re.search(r'<p class="for-host">(.*?)</p>', _html(scan_result(), room=None), re.S)
    assert para.group(1).startswith(
        "On 03 Nov 2026 I checked the devices and Wi-Fi where I&#39;m staying"
    )


# --- A1: the summary sentence --------------------------------------------------------------


def test_the_summary_sentence_is_the_top_finding_and_its_strongest_clue():
    result = scan_result()
    line = top_line(result, question_statuses(result))
    assert line == "Likely camera: it offers a live video stream, the kind security cameras use."
    html = _html(result)
    banner = re.search(r'<div class="banner">(.*?)</div>', html, re.S).group(1)
    assert line in banner


def test_no_country_specific_law_anywhere_the_user_reads():
    """Laws differ by country: the app, its strings, the report and the README name none."""
    texts = [
        ROOT / "web/src/strings/en.json",
        ROOT / "app/rules/rules.yaml",
        ROOT / "app/handover/tasks.yaml",
        ROOT / "app/report/templates/report.html.j2",
        ROOT / "README.md",
    ]
    for path in texts:
        body = path.read_text("utf-8")
        assert not re.search(r"Singapore|Penal Code|Misuse Act|section \d+[A-Z]*", body), path
    legal = STRINGS["start"]["permission"]["legal"]
    assert legal == (
        "Checking devices on a network without permission may be against the law in many places."
    )
    assert STRINGS["help"]["camera"]["note"].endswith("This isn't legal advice.")


# --- the summary's clue: the plainest, not the strongest --------------------------------------


def test_every_clue_has_a_plain_rank_and_the_camera_order_is_fixed():
    signals = {s.id: s for spec in load_weights().types.values() for s in spec.signals}
    assert all(1 <= s.plain_rank <= 5 for s in signals.values())
    # Live video stream > name > maker > ONVIF / discovery.
    ranks = [
        signals[i].plain_rank for i in ("rtsp_server", "camera_name", "camera_vendor", "onvif_nvt")
    ]
    assert ranks == sorted(ranks) and len(set(ranks)) == 4


def test_the_summary_leads_with_the_plainest_clue_and_scores_dont_change():
    cam = dev.hikvision_camera()
    cam.hostnames = ["cam-hallway"]
    cam.fingerprint = fingerprint(device_facts(cam), "full")
    (f,) = [x for x in evaluate(RoomFacts(devices=[cam], network=NET)) if x.rule_id == "R-CAM"]
    assert f.lead_clue == "It offers a live video stream, the kind security cameras use."
    assert (
        f.clues[0] == "It answers camera discovery requests (ONVIF)."
    )  # the card: strongest first
    # Without a video stream, the name leads; without a name, the maker.
    cam.identity.rtsp = []
    cam.fingerprint = fingerprint(device_facts(cam), "full")
    (f,) = [x for x in evaluate(RoomFacts(devices=[cam], network=NET)) if x.rule_id == "R-CAM"]
    assert f.lead_clue == "It calls itself “cam-hallway”."
    cam.hostnames = []
    cam.fingerprint = fingerprint(device_facts(cam), "full")
    (f,) = [x for x in evaluate(RoomFacts(devices=[cam], network=NET)) if x.rule_id == "R-CAM"]
    assert f.lead_clue == "Its maker mostly sells cameras."


def test_plain_rank_never_changes_a_score():
    cam = dev.hikvision_camera()
    before = fingerprint(device_facts(cam), "full")
    weights = load_weights()
    for spec in weights.types.values():
        for s in spec.signals:
            assert s.weight > 0  # weights unchanged by this pass; rank is a separate field
    assert before.confidence == fingerprint(device_facts(cam), "full").confidence
    assert {e.signal: e.weight for e in before.evidence} == {
        "onvif_nvt": 0.6,
        "rtsp_server": 0.5,
        "camera_ports": 0.3,
        "camera_vendor": 0.3,
    }


# --- item 3: "Where is it?" and who to report to ----------------------------------------------


def _camera_finding(stay):
    (f,) = [
        x
        for x in evaluate(RoomFacts(devices=[camera()], network=NET, stay=stay))
        if x.rule_id == "R-CAM"
    ]
    return f


def test_hidden_camera_guidance_names_the_right_people_for_the_stay():
    report_line = {
        stay: _camera_finding(stay).guidance[2]
        for stay in ("short_stay", "rental", "hostel", "other")
    }
    assert report_line == {
        "short_stay": "Report it to the platform and the police.",
        "rental": "Report it to the host or the landlord's agent, and the police.",
        "hostel": "Report it to the management and the police.",
        "other": "Report it to the host and the police.",
    }


def test_where_is_it_picks_the_next_step_and_the_message_for_the_stay():
    from app.handover.tasks import adjusted_steps

    def step(location, stay):
        return adjusted_steps(_camera_finding(stay), None, location=location, stay=stay)

    inside = step("inside", "short_stay")
    assert inside.next_step == (
        "Many platforms don't allow indoor cameras. "
        "Report it to the platform and keep your evidence."
    )
    assert inside.draft == "platform"
    outside = step("outside", "rental")
    assert outside.next_step.startswith("Check your tenancy agreement for a disclosed camera.")
    assert outside.draft == "host"
    assert "listing or tenancy agreement" in step("outside", None).next_step
    assert step("unknown", "short_stay").next_step == (
        "Ask the host what it is, where it is and who can view it."
    )
    assert "front desk or management" in step("inside", "hostel").next_step
    # "Mine" wins: nothing to ask or report.
    mine = adjusted_steps(_camera_finding("short_stay"), "mine", location="inside")
    assert mine.draft == "host" and "You said this is yours" in mine.next_step
    # Only cameras ask where they are.
    assert {r.id for r in load_rules().rules if r.next_step_by_location} == {
        "R-CAM",
        "R-NEW-CAMERA",
    }


def test_where_is_it_is_saved_and_changes_the_cards_steps(tmp_path):
    s = _session(tmp_path)
    s.salt = demo_data.SALT
    result = demo_data.full_check()
    cam = next(f for f in result.findings if f.rule_id == "R-CAM")
    s.set_location(cam.subject, "inside")
    again = _session(tmp_path)
    assert again.locations == {cam.subject: "inside"}
    again.salt = demo_data.SALT
    adjusted = again.state_for(result).adjusted[cam.id]
    assert adjusted.draft == "platform" and "Report it to the platform" in adjusted.next_step
    again.set_location(cam.subject, None)
    assert cam.id not in again.state_for(result).adjusted
    again.delete_all()
    assert _session(tmp_path).locations == {}


def test_locations_api(client):
    ok = client.post("/api/locations", json={"subject": "device:mac:x", "location": "outside"})
    assert ok.json()["locations"] == {"device:mac:x": "outside"}
    bad = client.post("/api/locations", json={"subject": "device:mac:x", "location": "attic"})
    assert bad.status_code == 422


# --- item 2: the paragraph for the host counts the tasks it lists -------------------------------


def _open_rows(html: str) -> int:
    table = re.search(r"<h2>What I&#39;m asking, and its status</h2>(.*?)</table>", html, re.S)
    rows = re.findall(r"<tr><td>.*?</td><td>(.*?)</td><td>(.*?)</td>", table.group(1), re.S)
    return sum(1 for who, status in rows if status != "Resolved" and who != "You")


def test_the_host_paragraph_counts_exactly_the_open_tasks_listed_below_it():
    files = demo_data.build()
    for handover in (files["handover"], files["handover_report"]):
        html = render.render_html(
            render.build_view(
                files["result_full"],
                files["result_full"].explanations,
                room_label="Room 4B",
                generated_at=T,
                handover=handover,
            )
        )
        para = re.search(r'<p class="for-host">(.*?)</p>', html, re.S).group(1)
        asked = int(re.search(r"asking you about (\d+) thing", para).group(1))
        # Three asks for the host; the tracker task is the user's own.
        assert asked == _open_rows(html) == 3


def test_the_demo_pdf_is_made_with_the_handover_data():
    from tests.fixtures.report.make_demo_preview import view

    v = view()
    assert v["tasks"] and "asking you about 3 things" in v["for_host"]
    assert "I also looked around the room in person" in v["for_host"]
