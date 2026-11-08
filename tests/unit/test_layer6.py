"""Layer 6: matching keys, handover tasks, recognition answers, the encrypted move-in store
(including the DPAPI failure path), the comparison, the new-camera rule and the API."""

import json
import sys
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.baseline.compare import assign_subjects, compare, snapshot
from app.baseline.keys import device_keys, nearby_key
from app.baseline.models import BaselineFacts
from app.baseline.store import BaselineStore, BaselineUnreadable, DpapiProtector
from app.discovery.messages import message_for
from app.discovery.models import DiscoveryResult, Service
from app.explain.models import LandlordMessage
from app.explain.validator import check_landlord_message
from app.fingerprint.facts import device_facts
from app.fingerprint.models import Identity
from app.fingerprint.scoring import fingerprint, load_weights
from app.handover import tasks as task_rules
from app.handover.models import TaskState
from app.handover.session import HandoverSession
from app.rules.engine import RoomFacts, evaluate, load_rules
from app.rules.models import Finding
from app.wireless.models import NearbyItem
from tests.conftest import FakeProtector
from tests.unit import devices as dev
from tests.unit.test_rules import NET

SALT = b"s" * 32
T0 = datetime(2026, 11, 3, 5, 0, tzinfo=UTC)
T1 = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


def scored(d):
    d.fingerprint = fingerprint(device_facts(d), "full")
    return d


def check(devices, *, baseline=None, nearby_items=(), extra_findings=(), at=T1):
    """A check through the real rules engine, with subjects, as run_scan makes it."""
    findings = evaluate(RoomFacts(devices=list(devices), network=NET, baseline=baseline))
    findings += list(extra_findings)
    result = DiscoveryResult(
        started_at=at,
        finished_at=at,
        mode="full",
        network=NET,
        devices=list(devices),
        checks=[],
        findings=findings,
        nearby_items=list(nearby_items),
    )
    assign_subjects(result, SALT)
    return result


def camera():
    return scored(dev.hikvision_camera())


def nearby_finding(rule_id, ref, severity="Medium", title="Your Wi-Fi router offers WPS"):
    return Finding(
        id=f"{rule_id}:{ref}",
        rule_id=rule_id,
        scope="nearby",
        severity=severity,
        confidence_band="Likely",
        device_ref=None,
        title=title,
        evidence=["e"],
        next_step="Ask the host.",
        nearby_ref=ref,
    )


def wps_item(key="wifi:aaa"):
    return NearbyItem(
        ref="wifi:session1",
        kind="wifi",
        label='Wi-Fi network "Example-Home"',
        maker="TP-Link Systems Inc",
        signal_dbm=-40,
        rule_ids=["R-WPS"],
        match_key=key,
    )


# --- matching keys -----------------------------------------------------------------------------


def test_a_real_mac_is_the_key_and_the_salt_makes_it_unreadable():
    d = camera()
    keys = device_keys(d, SALT)
    assert keys.kind == "mac" and keys.key.startswith("mac:")
    assert device_keys(d, SALT) == keys  # stable across scans with the same salt
    assert device_keys(d, b"t" * 32).key != keys.key  # meaningless without the salt
    assert d.mac.replace(":", "") not in keys.key


def test_a_private_mac_falls_back_to_a_soft_key_and_nothing_means_no_key():
    phone = dev.make("192.0.2.7", "da:11:22:33:44:55", hostnames=["anna-phone.local"], random=True)
    keys = device_keys(phone, SALT)
    assert keys.kind == "soft" and keys.key == keys.soft and keys.key.startswith("soft:")
    bare = dev.make("192.0.2.8", "da:11:22:33:44:56", random=True)
    bare.vendor = None
    assert device_keys(bare, SALT).kind == "none"


def test_nearby_keys_are_salted_hashes_of_the_address():
    key = nearby_key("wifi", "CC:BA:BD:00:10:D9", SALT)
    assert key == nearby_key("wifi", "cc-ba-bd-00-10-d9", SALT)
    assert "ccba" not in key and key.startswith("wifi:")


# --- handover tasks ----------------------------------------------------------------------------


def _severities(rule):
    return set(rule.severity.values()) if isinstance(rule.severity, dict) else {rule.severity}


