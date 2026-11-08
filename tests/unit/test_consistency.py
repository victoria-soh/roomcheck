"""Things that must say the same everywhere.

1. The list of outside calls: Help renders it from en.json as a table (privacy.intro and
   privacy.calls: Call, When, What's sent), and the README repeats each row word for word as
   "<call> (<when>): <what's sent>".
2. The demo check's numbers: the PDF counts as Results and the Report summary do (the same
   expectations are checked on the page in web/src/screens/Consistency.test.tsx), from the JSON
   copy of the page's demo fixture (web/src/test/demoFixture.test.ts keeps it in step).
"""

import json
import re
from pathlib import Path

from app.discovery.models import DiscoveryResult
from app.explain.models import (
    AI_LABEL,
    AI_MESSAGE_LABEL,
    STANDARD_LABEL,
    Explanations,
)
from app.questions import partly_line, question_statuses, status_line
from app.report import render

ROOT = Path(__file__).resolve().parents[2]

# The demo check, as Results and the Report summary show it (the same numbers are checked on the
# page in web/src/screens/Consistency.test.tsx): things to look at per question, their total,
# each question's status line, and the coverage line.
EXPECTED_THINGS = 5
EXPECTED_PER_QUESTION = [("watching", 2), ("control", 0), ("wifi", 3)]
EXPECTED_PER_QUESTION_TEXT = "Watching 2 · Control 0 · Wi-Fi 3"
EXPECTED_STATUS = {
    "watching": ("2 things to look at", None),
    "control": ("Not detected by the checks that ran", None),
    "wifi": (
        "3 things to look at",
        "Not checked: the second-address-server check took too long and was stopped",
    ),
}
EXPECTED_COVERAGE = "17 of 18 checks ran"


def readme_line(call: dict[str, str]) -> str:
    """One row of Help's "What's sent" table (Call, When, What's sent) as the README says it."""
    return f"{call['call']} ({call['when']}): {call['sent']}"


