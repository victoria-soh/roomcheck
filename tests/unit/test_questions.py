"""Results restructure: the renter's questions, specific clues, and "unconfirmed" said once."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from app.discovery.models import CheckStatus, DiscoveryResult
from app.fingerprint.facts import device_facts
from app.fingerprint.scoring import fingerprint, load_weights
from app.questions import partly_line, question_statuses, status_line, strings, text
from app.rules.engine import load_rules
from app.rules.models import QUESTIONS, Finding
from tests.unit import devices as dev
from tests.unit.test_layer6 import T1, check

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS_TS = ROOT / "web" / "src" / "results" / "questions.ts"


# --- the page's copy of rules.yaml stays the same ----------------------------------------------


def _ts_block(name: str) -> str:
    src = QUESTIONS_TS.read_text("utf-8")
    m = re.search(rf"export const {name}[^=]*= \{{(.*?)\n\}};", src, re.S)
    assert m, name
    return m.group(1)


def test_the_pages_checks_per_question_match_rules_yaml():
    block = _ts_block("QUESTION_CHECKS")
    ts = {q: re.findall(r'"([a-z_]+)"', line) for q, line in re.findall(r"(\w+): \[(.*?)\]", block)}
    yaml_spec = {q: spec.checks for q, spec in load_rules().questions.items()}
    assert ts == yaml_spec


def test_the_pages_question_per_rule_matches_rules_yaml():
    ts = dict(re.findall(r'"(R-[A-Z-]+)": "(\w+)"', _ts_block("QUESTION_OF_RULE")))
    assert ts == {r.id: r.question for r in load_rules().rules}


def test_every_rule_answers_one_of_the_three_questions():
    data = yaml.safe_load((ROOT / "app" / "rules" / "rules.yaml").read_text("utf-8"))
    assert [r["question"] for r in data["rules"]]  # stated in the file, not defaulted
    assert {r.question for r in load_rules().rules} == set(QUESTIONS)


# --- clues -------------------------------------------------------------------------------------


def test_every_signal_has_one_plain_clue_sentence():
    for spec in load_weights().types.values():
        for s in spec.signals:
            assert s.clue.endswith(".") and s.clue[0].isupper(), s.id
            # A value goes in only where the signal matched one: a name, or open ports.
            if "{detail}" in s.clue:
                assert s.when.name_regex or s.when.ports_any, s.id


def test_a_camera_finding_lists_its_specific_clues_strongest_first():
    cam = dev.hikvision_camera()
    cam.hostnames = ["cam-hallway"]
    cam.fingerprint = fingerprint(device_facts(cam), "full")
    (finding,) = [f for f in check([cam]).findings if f.rule_id == "R-CAM"]
    assert finding.clues == [
        "It answers camera discovery requests (ONVIF).",
        "It offers a live video stream, the kind security cameras use.",
        "It has a port open that camera recorders often use (port 8000).",
        "Its maker mostly sells cameras.",
        "It calls itself “cam-hallway”.",
    ]
    # Never invented: each clue is a signal that matched.
    assert len(finding.clues) == len(cam.fingerprint.evidence)


def test_findings_without_device_clues_use_their_rules_observed_sentence():
    router = dev.tp_link_gateway()
    router.identity.open_ports = [23, 80]
    router.fingerprint = fingerprint(device_facts(router), "full")
    telnet = next(f for f in check([router]).findings if f.rule_id == "R-TELNET")
    assert telnet.clues == [] and telnet.observed


def test_unconfirmed_is_said_once_not_on_each_card():
    assert text("results.questions.pageNote") == "Device types are unconfirmed: clues, not proof."
    for rule in load_rules().rules:
        for field in (rule.explanation, rule.why_it_matters, rule.observed):
            for value in field.values() if isinstance(field, dict) else [field]:
                assert "not proof" not in value, rule.id
    assert "bandHelp" not in strings()["results"]


# --- grouping and status -----------------------------------------------------------------------


def _finding(rule_id: str, question: str, severity: str, **over: object) -> Finding:
    base = {
        "id": f"{rule_id}:{over.get('device_ref') or over.get('nearby_ref') or 'network'}",
        "rule_id": rule_id,
        "question": question,
        "severity": severity,
        "confidence_band": "Likely",
        "device_ref": None,
        "title": rule_id,
        "evidence": [],
        "next_step": "",
    }
    return Finding.model_validate({**base, **over})


def _result(findings: list[Finding], checks: list[CheckStatus] | None = None) -> DiscoveryResult:
    ran = [
        CheckStatus(name=n, label=n, status="ran")
        for n in ("passive_listen", "cve", "wifi_encryption", "bluetooth")
    ]
    return DiscoveryResult(
        started_at=T1,
        finished_at=T1,
        mode="full",
        network=None,
        devices=[],
        checks=checks if checks is not None else ran,
        findings=findings,
    )


def test_a_nearby_signal_is_under_its_question_on_results():
    tracker = _finding(
        "R-TRACKER", "watching", "Medium", scope="nearby", shown_on="nearby", nearby_ref="bt:1"
    )
    (watching, control, wifi) = question_statuses(_result([tracker]))
    assert watching.things == 1 and watching.cards[0].kind == "nearby"
    assert status_line(watching) == "1 thing to look at"
    assert (control.state, wifi.state) == ("not_detected", "not_detected")


def test_info_sits_in_the_same_devices_card_even_under_another_question():
    cam = _finding("R-CAM", "watching", "High", device_ref="d1")
    cve = _finding("R-CVE", "control", "Info", device_ref="d1")
    (watching, control, _) = question_statuses(_result([cve, cam]))
    assert watching.cards[0].also == ["R-CVE:d1"]
    assert control.things == 0 and control.also == []


def test_an_info_item_with_no_card_is_listed_and_not_counted():
    cve = _finding("R-CVE", "control", "Info", device_ref="d1")
    (_, control, _) = question_statuses(_result([cve]))
    assert (control.things, control.state, control.also) == (0, "info", ["R-CVE:d1"])
    assert status_line(control) == "1 item for information only"


def test_low_counts_as_a_thing_to_look_at():
    upnp = _finding("R-UPNP", "wifi", "Low")
    (_, _, wifi) = question_statuses(_result([upnp]))
    assert wifi.things == 1


def test_a_question_whose_checks_didnt_run_says_not_checked_with_the_reason():
    checks = [
        CheckStatus(name="passive_listen", label="l", status="ran"),
        CheckStatus(
            name="wifi_encryption",
            label="w",
            status="skipped",
            reason="Not checked, because you chose a listen-only check.",
        ),
        CheckStatus(name="dns", label="d", status="failed", reason="Something broke."),
    ]
    (watching, _, wifi) = question_statuses(_result([], checks))
    assert (wifi.state, status_line(wifi)) == (
        "not_checked",
        "Not checked: you chose a listen-only check",
    )
    assert partly_line(wifi) is None  # said once, as the status
    # Some of watching's checks ran: not detected, nothing to name as not checked here.
    assert (watching.state, partly_line(watching)) == ("not_detected", None)


def test_no_status_line_reads_as_passed_or_safe():
    for key in ("look", "info", "notDetected", "notChecked"):
        node = strings()["results"]["questions"]["status"]
        for k, v in node.items():
            if k.startswith(key):
                assert not re.search(r"\b(safe|passed|clear|ok|harmless)\b", v, re.I), v
