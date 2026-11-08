"""Correctness and trust fixes: where findings live, evidence vs inference in every text, tasks
that ask only for what their finding supports, handover data saved on its own, status vs
evidence (with the migration of saved values), Compare that never mistakes "not checked" for
"gone", the report's two service choices, and the four Verify outcomes."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.baseline.compare import compare, snapshot
from app.baseline.store import BaselineStore
from app.coverage import coverage
from app.discovery.models import CheckStatus, CoverageItem
from app.explain import ai, validator
from app.explain.models import Explanations
from app.handover import tasks as task_rules
from app.handover.models import TaskState
from app.handover.session import HandoverSession
from app.report import render, tamper
from app.rules.engine import load_rules
from tests.conftest import FakeProtector
from tests.unit import devices as dev
from tests.unit.test_layer6 import SALT, T0, T1, camera, check, scored
from tests.unit.test_nearby_rules import ROUTER, ap
from tests.unit.test_recheck_and_wording import WPS, nearby_result
from tests.unit.test_report import CACERT, SAMPLE_PDF, SAMPLE_TSR, scan_result

T = datetime(2026, 11, 22, 9, 0, tzinfo=UTC)

# --- 2. scope: your network vs nearby signals -----------------------------------------------------


def test_wps_on_your_router_is_shown_with_your_network():
    result = nearby_result([ap(ROUTER, wps=WPS, rssi=-40)])
    wps = next(f for f in result.findings if f.rule_id == "R-WPS")
    assert (wps.scope, wps.shown_on) == ("nearby", "results")  # judged from the survey
    assert wps.subject and wps.subject.startswith("wifi:")  # rechecks still find it


def test_every_rule_about_your_own_network_is_shown_on_results():
    rules = {r.id: r for r in load_rules().rules}
    assert rules["R-WIFI-ENC"].scope == "network"
    on_results = {r.id for r in rules.values() if r.scope != "nearby" or r.about_your_network}
    assert {"R-WPS", "R-WIFI-ENC", "R-UPNP", "R-DNS", "R-ARP", "R-DHCP"} <= on_results
    # Lookalikes, hidden or open networks, camera hotspots and trackers are other signals.
    assert (
        not {
            "R-TWIN",
            "R-TWIN-VENDOR",
            "R-TWIN-DOWNGRADE",
            "R-HIDDEN",
            "R-OPEN",
            "R-CAMHOT",
            "R-TRACKER",
        }
        & on_results
    )


# --- 3. evidence vs inference ---------------------------------------------------------------------


def test_wps_says_what_was_observed_and_the_pin_risk_as_possible():
    wps = next(r for r in load_rules().rules if r.id == "R-WPS")
    assert wps.title == "Router advertises WPS"
    assert wps.observed == "The router's Wi-Fi broadcast says WPS is on."
    assert wps.why_it_matters.startswith(
        "If PIN-based WPS is enabled, the PIN could be guessed by trying many codes"
    )
    assert "brute" not in " ".join(wps.next_step.split())


UNHEDGED = [
    "can be guessed",
    "open to pin brute",
    "look tampered",
    "lets devices open",
    "people nearby can read",
    "is run through an online account",
    "hands out",
]


def test_no_rule_states_an_inference_as_fact():
    for r in load_rules().rules:
        for field in ("title", "observed", "next_step", "explanation", "why_it_matters"):
            v = getattr(r, field)
            for text in v.values() if isinstance(v, dict) else [v]:
                low = " ".join(text.lower().split())
                assert not [u for u in UNHEDGED if u in low], (r.id, field, text)


def test_no_task_states_an_inference_as_fact():
    t = task_rules.load_templates()
    for rule_id, tpl in t.templates.items():
        for text in [tpl.title, tpl.ask, *tpl.steps]:
            low = text.lower()
            assert not [u for u in UNHEDGED if u in low], (rule_id, text)


def test_the_validator_rejects_an_unhedged_wps_claim_and_keeps_a_conditional_one():
    assert validator.problem_with_text("The WPS PIN can be guessed.", "Medium", "R-WPS") == (
        "unconfirmed_claim"
    )
    assert validator.problem_with_text("It is open to PIN brute-forcing.", "Medium", "R-WPS")
    ok = "Your router advertises WPS. If PIN-based WPS is enabled, the PIN could be guessed."
    assert validator.problem_with_text(ok, "Medium", "R-WPS") is None


def test_the_ai_prompt_asks_for_observations_as_fact_and_inferences_as_possible():
    assert "Say what was observed as fact, and anything inferred from it as possible" in (
        ai.SYSTEM_PROMPT
    )


# --- 4. task accuracy -----------------------------------------------------------------------------


def test_the_wps_task_asks_only_about_wps():
    wps = task_rules.load_templates().templates["R-WPS"]
    steps = task_rules.load_templates().steps_for("R-WPS")
    assert not any("password" in s for s in [wps.ask, *steps])
    assert all("WPS" in s for s in [wps.ask, *steps])
    assert wps.optional == []


def test_an_optional_suggestion_stays_apart_from_the_task_and_the_message():
    result = check([camera()])
    enc = next(r for r in load_rules().rules if r.id == "R-WIFI-ENC")
    assert enc  # the rule exists; its template carries the only optional suggestion
    templates = task_rules.load_templates().templates
    with_optional = {k for k, v in templates.items() if v.optional}
    assert with_optional == {"R-WIFI-ENC"}
    (s,) = templates["R-WIFI-ENC"].optional
    assert s.text.startswith("You could also") and s.reason
    tasks = task_rules.build_tasks(result, {}, {})
    message = task_rules.bundle_message(tasks, None)
    assert message is not None and "password" not in message.text


# --- 5. handover saving on its own ----------------------------------------------------------------


def session(path):
    return HandoverSession(BaselineStore(path, FakeProtector()))


def test_tasks_statuses_and_notes_are_saved_without_a_move_in_scan(tmp_path):
    path = tmp_path / "b.db"
    s = session(path)
    result = check([camera()], at=T0)
    task = s.state_for(result).tasks[0]
    s.update_task(task.id, "asked", "Emailed the host", now=T1, check_at=result.started_at)
    state = s.state_for(result)
    assert (state.storage, state.storage_reason, state.saved) == ("saved", None, False)
    assert path.exists() and b"Emailed" not in path.read_bytes()  # encrypted
    again = session(path)
    assert again.salt == s.salt  # the same devices match next time
    (t,) = [x for x in again.state_for(result).tasks if x.id == task.id]
    assert (t.status, t.notes, t.changed_at, t.check_at) == ("asked", "Emailed the host", T1, T0)


def test_a_failed_save_says_not_saved_with_the_reason(tmp_path, monkeypatch):
    s = session(tmp_path / "b.db")
    result = check([camera()])
    task = s.state_for(result).tasks[0]

    def full(values):
        raise OSError("disk full")

    monkeypatch.setattr(s.store, "write", full)
    s.update_task(task.id, None, "A note")
    state = s.state_for(result)
    assert state.storage == "not_saved"
    assert state.storage_reason and "couldn't write" in state.storage_reason
    assert "disk full" not in state.storage_reason  # plain words, not the raw error


def test_deleting_the_baseline_keeps_the_handover_data(tmp_path):
    path = tmp_path / "b.db"
    s = session(path)
    result = check([camera()])
    task = s.state_for(result).tasks[0]
    s.save_baseline(result, now=T0)
    s.update_task(task.id, "asked", "Kept", now=T1)
    s.delete_baseline()
    again = session(path)
    assert again.info().state == "none"
    assert next(t for t in again.state_for(result).tasks if t.id == task.id).notes == "Kept"


# --- 6. status vs evidence, and the migration -----------------------------------------------------


def test_saved_values_from_before_are_migrated():
    assert TaskState.model_validate({"status": "done"}).status == "resolved"
    old = TaskState.model_validate({"status": "confirmed", "changed_at": T.isoformat()})
    assert (old.status, old.host_confirmed, old.host_confirmed_at) == ("asked", True, T)
    recheck = {
        "outcome": "fixed",
        "text": "WPS is now off on that router.",
        "checked_at": T.isoformat(),
    }
    moved = TaskState.model_validate({"status": "done", "recheck": recheck})
    assert [r.outcome for r in moved.rechecks] == ["fixed"]


def test_an_old_store_opens_with_migrated_tasks(tmp_path):
    path = tmp_path / "b.db"
    result = check([camera()])
    first = session(path)
    task = first.state_for(result).tasks[0]
    # A value saved by the earlier version of RoomCheck.
    first.store.write({"salt": first.salt.hex(), "tasks": {task.id: {"status": "confirmed"}}})
    t = next(x for x in session(path).state_for(result).tasks if x.id == task.id)
    assert (t.status, t.host_confirmed, t.open) == ("asked", True, False)


def test_host_confirmed_is_evidence_and_leaves_the_message():
    result = check([camera()])
    tasks = task_rules.build_tasks(result, {}, {})
    cam = tasks[0]
    states = {cam.id: TaskState(status="asked", host_confirmed=True)}
    (again,) = task_rules.build_tasks(result, {}, states)
    assert (again.status, again.host_confirmed, again.recheck_offer) == ("asked", True, "available")
    assert task_rules.bundle_message([again], None) is None  # the host has answered


@pytest.fixture
def client(no_real_baseline_store, monkeypatch, tmp_path):
    monkeypatch.setattr(render, "render_pdf", lambda html: SAMPLE_PDF)
    monkeypatch.setattr(main.app.state, "report_dir", tmp_path, raising=False)
    monkeypatch.setattr(main.app.state, "last_result", None, raising=False)
    with TestClient(main.app) as c:
        yield c


def test_api_records_host_confirmed_and_the_check_it_came_from(client):
    from urllib.parse import quote

    main.app.state.last_result = check([camera()], at=T0)
    task = client.get("/api/handover").json()["tasks"][0]
    body = client.patch(
        f"/api/tasks/{quote(task['id'], safe='')}", json={"host_confirmed": True}
    ).json()
    t = body["tasks"][0]
    assert (t["status"], t["host_confirmed"], t["recheck_offer"]) == ("todo", True, "available")
    assert t["host_confirmed_at"] and t["check_at"].startswith("2026-11-03")
    assert body["storage"] == "saved"
    assert (
        client.patch(
            f"/api/tasks/{quote(task['id'], safe='')}", json={"status": "done"}
        ).status_code
        == 422
    )


# --- 7. Compare -----------------------------------------------------------------------------------


def _with_coverage(result, **states):
    rows = [
        CoverageItem(area=a, label=a.title(), state=states.get(a, "completed"))
        for a in ("devices", "services", "router", "known_issues", "nearby_wifi", "bluetooth")
    ]
    result.coverage = rows
    return result


def test_a_mode_or_coverage_difference_is_said_at_the_top():
    base_result = _with_coverage(check([camera()], at=T0))
    baseline = snapshot(base_result, SALT, T0)
    assert (baseline.mode, len(baseline.coverage)) == ("full", 6)
    later = _with_coverage(check([camera()], at=T1), services="limited")
    later.mode = "passive"
    later.coverage[1].reason = "listening only, no permission to check services"
    out = compare(baseline, later, SALT)
    # One plain note (the page's "These checks ran differently, …"), not a list of what
    # followed from it.
    assert out.ran_differently is True
    assert out.warnings == []
    # The same coverage gap with both checks run the same way is listed on its own.
    same = _with_coverage(check([camera()], at=T1), services="limited")
    same.coverage[1].reason = "the service check timed out"
    out = compare(baseline, same, SALT)
    assert out.ran_differently is False
    assert any("Services was only partly checked this time" in w for w in out.warnings)


def test_a_port_or_finding_that_wasnt_checked_is_never_shown_as_removed():
    router = scored(dev.tp_link_gateway())
    router.identity.open_ports = [23, 80]
    baseline = snapshot(_with_coverage(check([router], at=T0)), SALT, T0)
    later_router = scored(dev.tp_link_gateway())
    later_router.identity = None  # a listening-only check: its services weren't looked at
    later = _with_coverage(check([later_router], at=T1), services="not_run")
    out = compare(baseline, later, SALT)
    changes = [c for item in out.changed for c in item.changes]
    assert not [
        c for c in changes if "No longer open" in c or "No longer found: Device offers Telnet" in c
    ]


def test_a_network_finding_not_checked_this_time_isnt_not_seen():
    result = check([camera()], at=T0)
    from app.rules.models import Finding

    upnp = Finding(
        id="R-UPNP:network",
        rule_id="R-UPNP",
        scope="network",
        severity="Medium",
        confidence_band="Likely",
        device_ref=None,
        title="Router offers UPnP controls",
        evidence=[],
        next_step="Ask.",
    )
    result.findings.append(upnp)
    baseline = snapshot(_with_coverage(result), SALT, T0)
    later = _with_coverage(check([camera()], at=T1), devices="limited")
    out = compare(baseline, later, SALT)
    assert out.not_checked == ["Router offers UPnP controls"]
    assert not [g for g in out.gone if g.kind == "network"]


# --- 8. the report's service choices --------------------------------------------------------------


def test_report_choices_and_each_service_outcome(client, monkeypatch):
    main.app.state.last_result = scan_result()
    monkeypatch.setattr(tamper, "request_token", lambda digest, url: SAMPLE_TSR)
    both = client.post("/api/report", json={"ai": True, "timestamp": True}).json()
    # No API key in tests: AI isn't requested even when chosen.
    assert both["ai"] == {"state": "not_requested", "reason": None}
    assert both["timestamp"] == {"state": "added", "reason": None}
    none = client.post("/api/report", json={"ai": False, "timestamp": False}).json()
    assert none["timestamp"] == {"state": "not_requested", "reason": None} and none["tsr"] is None

    def down(digest, url):
        raise tamper.TimestampUnavailable("offline")

    monkeypatch.setattr(tamper, "request_token", down)
    failed = client.post("/api/report", json={"timestamp": True}).json()
    assert failed["timestamp"]["state"] == "unavailable" and failed["timestamp"]["reason"]
    assert failed["tsr"] is None and failed["timestamped_at"] is None  # never promised


def test_ai_unchosen_sends_nothing_and_failed_says_why(client, monkeypatch):
    from pydantic import SecretStr

    from app.config import Settings

    main.app.state.last_result = scan_result()
    main.app.state.last_result.explanations = None
    keyed = Settings(anthropic_api_key=SecretStr("sk-ant-test"), tsa_url="")
    monkeypatch.setattr(main.config, "get_settings", lambda: keyed)
    calls = []

    def fake_explain(findings, devices, nearby, *, online):
        calls.append(online)
        status = "failed" if online else "offline"
        return Explanations(
            ai_status=status, ai_reason_text="The AI didn't answer in time." if online else None
        )

    monkeypatch.setattr(main, "explain", fake_explain)
    off = client.post("/api/report", json={"ai": False, "timestamp": False}).json()
    assert off["ai"]["state"] == "not_requested" and calls == [False]
    on = client.post("/api/report", json={"ai": True, "timestamp": False}).json()
    assert on["ai"] == {"state": "unavailable", "reason": "The AI didn't answer in time."}


# --- 9. Verify outcomes ---------------------------------------------------------------------------


def test_verified():
    r = tamper.verify(SAMPLE_PDF, SAMPLE_TSR)
    assert (r.outcome, r.reason, r.ok) == ("verified", None, True)


def test_files_dont_match():
    changed = SAMPLE_PDF[:-10] + b"x" + SAMPLE_PDF[-9:]
    r = tamper.verify(changed, SAMPLE_TSR)
    assert (r.outcome, r.ok) == ("mismatch", False)


@pytest.mark.parametrize(
    "pdf, tsr, cert, reason",
    [
        (b"not a pdf at all", SAMPLE_TSR, None, "isn't a PDF"),
        (SAMPLE_PDF, b"not a timestamp", None, "damaged or isn't a timestamp"),
        (SAMPLE_PDF, SAMPLE_TSR, CACERT, "wasn't signed by the timestamp service RoomCheck uses"),
    ],
)
def test_couldnt_verify_says_the_specific_reason(pdf, tsr, cert, reason):
    r = tamper.verify(pdf, tsr, certificate=cert)
    assert r.outcome == "couldnt_verify" and reason in (r.reason or "")
    assert not r.ok


def test_an_untimestamped_report_is_explained_never_called_altered():
    r = tamper.verify(SAMPLE_PDF, None, "0" * 64)  # even with a .sha256 that doesn't match
    assert r.outcome == "not_timestamped"
    assert r.message.startswith(tamper.NOT_TIMESTAMPED)
    assert not [w for w in ("changed", "altered", "tampered") if w in r.message.lower()]


def test_the_verify_endpoint_takes_a_pdf_alone(client):
    r = client.post("/api/verify", files={"pdf": ("r.pdf", SAMPLE_PDF, "application/pdf")})
    assert r.status_code == 200 and r.json()["outcome"] == "not_timestamped"


# --- 10. all devices ------------------------------------------------------------------------------


def test_coverage_is_unaffected_by_devices_with_no_findings():
    result = check([camera(), scored(dev.sonos())])
    result.checks = [CheckStatus(name="mdns", label="mdns", status="ran")]
    assert [r.state for r in coverage(result)] == ["completed"]
    assert len(result.devices) == 2 and len({f.device_ref for f in result.findings}) == 1