def test_every_rule_that_can_be_high_or_medium_has_a_task_template():
    templates = task_rules.load_templates()
    for rule in load_rules().rules:
        if _severities(rule) & {"High", "Medium"}:
            assert rule.id in templates.templates, rule.id


@pytest.mark.parametrize("rule_id", sorted(task_rules.load_templates().templates))
def test_each_template_asks_a_polite_question_with_fixed_category_steps(rule_id):
    templates = task_rules.load_templates()
    t = templates.templates[rule_id]
    assert t.ask.endswith("?")
    assert check_landlord_message(t.ask) is None  # no accusations, threats or reassurance
    assert (
        templates.steps_for(rule_id)[: len(templates.categories[t.category]["steps"])]
        == (templates.categories[t.category]["steps"])
    )


def test_plan_md_category_steps():
    steps = task_rules.load_templates().categories
    assert any("users, codes and fingerprints" in s for s in steps["lock"]["steps"])
    assert any("in writing" in s for s in steps["lock"]["steps"])
    # No bundled request: router tasks ask only for what their own finding supports.
    assert steps["router"]["steps"] == []
    templates = task_rules.load_templates().templates
    for rule_id, t in templates.items():
        assert not any("password" in x for x in [t.ask, *t.steps]), rule_id
    # Kept only as a clearly optional suggestion, with its own reason.
    (extra,) = templates["R-WIFI-ENC"].optional
    assert "password" in extra.text and extra.reason
    assert any("factory-reset" in s for s in steps["cloud"]["steps"])
    assert any("who can view it" in s for s in steps["camera"]["steps"])


def test_tasks_come_from_high_and_medium_findings_with_the_makers_own_support_page():
    result = check(
        [camera()],
        nearby_items=[wps_item()],
        extra_findings=[nearby_finding("R-WPS", "wifi:session1")],
    )
    tasks = task_rules.build_tasks(result, {}, {})
    by_rule = {t.rule_id: t for t in tasks}
    assert set(by_rule) == {"R-CAM", "R-WPS"}
    cam = by_rule["R-CAM"]
    assert cam.severity == "High" and cam.who == "landlord_or_host" and cam.status == "todo"
    assert "who can view it" in " ".join(cam.steps)
    assert cam.support is not None and cam.support.url == "https://www.hikvision.com/en/support/"
    assert by_rule["R-WPS"].support.url == "https://www.tp-link.com/support/"
    assert tasks[0].rule_id == "R-CAM"  # High first
    # Only links to the maker; RoomCheck never writes brand-specific reset steps.
    assert not any(
        "reset" in s.lower() and "hikvision" in s.lower() for t in tasks for s in t.steps
    )


def test_no_support_link_for_an_unknown_maker():
    assert task_rules.support_for("Example Camera Co.", task_rules.load_templates()) is None
    assert task_rules.support_for(None, task_rules.load_templates()) is None
    # Whole words only: "Bring" isn't Ring.
    assert task_rules.support_for("Bring Devices", task_rules.load_templates()) is None


def test_saved_statuses_notes_and_dates_are_applied_by_task_id():
    result = check([camera()])
    (cam,) = task_rules.build_tasks(result, {}, {})
    state = TaskState(status="asked", notes="Emailed on Monday", changed_at=T1)
    (again,) = task_rules.build_tasks(result, {}, {cam.id: state})
    assert (again.status, again.notes, again.changed_at) == ("asked", "Emailed on Monday", T1)


def test_the_message_bundles_the_open_tasks_and_never_the_closed_ones():
    result = check(
        [camera()],
        nearby_items=[wps_item()],
        extra_findings=[
            nearby_finding("R-WPS", "wifi:session1"),
            nearby_finding("R-TRACKER", "bluetooth:x", title="Item tracker nearby"),
        ],
    )
    tasks = task_rules.build_tasks(result, {}, {})
    message = task_rules.bundle_message(tasks, None)
    assert message.source == "standard" and message.note.startswith("RoomCheck never sends")
    assert (
        "1. Could you tell me what the device on the Wi-Fi that looks like a camera is"
        in message.text
    )
    assert "2. The Wi-Fi router advertises WPS." in message.text
    assert "item tracker" not in message.text  # a task for you, not for the host
    assert check_landlord_message(message.text) is None
    cam = next(t for t in tasks if t.rule_id == "R-CAM")
    closed = task_rules.build_tasks(result, {}, {cam.id: TaskState(status="confirmed")})
    assert "camera" not in task_rules.bundle_message(closed, None).text
    done = {t.id: TaskState(status="done") for t in tasks}
    assert task_rules.bundle_message(task_rules.build_tasks(result, {}, done), None) is None


