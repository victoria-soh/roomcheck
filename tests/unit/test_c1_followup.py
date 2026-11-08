"""C1 follow-up: one vocabulary for uncertainty (and the old phrasings gone), the report's
privacy choices, and deleting all saved RoomCheck data."""

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import app.main as main
from app import coverage as coverage_mod
from app.baseline.store import BaselineStore
from app.discovery.messages import MESSAGES
from app.explain import ai, validator
from app.explain.models import Explanations
from app.handover import recheck as recheck_mod
from app.handover.session import HandoverSession
from app.report import render, tamper
from app.vocabulary import OLD_PHRASES, old_phrase
from tests.conftest import FakeProtector
from tests.unit.test_layer6 import T0, T1, camera, check
from tests.unit.test_report import SAMPLE_PDF

ROOT = Path(__file__).resolve().parents[2]


def strings(node, path=""):
    """Every string value in a JSON or YAML tree (keys aren't shown to anyone)."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from strings(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from strings(v, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


# --- 1. one vocabulary --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Skipped.",
        "Not run: Nmap is missing",
        "The nearby check didn't run.",
        "Nothing found",
        "This check flagged nothing.",
        "No issues found",
        "This is a hint, not proof.",
        "It couldn't be checked.",
        "Shown as context, not proof.",
    ],
)
def test_the_old_phrasings_are_recognised(text):
    assert old_phrase(text)


def test_the_new_words_are_allowed():
    for text in (
        "Not detected",
        "Not checked: Bluetooth is off",
        "Unconfirmed: a clue, not proof.",
        "Resolved",
        "Results are clues, not proof.",
    ):
        assert old_phrase(text) is None, text


def test_no_old_phrasing_is_left_in_the_dashboard_strings():
    data = json.loads((ROOT / "web/src/strings/en.json").read_text(encoding="utf-8"))
    left = [(p, v) for p, v in strings(data) if old_phrase(v)]
    assert left == []


def test_no_old_phrasing_is_left_in_messages_rules_tasks_and_the_report():
    texts = list(MESSAGES.values())
    for f in ("app/rules/rules.yaml", "app/handover/tasks.yaml"):
        texts += [v for _, v in strings(yaml.safe_load((ROOT / f).read_text(encoding="utf-8")))]
    texts += list(coverage_mod.STATE_TEXT.values())
    texts += list(coverage_mod.SHORT_REASON.values()) + [coverage_mod.PASSIVE_REASON]
    texts += [v for group in recheck_mod.TEXT.values() for v in group.values()]
    texts += [recheck_mod.NO_ROOM, recheck_mod.NEEDS_PERMISSION, tamper.NOT_TIMESTAMPED]
    # The report template's own words (everything outside {{ }} and {% %}).
    import re

    template = (ROOT / "app/report/templates/report.html.j2").read_text(encoding="utf-8")
    texts.append(re.sub(r"\{[{%].*?[%}]\}", " ", template))
    # The report's Limitations and its "What was checked" list (the same check labels as the
    # dashboard and the CLI): B2 and B3 from the live tests.
    texts += render.LIMITATIONS + check_labels()
    assert [t for t in texts if old_phrase(t)] == []


def check_labels():
    """Every label a check can have in "What was checked"."""
    from app.checks import runner as checks_runner
    from app.discovery.runner import default_collectors
    from app.fingerprint import pipeline
    from app.wireless import survey

    labels = [c.label for c in default_collectors(None)]
    for module in (checks_runner, pipeline, survey):
        labels += [v for v in vars(module).values() if isinstance(v, dict) for v in v.values()]
    return [x for x in labels if isinstance(x, str) and x.split(" ")[0].istitle()]


def test_report_limitations_and_the_devices_list_use_the_shared_phrase():
    from app.vocabulary import CLUES_NOT_PROOF

    assert any(CLUES_NOT_PROOF in line for line in render.LIMITATIONS)
    data = json.loads((ROOT / "web/src/strings/en.json").read_text(encoding="utf-8"))
    assert CLUES_NOT_PROOF in data["results"]["allDevices"]["intro"]
    assert old_phrase("Types are hints from limited evidence.")  # the old wording is caught


def test_check_labels_say_what_was_checked_not_what_it_means():
    labels = check_labels()
    assert "Checking whether the router advertises UPnP controls" in labels
    inferences = ("open internet ports", "honestly", "copies of", "Asking cameras", "smart devices")
    for inference in inferences:
        assert not [x for x in labels if inference in x], inference


def test_the_shared_words_are_used():
    assert coverage_mod.STATE_TEXT == {
        "completed": "Checked",
        "limited": "Not checked (partly)",
        "not_run": "Not checked",
    }
    data = json.loads((ROOT / "web/src/strings/en.json").read_text(encoding="utf-8"))
    assert data["vocabulary"] == {
        "notDetected": "Not detected",
        "notChecked": "Not checked",
        "unconfirmed": "Unconfirmed",
        "resolved": "Resolved",
    }
    assert data["results"]["headline"]["none"].startswith("Not detected")
    assert data["handover"]["statusValue"]["resolved"] == "Resolved"


def test_the_ai_uses_the_same_words_and_the_validator_rejects_the_old_ones():
    for word in ('"Not detected"', '"Not checked"', '"Unconfirmed"'):
        assert word in ai.SYSTEM_PROMPT
    # Outside the one sentence that lists the old words to avoid, the prompt never uses them.
    assert not OLD_PHRASES.search(ai.SYSTEM_PROMPT.split('Never say "skipped"')[0])
    text = "A device on this network may be a camera. This is a hint, not proof."
    assert validator.problem_with_text(text, "High", "R-CAM") == "vocabulary"


# --- 4. report privacy choices --------------------------------------------------------------------


def session(tmp_path):
    return HandoverSession(BaselineStore(tmp_path / "b.db", FakeProtector()))


def report_html(result, state, privacy=None):
    return render.render_html(
        render.build_view(
            result,
            Explanations(),
            room_label=None,
            generated_at=T1,
            handover=state,
            privacy=privacy,
        )
    )


def named_check(tmp_path):
    cam = camera()
    cam.hostnames = ["cam-hallway"]
    result = check([cam])
    result.room_network = "Example-Home"
    s = session(tmp_path)
    subject = next(f.subject for f in result.findings)
    s.set_name(subject, "Hallway camera")
    s.set_note(subject, "Above the door")
    task = s.state_for(result).tasks[0]
    s.update_task(task.id, "asked", "Emailed the host on Monday")
    return result, s.state_for(result)


def test_by_default_names_are_in_and_notes_are_out(tmp_path):
    result, state = named_check(tmp_path)
    html = report_html(result, state)
    assert "Example-Home" in html and "Hallway camera" in html
    assert "Emailed the host on Monday" not in html and "Above the door" not in html


def test_notes_are_in_only_when_chosen(tmp_path):
    result, state = named_check(tmp_path)
    html = report_html(result, state, render.ReportPrivacy(notes=True))
    assert "Emailed the host on Monday" in html and "Your note: Above the door" in html


def test_the_network_name_and_device_names_can_be_left_out_everywhere(tmp_path):
    result, state = named_check(tmp_path)
    for f in result.findings:
        f.evidence = [*f.evidence, "Calls itself cam-hallway on Example-Home"]
    privacy = render.ReportPrivacy(network_name=False, device_names=False, notes=True)
    html = report_html(result, state, privacy)
    assert "Example-Home" not in html and "example-home" not in html.lower()
    assert "cam-hallway" not in html and "Hallway camera" not in html
    assert "[network name left out]" in html and "[device name left out]" in html
    assert "Emailed the host on Monday" in html  # the notes were still chosen


@pytest.fixture
def client(no_real_baseline_store, monkeypatch, tmp_path):
    monkeypatch.setattr(render, "render_pdf", lambda html: SAMPLE_PDF)
    monkeypatch.setattr(main.app.state, "report_dir", tmp_path / "reports", raising=False)
    monkeypatch.setattr(main.app.state, "last_result", None, raising=False)
    with TestClient(main.app) as c:
        c.store_path = no_real_baseline_store
        yield c


def test_the_report_api_takes_the_privacy_choices(client, monkeypatch):
    seen = {}
    real = render.make_report

    def spy(*a, **kw):
        seen["privacy"] = kw["privacy"]
        return real(*a, **kw)

    monkeypatch.setattr(render, "make_report", spy)
    main.app.state.last_result = check([camera()])
    client.post("/api/report", json={"timestamp": False})
    assert seen["privacy"] == render.ReportPrivacy(
        network_name=True, device_names=True, notes=False
    )
    client.post(
        "/api/report",
        json={
            "timestamp": False,
            "include_network_name": False,
            "include_device_names": False,
            "include_notes": True,
        },
    )
    assert seen["privacy"] == render.ReportPrivacy(
        network_name=False, device_names=False, notes=True
    )


# --- 5. delete all saved data ---------------------------------------------------------------


def test_delete_all_removes_everything_and_starts_a_new_salt(tmp_path):
    path = tmp_path / "b.db"
    s = HandoverSession(BaselineStore(path, FakeProtector()))
    result = check([camera()])
    subject = next(f.subject for f in result.findings)
    s.set_answer(subject, "landlord", confirmed=True)
    s.set_name(subject, "Hallway camera")
    s.set_note(subject, "Above the door")
    task = s.state_for(result).tasks[0]
    s.update_task(task.id, "asked", "Emailed")
    s.save_baseline(result, now=T0)
    old_salt = s.salt
    assert path.exists()
    s.delete_all()
    assert not path.exists()
    assert (s.answers, s.confirmed, s.names, s.notes, s.states, s.baseline) == (
        {},
        {},
        {},
        {},
        {},
        None,
    )
    assert s.salt != old_salt
    again = HandoverSession(BaselineStore(path, FakeProtector()))
    assert again.info().state == "none" and again.answers == {} and again.salt != old_salt


def test_delete_all_api_leaves_report_files_alone(client):
    from urllib.parse import quote

    main.app.state.last_result = check([camera()])
    subject = next(f.subject for f in main.app.state.last_result.findings)
    client.post("/api/answers", json={"subject": subject, "answer": "mine"})
    client.post("/api/names", json={"subject": subject, "name": "Hall cam", "note": "By the door"})
    task = client.get("/api/handover").json()
    client.post("/api/baseline")
    made = client.post("/api/report", json={"timestamp": False}).json()
    report_file = main.app.state.report_dir / made["pdf"]
    assert report_file.exists() and client.store_path.exists()
    body = client.delete("/api/data").json()
    assert body["baseline"]["state"] == "none"
    h = body["handover"]
    assert (h["answers"], h["names"], h["notes"], h["confirmed"]) == ({}, {}, {}, {})
    assert all(t["status"] == "todo" and t["notes"] == "" for t in h["tasks"])
    assert not client.store_path.exists()
    assert report_file.exists()  # saved reports aren't affected
    # The latest check now has new subjects: nothing new can be linked to what was deleted.
    new_subject = next(f.subject for f in main.app.state.last_result.findings)
    assert new_subject != subject
    assert task  # (the handover state before deleting was readable)
    assert quote  # keep the import used