def test_readme_lists_the_outside_calls_word_for_word():
    strings = json.loads((ROOT / "web/src/strings/en.json").read_text(encoding="utf-8"))
    privacy = strings["privacy"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## What's sent", 1)[1].split("\n## ", 1)[0]
    lines = [line.strip() for line in section.strip().splitlines() if line.strip()]
    assert lines[0] == privacy["intro"]
    # Help's table cells, read back as one line each, are the README's list word for word.
    assert [line.removeprefix("- ") for line in lines[1:]] == [
        readme_line(privacy["calls"][k]) for k in ("ai", "nvd", "tsa")
    ]
    # And each call states its default.
    assert "off unless" in privacy["calls"]["ai"]["when"]
    assert "on in a full check" in privacy["calls"]["nvd"]["when"]
    assert "on by default" in privacy["calls"]["tsa"]["when"]


DEMO = ROOT / "web" / "src" / "test" / "demo"


def demo_result() -> DiscoveryResult:
    """The demo check the page shows (made by the pipeline: tests/unit/demo_data.py)."""
    return DiscoveryResult.model_validate_json((DEMO / "result_full.json").read_text("utf-8"))


def demo_explanations() -> Explanations:
    """The demo's explanations as the backend would hand them over (with their labels)."""
    explanations = demo_result().explanations
    assert explanations is not None
    return explanations


def test_the_demo_tells_one_ai_story():
    # AI is on in the demo: every finding explained by AI, on the page and in the PDF alike.
    explanations = demo_explanations()
    assert explanations.ai_status == "used"
    result = demo_result()
    assert {i.finding_id for i in explanations.items} == {f.id for f in result.findings}
    assert all(i.source == "ai" for i in explanations.items)
    assert explanations.landlord_message is not None
    assert explanations.landlord_message.label == AI_MESSAGE_LABEL
    html = render.render_html(
        render.build_view(result, explanations, room_label=None, generated_at=result.finished_at)
    )
    assert html.count(AI_LABEL) == len(result.findings)
    assert STANDARD_LABEL not in html


def test_the_pdf_counts_the_demo_check_as_results_does():
    result = demo_result()
    questions = question_statuses(result)
    assert [(q.id, q.things) for q in questions] == EXPECTED_PER_QUESTION
    assert {q.id: (status_line(q), partly_line(q)) for q in questions} == EXPECTED_STATUS
    view = render.build_view(
        result, Explanations(), room_label=None, generated_at=result.finished_at
    )
    assert view["things"] == EXPECTED_THINGS
    assert view["per_question"] == EXPECTED_PER_QUESTION_TEXT
    assert view["coverage_line"] == EXPECTED_COVERAGE
    html = render.render_html(view)
    banner = re.search(r'<div class="banner">(.*?)</div>', html, re.S).group(1)
    assert f"{EXPECTED_THINGS} things to look at: {EXPECTED_PER_QUESTION_TEXT}" in banner
    assert f"<p>{EXPECTED_COVERAGE}</p>" in html
    # Each question's heading and status line, in order, then the fourth from Compare.
    titles = re.findall(r"<h2>(.*?)</h2>", html)
    # After page 1 (for the host, the tasks, the physical check) and "Findings in detail".
    start = titles.index("Findings in detail") + 1
    assert titles[start : start + 4] == [
        "Is anything watching?",
        "Can someone else control things here?",
        "Can you trust this Wi-Fi?",
        "What&#39;s changed since move-in?",
    ]
    statuses = re.findall(r'<p class="status">(.*?)</p>', html)
    assert statuses[:3] == [EXPECTED_STATUS[q][0] for q in ("watching", "control", "wifi")]
    # One row per check, as in Coverage and limits on Results, plus the devices total (which
    # isn't a check, so the "18 checks" line never counts it).
    assert len(view["check_rows"]) == len(result.checks) + 1 == 19
    assert sum(label == "Devices heard in all" for label, _ in view["check_rows"]) == 1


def test_the_pdf_puts_info_inside_its_device_card_and_never_counts_it():
    result = demo_result()
    (watching, control, _) = question_statuses(result)
    camera = next(c for c in watching.cards if c.finding_ids[0].startswith("R-CAM:"))
    assert camera.also == [camera.finding_ids[0].replace("R-CAM:", "R-CVE:")]
    assert control.things == 0 and control.also == []
    html = render.render_html(
        render.build_view(result, Explanations(), room_label=None, generated_at=result.finished_at)
    )
    # Inside the camera's card, and the open networks (Info) at the end of the Wi-Fi question.
    assert html.count("<b>Also found</b>") == 2


def test_the_pdf_lists_the_specific_clues_and_says_unconfirmed_once():
    result = demo_result()
    html = render.render_html(
        render.build_view(result, Explanations(), room_label=None, generated_at=result.finished_at)
    )
    for clue in (
        "It answers camera discovery requests (ONVIF).",
        "It offers a live video stream, the kind security cameras use.",
        "It has a port open that camera recorders often use (port 8000).",
        "It calls itself “cam-hallway”.",
    ):
        assert f"<li>{clue}</li>" in html
    assert html.count("Device types are unconfirmed: clues, not proof.") == 1


WORD = {"High": "Look at this first", "Medium": "Look at this soon"}


def test_the_pdf_marks_priority_with_the_app_icon_and_word_not_brackets():
    result = demo_result()
    html = render.render_html(
        render.build_view(result, Explanations(), room_label=None, generated_at=result.finished_at)
    )
    for marker in ("[!!]", "[!]", "[-]", "[i]"):
        assert marker not in html
    # The icon, then the word, as on the cards: e.g. the octagon then "Look at this first".
    for colour, level in (("#b42318", "High"), ("#b54708", "Medium")):
        icon = rf'<svg class="icon"[^>]*stroke="{colour}"[^>]*>.*?</svg>'
        assert re.search(icon + f" {WORD[level]}", html)
    banner = re.search(r'<div class="banner">(.*?)</div>', html, re.S).group(1)
    assert banner.startswith('<svg class="icon"')


def test_the_pdf_network_uses_documentation_addresses():
    result = demo_result()
    html = render.render_html(
        render.build_view(result, Explanations(), room_label=None, generated_at=result.finished_at)
    )
    assert "<td><b>Network checked</b></td><td>192.0.2.0/24" in html
    assert "192.168." not in html