def test_the_ai_draft_is_used_only_while_it_covers_exactly_the_open_tasks():
    result = check([camera()])
    tasks = task_rules.build_tasks(result, {}, {})
    ai = LandlordMessage(
        text="Hello, I noticed a device that may be a camera. Could you tell me about it?",
        source="ai",
        label="AI",
        covers=[tasks[0].finding_id],
    )
    assert task_rules.bundle_message(tasks, ai) is ai
    asked = task_rules.build_tasks(result, {}, {tasks[0].id: TaskState(status="asked")})
    assert task_rules.bundle_message(asked, ai).source == "standard"


# --- "Do you recognise this device?" -----------------------------------------------------------


def test_mine_changes_the_next_step_and_guidance_but_never_the_detection(tmp_path):
    result = check([camera()])
    cam = next(f for f in result.findings if f.rule_id == "R-CAM")
    before = cam.model_copy(deep=True)
    session = HandoverSession(BaselineStore(tmp_path / "b.db", FakeProtector()))
    session.set_answer(cam.subject, "mine")
    state = session.state_for(result)
    steps = state.adjusted[cam.id]
    assert steps.guidance == []  # no "leave if unsafe" or "report it"
    assert steps.next_step.startswith("You said this is yours")
    assert [t for t in state.tasks if t.rule_id == "R-CAM"] == []  # nothing to ask anyone
    # The finding itself is unchanged: same severity, confidence, title and evidence.
    assert cam == before
    assert next(f for f in result.findings if f.rule_id == "R-CAM").severity == "High"


@pytest.mark.parametrize("answer", ["landlord", "unknown"])
def test_landlord_and_dont_know_keep_the_next_steps_and_the_task(tmp_path, answer):
    result = check([camera()])
    cam = next(f for f in result.findings if f.rule_id == "R-CAM")
    session = HandoverSession(BaselineStore(tmp_path / "b.db", FakeProtector()))
    session.set_answer(cam.subject, answer)
    state = session.state_for(result)
    assert cam.id not in state.adjusted
    assert [t.rule_id for t in state.tasks if t.rule_id == "R-CAM"] == ["R-CAM"]
    assert state.answers[cam.subject] == answer


def test_an_answer_can_be_cleared(tmp_path):
    session = HandoverSession(BaselineStore(tmp_path / "b.db", FakeProtector()))
    session.set_answer("device:x", "mine")
    session.set_answer("device:x", None)
    assert session.answers == {}


# --- the encrypted store -----------------------------------------------------------------------


def test_the_store_encrypts_every_value_on_disk(tmp_path):
    store = BaselineStore(tmp_path / "b.db", FakeProtector())
    store.write({"baseline": {"type_label": "Camera", "secret": "camera-in-hallway"}})
    assert store.read("baseline") == {"type_label": "Camera", "secret": "camera-in-hallway"}
    raw = (tmp_path / "b.db").read_bytes()
    assert b"camera-in-hallway" not in raw and b"Camera" not in raw


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI")
def test_real_dpapi_round_trip(tmp_path):
    store = BaselineStore(tmp_path / "b.db", DpapiProtector())
    store.write({"salt": "ab" * 16})
    assert store.read("salt") == "ab" * 16
    assert b"abab" not in (tmp_path / "b.db").read_bytes()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI")
def test_real_dpapi_rejects_a_damaged_value(tmp_path):
    import sqlite3

    store = BaselineStore(tmp_path / "b.db", DpapiProtector())
    store.write({"salt": "ab" * 16})
    with sqlite3.connect(tmp_path / "b.db") as conn:
        (blob,) = conn.execute("SELECT value FROM store WHERE key = 'salt'").fetchone()
        conn.execute("UPDATE store SET value = ? WHERE key = 'salt'", (blob[:-8] + b"x" * 8,))
    conn.close()
    with pytest.raises(BaselineUnreadable):
        store.read("salt")


