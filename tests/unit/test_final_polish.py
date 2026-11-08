"""Final UI polish: what the backend has to agree on with the new screens.

The Handover page builds the host message for a chosen subset of open tasks itself, with the
same template as bundle_message. These tests pin the two together, so they can't drift.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.baseline.compare import compare, snapshot
from app.baseline.store import BaselineStore
from app.fingerprint.models import Identity
from app.handover.models import Task
from app.handover.session import HandoverSession
from app.handover.tasks import STANDARD_MESSAGE_LABEL, bundle_message
from tests.conftest import FakeProtector
from tests.unit import devices as dev
from tests.unit.test_layer6 import SALT, T0, check, scored

ROOT = Path(__file__).resolve().parents[2]
EN = json.loads((ROOT / "web/src/strings/en.json").read_text(encoding="utf-8"))
MESSAGE = EN["handover"]["message"]


def task(n: int, ask: str) -> Task:
    return Task(
        id=f"R-CAM|device:{n}",
        finding_id=f"R-CAM:dev-{n}",
        rule_id="R-CAM",
        subject=f"device:{n}",
        severity="High",
        finding_title="Likely camera",
        title=f"Ask about device {n}",
        ask=ask,
        who="landlord_or_host",
        steps=[],
    )


def client_side(tasks: list[Task]) -> str:
    """What web/src/handover/message.ts messageFor builds for these tasks."""
    opening = MESSAGE["opening_one"] if len(tasks) == 1 else MESSAGE["opening_other"]
    lines = "\n".join(f"{i}. {t.ask}" for i, t in enumerate(tasks, start=1))
    return f"{opening}\n\n{lines}\n\n{MESSAGE['closing']}"


def test_one_task_matches_the_server_template():
    tasks = [task(1, "Could you tell me what the camera-like device is?")]
    message = bundle_message(tasks, None)
    assert message is not None
    assert message.text == client_side(tasks)


def test_several_tasks_match_the_server_template():
    tasks = [task(1, "First question?"), task(2, "Second question?"), task(3, "Third question?")]
    message = bundle_message(tasks, None)
    assert message is not None
    assert message.text == client_side(tasks)


def test_the_note_matches_the_server_note():
    message = bundle_message([task(1, "A question?")], None)
    assert message is not None
    assert message.note == MESSAGE["note"]
    assert message.label == STANDARD_MESSAGE_LABEL


# --- Compare: modes, and answering "possibly the same device" -----------------------------------


def soft_pair():
    """A phone with a private address at move-in, and (by soft key) possibly the same now."""
    phone = scored(
        dev.make("192.0.2.7", "da:11:22:33:44:55", hostnames=["anna-phone.local"], random=True)
    )
    phone.identity = Identity(open_ports=[])
    base = snapshot(check([phone], at=T0), SALT, T0)
    same = scored(
        dev.make("192.0.2.9", "de:99:88:77:66:55", hostnames=["anna-phone.local"], random=True)
    )
    same.vendor = phone.vendor
    same.services = phone.services
    return base, same


def test_compare_says_how_each_check_ran():
    base, same = soft_pair()
    out = compare(base, check([same]), SALT)
    assert (out.baseline_mode, out.scan_mode) == (base.mode, check([same]).mode)


def test_an_unchanged_possible_match_is_listed_so_it_can_be_answered():
    base, same = soft_pair()
    out = compare(base, check([same]), SALT)
    assert (out.unchanged, out.unchanged_possible) == (1, 1)
    (item,) = out.possible
    assert item.status == "unchanged" and item.match == "possible"
    assert item.match_id and item.decision is None


def test_same_counts_the_pair_as_one_device():
    base, same = soft_pair()
    mid = compare(base, check([same]), SALT).possible[0].match_id
    out = compare(base, check([same]), SALT, {mid: "same"})
    assert out.new == [] and out.gone == []
    assert (out.unchanged, out.unchanged_possible) == (1, 0)  # answered: no longer "possibly"
    assert out.possible[0].decision == "same"  # still listed, so the answer can be changed


def test_different_shows_one_new_and_one_not_seen_and_never_changes_findings():
    base, same = soft_pair()
    result = check([same])
    findings_before = [f.model_dump() for f in result.findings]
    mid = compare(base, result, SALT).possible[0].match_id
    out = compare(base, result, SALT, {mid: "different"})
    assert out.unchanged == 0 and out.possible == []
    (new,), (gone,) = out.new, out.gone
    assert (new.match_id, new.decision) == (mid, "different")
    assert (gone.match_id, gone.decision) == (mid, "different")
    assert [f.model_dump() for f in result.findings] == findings_before


def test_a_changed_possible_match_carries_its_id_and_answer():
    base, same = soft_pair()
    same.identity = Identity(open_ports=[8080])
    (changed,) = compare(base, check([same]), SALT).changed
    assert changed.match == "possible" and changed.match_id and changed.decision is None
    (changed,) = compare(base, check([same]), SALT, {changed.match_id: "same"}).changed
    assert changed.decision == "same"


def test_answers_are_saved_encrypted_and_cleared_with_the_baseline(tmp_path):
    base, same = soft_pair()
    store = BaselineStore(tmp_path / "b.db", FakeProtector())
    session = HandoverSession(store)
    session.salt = SALT
    session.save_baseline(check([same], at=T0))
    session.set_match("x>y", "different")
    assert HandoverSession(store).matches == {"x>y": "different"}  # survives a restart
    session.set_match("x>y", None)
    assert HandoverSession(store).matches == {}
    session.set_match("x>y", "same")
    session.delete_baseline()
    assert session.matches == {} and HandoverSession(store).matches == {}
    session.save_baseline(check([same], at=T0))
    session.set_match("x>y", "same")
    session.delete_all()
    assert HandoverSession(store).matches == {}


@pytest.fixture
def client(no_real_baseline_store, monkeypatch):
    monkeypatch.setattr(main.app.state, "last_result", None, raising=False)
    with TestClient(main.app) as c:
        yield c


def test_api_answers_a_possible_match(client):
    base, same = soft_pair()
    phone_check = check([same], at=T0)
    main.app.state.last_result = phone_check
    client.post("/api/baseline")
    ready = client.get("/api/compare").json()["comparison"]
    assert ready["baseline_mode"] and ready["scan_mode"]
    # The same device matches exactly against itself; build a soft pair through the session.
    session = main.app.state.handover
    session.baseline = base
    session.salt = SALT
    main.app.state.last_result = check([same])
    (item,) = client.get("/api/compare").json()["comparison"]["possible"]
    r = client.post(
        "/api/compare/matches", json={"match_id": item["match_id"], "decision": "different"}
    )
    out = r.json()["comparison"]
    assert r.status_code == 200 and len(out["new"]) == 1 and len(out["gone"]) == 1
    r = client.post("/api/compare/matches", json={"match_id": item["match_id"], "decision": None})
    assert r.json()["comparison"]["possible"][0]["decision"] is None
    bad = client.post("/api/compare/matches", json={"match_id": "x", "decision": "maybe"})
    assert bad.status_code == 422


# --- Report: the bundle, and the last room label -----------------------------------------------


@pytest.fixture
def report_client(tmp_path, monkeypatch):
    from app.report import render, tamper
    from tests.unit.test_report import SAMPLE_PDF, SAMPLE_TSR

    monkeypatch.setattr(render, "render_pdf", lambda html: SAMPLE_PDF)
    monkeypatch.setattr(tamper, "request_token", lambda digest, url: SAMPLE_TSR)
    monkeypatch.setattr(main.app.state, "report_dir", tmp_path, raising=False)
    monkeypatch.setattr(main.app.state, "last_result", None, raising=False)
    with TestClient(main.app) as c:
        yield c


def test_report_bundle_holds_the_pdf_tsr_and_hash(report_client):
    import io
    import zipfile

    from tests.unit.test_report import SAMPLE_PDF, scan_result

    main.app.state.last_result = scan_result()
    body = report_client.post("/api/report", json={}).json()
    assert body["bundle"].endswith(".zip")
    r = report_client.get(f"/api/report/files/{body['bundle']}")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert sorted(z.namelist()) == sorted([body["pdf"], body["tsr"], body["sha256_file"]])
        assert z.read(body["pdf"]) == SAMPLE_PDF


def test_report_bundle_without_a_timestamp_has_no_tsr(report_client):
    import io
    import zipfile

    from tests.unit.test_report import scan_result

    main.app.state.last_result = scan_result()
    body = report_client.post("/api/report", json={"timestamp": False}).json()
    assert body["tsr"] is None
    content = report_client.get(f"/api/report/files/{body['bundle']}").content
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        assert sorted(z.namelist()) == sorted([body["pdf"], body["sha256_file"]])


def test_the_last_room_label_is_offered_next_time_and_deleted_with_the_data(report_client):
    from tests.unit.test_report import scan_result

    assert report_client.get("/api/report/defaults").json() == {"room_label": None}
    main.app.state.last_result = scan_result()
    report_client.post("/api/report", json={"room_label": "Flat 4B"})
    assert report_client.get("/api/report/defaults").json() == {"room_label": "Flat 4B"}
    # A report without a label keeps the last one used.
    report_client.post("/api/report", json={"room_label": ""})
    assert report_client.get("/api/report/defaults").json() == {"room_label": "Flat 4B"}
    # Saved, encrypted, in the store: a restart still offers it.
    store = main.app.state.handover.store
    assert HandoverSession(store).room_label == "Flat 4B"
    report_client.delete("/api/data")
    assert report_client.get("/api/report/defaults").json() == {"room_label": None}
