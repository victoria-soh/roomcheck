"""This set's backend: tracker wording (rules, tasks, AI prompt and validator), rechecking a
handover task where RoomCheck can observe the fix, the "Host confirmed" and "Observed by
RoomCheck" labels, and the logo and wordmark font in the PDF report. No real scans run."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.baseline.compare import assign_subjects
from app.discovery.messages import message_for
from app.discovery.models import CheckStatus, DiscoveryResult
from app.explain import ai, validator
from app.explain.models import Explanations
from app.handover import recheck as rc
from app.handover import tasks as task_rules
from app.handover.models import Recheck
from app.report import render
from app.rules.engine import RoomFacts, evaluate, load_rules
from app.wireless.models import NearbySurvey, WpsInfo
from app.wireless.survey import flagged_items
from tests.unit import devices as dev
from tests.unit.test_layer6 import SALT, scored
from tests.unit.test_nearby_rules import CONNECTED, OPEN, PHONE_HOTSPOT, ROUTER, ap
from tests.unit.test_rules import NET

T = datetime(2026, 11, 21, 10, 0, tzinfo=UTC)
WPS = WpsInfo(state="configured")

# --- tracker wording ----------------------------------------------------------------------------


def test_the_tracker_rule_asks_instead_of_saying_whose_it_is():
    rule = next(r for r in load_rules().rules if r.id == "R-TRACKER")
    assert rule.title == "Item tracker nearby"
    assert rule.next_step == (
        "If it isn't yours, find it with the locator; a phone's built-in "
        "unknown-tracker alert gives a second opinion."
    )  # the card asks "Do you recognise this?" itself, so the step doesn't repeat it
    assert (
        rule.why_it_matters == "A tracker you don't recognise could be used to follow where you go."
    )


def test_no_rule_or_task_text_says_whose_something_is():
    texts = []
    for r in load_rules().rules:
        for field in ("title", "observed", "next_step", "explanation", "why_it_matters"):
            v = getattr(r, field)
            texts += list(v.values()) if isinstance(v, dict) else [v]
        texts += r.guidance
    t = task_rules.load_templates()
    for tpl in t.templates.values():
        texts += [tpl.title, tpl.ask, *tpl.steps]
    for c in t.categories.values():
        texts += c["steps"]
    # A condition isn't a claim: R-TRACKER's "If it isn't yours, ..." says nothing about whose
    # it is. AI text is still held to the full rule (the validator is unchanged).
    texts = [x.replace("If it isn't yours,", "If so,") for x in texts]
    assert [x for x in texts if validator._OWNERSHIP.search(x)] == []


@pytest.mark.parametrize(
    "text",
    [
        "This tracker isn't yours, so find it.",
        "The tracker is not yours.",
        "It doesn't seem to belong to you.",
        "It belongs to someone else.",
        "This could be someone else's tracker.",
    ],
)
def test_the_validator_rejects_ownership_claims(text):
    assert validator.problem_with_text(text, "Medium", "R-TRACKER") == "ownership_claim"


def test_the_validator_accepts_asking():
    text = (
        "Do you recognise this tracker? A tracker you don't recognise could be used to follow you."
    )
    assert validator.problem_with_text(text, "Medium", "R-TRACKER") is None


def test_the_ai_prompt_forbids_ownership_claims():
    assert "Never say or suggest whose a device or tracker is" in ai.SYSTEM_PROMPT
    assert '"Do you recognise this tracker?"' in ai.SYSTEM_PROMPT


# --- recheck: which tasks offer it --------------------------------------------------------------


@pytest.mark.parametrize(
    "rule_id, status, host_confirmed, offer",
    [
        ("R-WPS", "todo", False, "needs_status"),
        ("R-WPS", "asked", False, "needs_status"),
        ("R-WPS", "resolved", False, "available"),
        ("R-WPS", "asked", True, "available"),  # Host confirmed evidence
        ("R-TELNET", "resolved", False, "available"),
        ("R-UPNP", "todo", True, "available"),
        ("R-CAM", "resolved", False, "available"),
        ("R-TWIN", "resolved", False, "available"),
        ("R-LOCK", "resolved", True, "unobservable"),
        ("R-CLOUD", "todo", False, "unobservable"),
        ("R-CVE", "resolved", False, "unobservable"),
        ("R-DNS", "resolved", False, "none"),
    ],
)
def test_recheck_is_offered_only_where_roomcheck_can_observe_the_fix(
    rule_id, status, host_confirmed, offer
):
    assert task_rules.recheck_offer(rule_id, status, host_confirmed) == offer


# --- recheck: the Wi-Fi survey ------------------------------------------------------------------


def nearby_result(aps, mode="full"):
    survey = NearbySurvey(room=CONNECTED, access_points=list(aps), wifi_method="wlanapi")
    findings = evaluate(RoomFacts(devices=[], network=None, nearby=survey))
    result = DiscoveryResult(
        started_at=T,
        finished_at=T,
        mode=mode,
        network=None,
        devices=[],
        checks=[],
        findings=findings,
        nearby_items=flagged_items(survey, findings, SALT),
        room_network="HomeNet",
    )
    assign_subjects(result, SALT)
    return result


def task_for(result, rule_id, status="resolved"):
    tasks = task_rules.build_tasks(result, {}, {})
    task = next(t for t in tasks if t.rule_id == rule_id)
    return task.model_copy(update={"status": status})


def wifi(aps, room=CONNECTED, failed=False):
    def collect(typed):
        survey = NearbySurvey(
            room=room, access_points=None if failed else list(aps), wifi_method="wlanapi"
        )
        return survey, [], ["Windows needs Location turned on."] if failed else []

    return rc.Collectors(wifi=collect, devices=lambda consent: pytest.fail("no device check"))


def test_wps_off_is_observed():
    result = nearby_result([ap(ROUTER, wps=WPS, rssi=-40)])
    task = task_for(result, "R-WPS")
    got = rc.recheck(task, result, salt=SALT, collectors=wifi([ap(ROUTER, rssi=-40)]), now=T)
    assert (got.outcome, got.text, got.observed) == (
        "fixed",
        "WPS is now off on that router.",
        True,
    )


def test_wps_still_on_or_router_not_heard():
    result = nearby_result([ap(ROUTER, wps=WPS, rssi=-40)])
    task = task_for(result, "R-WPS")
    still = rc.recheck(task, result, salt=SALT, collectors=wifi([ap(ROUTER, wps=WPS, rssi=-40)]))
    assert (still.outcome, still.observed) == ("still_there", False)
    gone = rc.recheck(task, result, salt=SALT, collectors=wifi([]))
    assert gone.outcome == "couldnt_check" and "wasn't heard" in gone.text


def test_a_lookalike_network_gone_is_observed():
    result = nearby_result([ap(ROUTER), ap(PHONE_HOTSPOT, sec=OPEN, rssi=-45)])
    task = task_for(result, "R-TWIN")
    gone = rc.recheck(task, result, salt=SALT, collectors=wifi([ap(ROUTER)]))
    assert (gone.outcome, gone.observed) == ("gone", True)
    again = [ap(ROUTER), ap(PHONE_HOTSPOT, sec=OPEN, rssi=-45)]
    assert rc.recheck(task, result, salt=SALT, collectors=wifi(again)).outcome == "still_there"


def test_a_failed_survey_or_unknown_room_network_never_reads_as_fixed():
    result = nearby_result([ap(ROUTER, wps=WPS, rssi=-40)])
    task = task_for(result, "R-WPS")
    failed = rc.recheck(task, result, salt=SALT, collectors=wifi([], failed=True))
    assert (failed.outcome, failed.text) == ("couldnt_check", "Windows needs Location turned on.")
    no_room = rc.recheck(task, result, salt=SALT, collectors=wifi([ap(ROUTER)], room=None))
    assert no_room.outcome == "couldnt_check"


# --- recheck: device discovery ------------------------------------------------------------------


def device_result(devices, mode="full"):
    findings = evaluate(RoomFacts(devices=list(devices), network=NET))
    result = DiscoveryResult(
        started_at=T,
        finished_at=T,
        mode=mode,
        network=NET,
        devices=list(devices),
        checks=[],
        findings=findings,
    )
    assign_subjects(result, SALT)
    return result


def telnet_router(ports=(23, 80)):
    d = dev.tp_link_gateway()
    d.identity.open_ports = list(ports)
    return scored(d)


def devices(found, checks=("ssdp", "port_check")):
    def collect(consent):
        return DiscoveryResult(
            started_at=T,
            finished_at=T,
            mode="full" if consent else "passive",
            network=NET,
            devices=list(found),
            checks=[CheckStatus(name=n, label=n, status="ran") for n in checks],
        )

    return rc.Collectors(wifi=lambda typed: pytest.fail("no Wi-Fi check"), devices=collect)


def test_telnet_closed_is_observed_and_still_open_is_said():
    result = device_result([telnet_router()])
    task = task_for(result, "R-TELNET")
    fixed = rc.recheck(task, result, salt=SALT, collectors=devices([telnet_router(ports=(80,))]))
    assert (fixed.outcome, fixed.text) == ("fixed", "Telnet is now closed on that device.")
    still = rc.recheck(task, result, salt=SALT, collectors=devices([telnet_router()]))
    assert still.outcome == "still_there"


def test_telnet_cant_be_judged_without_the_device_or_the_port_check():
    result = device_result([telnet_router()])
    task = task_for(result, "R-TELNET")
    assert rc.recheck(task, result, salt=SALT, collectors=devices([])).outcome == "couldnt_check"
    no_ports = devices([telnet_router(ports=(80,))], checks=("ssdp",))
    assert rc.recheck(task, result, salt=SALT, collectors=no_ports).outcome == "couldnt_check"


def test_active_rechecks_need_a_check_with_permission():
    result = device_result([telnet_router()], mode="passive")
    task = task_for(result, "R-TELNET")
    got = rc.recheck(task, result, salt=SALT, collectors=devices([]))
    assert got.outcome == "needs_permission"


def test_a_camera_gone_is_observed_with_a_caveat():
    cam = scored(dev.hikvision_camera())
    result = device_result([cam])
    task = task_for(result, "R-CAM")
    gone = rc.recheck(task, result, salt=SALT, collectors=devices([]))
    assert gone.outcome == "gone" and "A quiet device can be missed" in gone.text
    here = rc.recheck(task, result, salt=SALT, collectors=devices([scored(dev.hikvision_camera())]))
    assert here.outcome == "still_there"


# --- labels, the API and the report -------------------------------------------------------------


def test_host_confirmed_and_observed_are_separate_labels(tmp_path):
    from app.baseline.store import BaselineStore
    from app.handover.session import HandoverSession
    from tests.conftest import FakeProtector

    s = HandoverSession(BaselineStore(tmp_path / "b.db", FakeProtector()))
    s.salt = SALT
    result = nearby_result([ap(ROUTER, wps=WPS, rssi=-40)])
    task = task_for(result, "R-WPS", status="todo")
    s.update_task(task.id, "asked", None, now=T, host_confirmed=True)
    got = next(t for t in s.state_for(result).tasks if t.id == task.id)
    assert (got.status, got.host_confirmed, got.observed, got.recheck_offer) == (
        "asked",
        True,
        False,
        "available",
    )
    s.save_recheck(task.id, Recheck(outcome="still_there", text="WPS is still on.", checked_at=T))
    s.save_recheck(
        task.id, Recheck(outcome="fixed", text="WPS is now off on that router.", checked_at=T)
    )
    got = next(t for t in s.state_for(result).tasks if t.id == task.id)
    # Status and evidence stay apart; every recheck is recorded, the latest one counts.
    assert (got.status, got.host_confirmed, got.observed, got.observed_at) == (
        "asked",
        True,
        True,
        T,
    )
    assert [r.outcome for r in got.rechecks] == ["still_there", "fixed"]
    html = render.render_html(
        render.build_view(
            result, Explanations(), room_label=None, generated_at=T, handover=s.state_for(result)
        )
    )
    assert "<td>Asked</td>" in html
    assert "Host confirmed (" in html and "Observed by RoomCheck (" in html
    assert "WPS is still on." in html and "WPS is now off on that router." in html


def test_the_report_says_when_roomcheck_cant_check_a_fix():
    from app.handover.models import HandoverState

    task = task_rules.Task(
        id="R-LOCK|device:x",
        finding_id="R-LOCK:x",
        rule_id="R-LOCK",
        subject="device:x",
        severity="Medium",
        finding_title="Smart lock or doorbell",
        title="Ask who can open the lock",
        ask="Who can open the smart lock?",
        who="landlord_or_host",
        steps=[],
        recheck_offer="unobservable",
    )
    view = render.build_view(
        device_result([]),
        Explanations(),
        room_label=None,
        generated_at=T,
        handover=HandoverState(tasks=[task]),
    )
    html = render.render_html(view)
    assert "RoomCheck can't check this. It relies on the host's confirmation." in html


@pytest.fixture
def client(no_real_baseline_store, monkeypatch):
    monkeypatch.setattr(main.app.state, "last_result", None, raising=False)
    with TestClient(main.app) as c:
        yield c


def test_api_recheck_runs_only_when_offered(client, monkeypatch):
    result = nearby_result([ap(ROUTER, wps=WPS, rssi=-40)])
    main.app.state.last_result = result
    session = main._handover(main.app.state)
    session.salt = SALT
    task = next(t for t in session.state_for(result).tasks if t.rule_id == "R-WPS")
    url = f"/api/tasks/{task.id}/recheck"
    assert client.post(url).status_code == 409  # still To do
    client.patch(f"/api/tasks/{task.id}", json={"status": "resolved"})
    monkeypatch.setattr(rc, "real_collectors", lambda scanner: wifi([ap(ROUTER, rssi=-40)]))
    body = client.post(url).json()
    got = next(t for t in body["tasks"] if t["id"] == task.id)
    assert got["observed"] is True and got["recheck"]["outcome"] == "fixed"


def test_api_recheck_waits_for_a_running_check(client, monkeypatch):
    result = nearby_result([ap(ROUTER, wps=WPS, rssi=-40)])
    main.app.state.last_result = result
    session = main._handover(main.app.state)
    task = next(t for t in session.state_for(result).tasks if t.rule_id == "R-WPS")
    session.update_task(task.id, "resolved", None)
    monkeypatch.setattr(main.app.state.scan_jobs, "busy", lambda: True)
    assert client.post(f"/api/tasks/{task.id}/recheck").status_code == 409


def test_the_report_header_has_the_mark_and_an_embedded_wordmark_font():
    result = device_result([])
    html = render.render_html(
        render.build_view(result, Explanations(), room_label=None, generated_at=T)
    )
    assert render.MARK_PATH in html and 'fill="#1BA9A6"' in html
    assert '<span class="wordmark">RoomCheck</span>' in html
    assert "src: url(data:font/woff2;base64," in html  # embedded: the renderer fetches nothing
    assert "fonts.googleapis" not in html and "fonts.gstatic" not in html


# --- "Help identify this": the optional note ----------------------------------------------------


def test_notes_are_plain_short_text():
    from app.handover.models import clean_note

    assert (
        clean_note("  White box   above the TV \n by the window ")
        == "White box above the TV\nby the window"
    )
    for bad in ("x" * 201, "<b>x</b>", "tab\there"):
        with pytest.raises(ValueError):
            clean_note(bad)


def test_names_api_saves_a_note_and_the_report_shows_it_escaped(client):
    from tests.unit.test_layer6 import camera, check

    main.app.state.last_result = check([camera()])
    subject = next(f.subject for f in main.app.state.last_result.findings)
    body = client.post(
        "/api/names", json={"subject": subject, "name": "Hall cam", "note": "Above the door & TV"}
    ).json()
    assert body["notes"] == {subject: "Above the door & TV"}
    bad = client.post("/api/names", json={"subject": subject, "name": "", "note": "<i>x</i>"})
    assert (bad.status_code, bad.json()["detail"]) == (422, message_for("note_invalid"))
    # Leaving the note out keeps it.
    kept = client.post("/api/names", json={"subject": subject, "name": "Hall camera"}).json()
    assert kept["notes"] == {subject: "Above the door & TV"}
    state = main._handover(main.app.state).state_for(main.app.state.last_result)
    html = render.render_html(
        render.build_view(
            main.app.state.last_result,
            Explanations(),
            room_label=None,
            generated_at=T,
            handover=state,
            privacy=render.ReportPrivacy(notes=True),  # notes are off unless chosen
        )
    )
    assert "Your note: Above the door &amp; TV" in html