def test_another_accounts_store_gives_the_plan_md_message(tmp_path):
    path = tmp_path / "b.db"
    mine = HandoverSession(BaselineStore(path, FakeProtector(b"alice")))
    mine.save_baseline(check([camera()]), now=T0)
    theirs = HandoverSession(BaselineStore(path, FakeProtector(b"bob")))
    info = theirs.info()
    assert info.state == "unreadable"
    assert (
        info.message
        == "This saved scan belongs to another account or install. Start a new move-in scan."
    )
    assert info.message == message_for("baseline_unreadable")
    assert theirs.facts() is None  # nothing is compared against it
    # Starting a new baseline replaces it.
    assert theirs.save_baseline(check([camera()]), now=T1).state == "saved"
    assert HandoverSession(BaselineStore(path, FakeProtector(b"bob"))).info().saved_at == T1


def test_a_damaged_file_is_unreadable_not_a_crash(tmp_path):
    path = tmp_path / "b.db"
    path.write_bytes(b"this is not a database")
    assert HandoverSession(BaselineStore(path, FakeProtector())).info().state == "unreadable"


def test_saving_keeps_answers_and_tasks_and_later_changes_are_saved_too(tmp_path):
    path = tmp_path / "b.db"
    result = check([camera()])
    cam = next(f for f in result.findings if f.rule_id == "R-CAM")
    session = HandoverSession(BaselineStore(path, FakeProtector()))
    session.set_answer(cam.subject, "landlord")
    assert path.exists()  # saved straight away, with or without a move-in scan
    session.save_baseline(result, now=T0)
    task = session.state_for(result).tasks[0]
    session.update_task(task.id, "asked", "Emailed the host", now=T1)
    reloaded = HandoverSession(BaselineStore(path, FakeProtector()))
    assert reloaded.salt == session.salt  # so later scans give the same keys
    assert reloaded.answers == {cam.subject: "landlord"}
    again = reloaded.state_for(result).tasks[0]
    assert (again.status, again.notes, again.changed_at) == ("asked", "Emailed the host", T1)


def test_delete_baseline_removes_the_file(tmp_path):
    path = tmp_path / "b.db"
    session = HandoverSession(BaselineStore(path, FakeProtector()))
    session.save_baseline(check([camera()]), now=T0)
    assert path.exists()
    assert session.delete_baseline().state == "none"
    # Only the move-in scan goes: the handover data stays saved.
    again = HandoverSession(BaselineStore(path, FakeProtector()))
    assert again.info().state == "none" and again.salt == session.salt


def test_the_baseline_stores_only_what_plan_md_lists():
    d = camera()
    result = check(
        [d], nearby_items=[wps_item()], extra_findings=[nearby_finding("R-WPS", "wifi:session1")]
    )
    base = snapshot(result, SALT, T0)
    data = json.dumps(base.model_dump(mode="json"))
    (stored,) = base.devices
    assert set(stored.model_dump()) == {
        "key",
        "kind",
        "soft",
        "type",
        "type_label",
        "ports",
        "ports_checked",
        "findings",
        # Part of the type guess: its band and the fixed names of the clues behind it (from
        # weights.yaml, e.g. "onvif_nvt"), so Compare can tell varied identification from a
        # changed device. Never device data.
        "band",
        "signals",
    }
    assert stored.type == "camera" and stored.ports == sorted(d.identity.open_ports)
    known = {s.id for t in load_weights().types.values() for s in t.signals}
    assert stored.signals and set(stored.signals) <= known
    assert stored.band == d.fingerprint.band
    assert set(base.nearby[0].model_dump()) == {"key", "kind", "findings"}
    # No addresses, names, makers or network names.
    for secret in (d.mac, d.ip, d.vendor, *d.hostnames, "Example-Home", "TP-Link"):
        assert secret.lower() not in data.lower(), secret


# --- the comparison ----------------------------------------------------------------------------


def test_new_gone_and_changed_devices():
    sonos, cam = scored(dev.sonos()), camera()
    base = snapshot(check([sonos, cam], at=T0), SALT, T0)
    laptop = scored(dev.windows_laptop())
    cam2 = camera()
    cam2.identity.open_ports = sorted({*cam2.identity.open_ports, 23})
    out = compare(base, check([cam2, laptop]), SALT)
    assert [i.label for i in out.new] == [laptop.fingerprint.label]
    assert [i.status for i in out.gone] == ["gone"] and out.gone[0].label == sonos.fingerprint.label
    (changed,) = out.changed
    assert changed.match == "exact"
    assert "Newly open port: 23" in changed.changes
    assert out.baseline_saved_at == T0


def test_a_soft_key_match_is_only_possibly_the_same_device():
    phone = scored(
        dev.make("192.0.2.7", "da:11:22:33:44:55", hostnames=["anna-phone.local"], random=True)
    )
    phone.identity = Identity(open_ports=[])  # its services were checked at move-in
    base = snapshot(check([phone], at=T0), SALT, T0)
    later = scored(
        dev.make("192.0.2.9", "de:99:88:77:66:55", hostnames=["anna-phone.local"], random=True)
    )
    later.identity = None
    later.services = [Service(kind="mdns", name="_companion-link._tcp")]
    out = compare(base, check([later]), SALT)
    # A different private address with a different service list: no match, so it's new.
    assert len(out.new) == 1
    same = scored(
        dev.make("192.0.2.9", "de:99:88:77:66:55", hostnames=["anna-phone.local"], random=True)
    )
    same.vendor = phone.vendor
    same.services = phone.services
    out = compare(base, check([same]), SALT)
    assert out.new == [] and out.gone == []
    assert (out.unchanged, out.unchanged_possible) == (1, 1)  # never a confident match
    same.identity = Identity(open_ports=[8080])  # now offers a web page: changed, possibly
    (changed,) = compare(base, check([same]), SALT).changed
    assert changed.match == "possible" and "Newly open port: 8080" in changed.changes


def test_devices_with_nothing_to_match_on_are_counted_not_guessed():
    bare = dev.make("192.0.2.8", "da:11:22:33:44:56", random=True)
    bare.vendor = None
    base = snapshot(check([bare], at=T0), SALT, T0)
    assert base.devices == [] and base.unkeyed_devices == 1
    out = compare(base, check([bare]), SALT)
    assert (out.new, out.gone, out.not_compared) == ([], [], 1)


def test_nearby_items_and_network_findings_are_compared_too():
    base = snapshot(
        check(
            [],
            nearby_items=[wps_item("wifi:old")],
            extra_findings=[nearby_finding("R-WPS", "wifi:session1")],
            at=T0,
        ),
        SALT,
        T0,
    )
    net = Finding(
        id="R-DHCP:network",
        rule_id="R-DHCP",
        scope="network",
        severity="High",
        confidence_band="Likely",
        device_ref=None,
        title="More than one device hands out network addresses",
        evidence=[],
        next_step="x",
    )
    item = wps_item("wifi:new")
    out = compare(
        base,
        check(
            [], nearby_items=[item], extra_findings=[nearby_finding("R-WPS", "wifi:session1"), net]
        ),
        SALT,
    )
    assert sorted((i.kind, i.status) for i in out.new) == [("nearby", "new"), ("network", "new")]
    assert [(i.kind, i.label) for i in out.gone] == [("nearby", "Nearby Wi-Fi")]


# --- the new-camera rule, through the same rules engine ----------------------------------------


def test_a_camera_new_since_the_move_in_scan_is_high_with_the_date():
    base = snapshot(check([scored(dev.sonos())], at=T0), SALT, T0)
    facts = BaselineFacts.of(base, SALT)
    result = check([camera()], baseline=facts)
    new = next(f for f in result.findings if f.rule_id == "R-NEW-CAMERA")
    assert new.severity == "High"
    assert new.evidence[0] == "It wasn't in your move-in scan on 3 Nov 2026."
    assert "R-CAM" in {f.rule_id for f in result.findings}  # the usual rules still run


def test_a_camera_that_was_there_at_move_in_is_not_new():
    base = snapshot(check([camera()], at=T0), SALT, T0)
    result = check([camera()], baseline=BaselineFacts.of(base, SALT))
    assert "R-NEW-CAMERA" not in {f.rule_id for f in result.findings}
    assert "R-NEW-CAMERA" not in {f.rule_id for f in check([camera()]).findings}  # no baseline


# --- the API -----------------------------------------------------------------------------------


@pytest.fixture
def client(no_real_baseline_store, monkeypatch):
    monkeypatch.setattr(main.app.state, "last_result", None, raising=False)  # no earlier check
    with TestClient(main.app) as c:
        c.store_path = no_real_baseline_store
        yield c


def test_api_save_compare_and_delete_the_baseline(client):
    assert client.get("/api/baseline").json()["state"] == "none"
    assert client.get("/api/compare").json()["state"] == "none"
    r = client.post("/api/baseline")
    assert (r.status_code, r.json()["detail"]) == (409, message_for("baseline_needs_check"))
    main.app.state.last_result = check([camera()])
    saved = client.post("/api/baseline").json()
    assert saved["state"] == "saved" and saved["devices"] == 1
    assert client.store_path.exists()
    ready = client.get("/api/compare").json()
    assert ready["state"] == "ready" and ready["comparison"]["unchanged"] == 1
    assert client.delete("/api/baseline").json()["state"] == "none"
    assert client.get("/api/compare").json()["state"] == "none"


def test_api_answers_change_guidance_and_tasks_not_findings(client):
    result = check([camera()])
    main.app.state.last_result = result
    cam = next(f for f in result.findings if f.rule_id == "R-CAM")
    assert [t["rule_id"] for t in client.get("/api/handover").json()["tasks"]] == ["R-CAM"]
    state = client.post("/api/answers", json={"subject": cam.subject, "answer": "mine"}).json()
    assert state["tasks"] == [] and state["adjusted"][cam.id]["guidance"] == []
    assert state["message"] is None
    assert main.app.state.last_result.findings == result.findings  # detection unchanged
    assert (
        client.post("/api/answers", json={"subject": cam.subject, "answer": "nope"}).status_code
        == 422
    )


def test_api_task_status_and_notes(client):
    main.app.state.last_result = check([camera()])
    task = client.get("/api/handover").json()["tasks"][0]
    from urllib.parse import quote

    state = client.patch(
        f"/api/tasks/{quote(task['id'], safe='')}", json={"status": "asked", "notes": "Emailed"}
    ).json()
    (updated,) = state["tasks"]
    assert (updated["status"], updated["notes"]) == ("asked", "Emailed") and updated["changed_at"]
    assert client.patch("/api/tasks/nope", json={"status": "resolved"}).status_code == 404
    assert (
        client.patch(
            f"/api/tasks/{quote(task['id'], safe='')}", json={"status": "maybe"}
        ).status_code
        == 422
    )


def test_task_statuses_and_dates_are_in_the_pdf_report():
    from app.handover.session import HandoverSession as Session
    from app.report import render

    result = check([camera()])
    result.summary = None
    session = Session(BaselineStore(main.baseline_store().path, FakeProtector()))
    task = session.state_for(result).tasks[0]
    session.update_task(
        task.id, "asked", "Host said it's the hallway camera", now=T1, host_confirmed=True
    )
    from app.explain.models import Explanations

    html = render.render_html(
        render.build_view(
            result,
            Explanations(),
            room_label=None,
            generated_at=T1,
            handover=session.state_for(result),
            privacy=render.ReportPrivacy(notes=True),  # notes are off unless chosen
        )
    )
    assert "What I&#39;m asking, and its status" in html  # page 1, for the host
    assert (
        "<td>Asked</td>" in html
        and "Host confirmed (" in html
        and "Host said it&#39;s the hallway camera" in html
    )
    assert task.title in html


def test_a_rescan_gets_the_baseline_and_the_fixed_salt(client, monkeypatch):
    """The scan pipeline passes the move-in keys and the stored salt to the rules, so a later
    check's subjects and keys match the saved ones."""
    seen = {}

    def fake_run(consent, scanner, duration_seconds, online=True, **kwargs):
        seen.update(kwargs)
        return check([camera()])

    monkeypatch.setattr(main, "run_scan", fake_run)
    monkeypatch.setattr(main, "explain", lambda *a, **k: None)
    body = main.DiscoveryRequest()
    main._run_check(body, main.app.state)
    assert seen["baseline"] is None  # no move-in scan yet
    session = main._handover(main.app.state)
    assert seen["match_salt"] == session.salt
    client.post("/api/baseline")
    main._run_check(body, main.app.state)
    assert seen["baseline"].saved_at == session.baseline.saved_at
    assert seen["baseline"].keys == {d.key for d in session.baseline.devices}
