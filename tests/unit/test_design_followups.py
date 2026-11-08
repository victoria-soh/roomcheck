"""Design follow-ups: weak camera clues, one scale per card, coverage wording, bundled fonts."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.coverage import COUNTING, DETECTING, check_rows
from app.discovery.models import DiscoveryResult
from app.explain.models import Explanations
from app.main import CONTENT_SECURITY_POLICY
from app.questions import question_statuses, weak_camera_line
from app.report import render
from tests.unit import demo_data

ROOT = Path(__file__).resolve().parents[2]
STRINGS = json.loads((ROOT / "web/src/strings/en.json").read_text("utf-8"))
DEMO = ROOT / "web" / "src" / "test" / "demo"


def _demo(name: str) -> DiscoveryResult:
    return DiscoveryResult.model_validate_json((DEMO / f"{name}.json").read_text("utf-8"))


def _html(result: DiscoveryResult) -> str:
    return render.render_html(
        render.build_view(result, Explanations(), room_label=None, generated_at=result.finished_at)
    )


# --- A: a weak camera clue stays visible --------------------------------------------------------


def test_a_weak_camera_clue_is_said_under_watching_and_never_counted():
    quiet = _demo("result_quiet_full")
    watching = question_statuses(quiet)[0]
    assert watching.things == 0 and watching.state == "not_detected"
    assert len(watching.weak_camera) == 1
    line = (
        "1 device gave a weak camera clue. Not enough to flag it, "
        "but worth a look during the physical check."
    )
    assert weak_camera_line(watching) == line
    assert line in _html(quiet)
    # A flagged camera is never also a weak clue.
    assert question_statuses(_demo("result_full"))[0].weak_camera == []


# --- B: one scale per card ----------------------------------------------------------------------


def test_the_pdf_uses_the_urgency_words_with_confidence_apart():
    html = _html(demo_data.full_check())
    assert "Likely camera · " in html and "Look at this first" in html
    assert "identification confidence Likely · priority: Look at this first" in html
    assert not re.search(r"Priority: (High|Medium|Low|Info)\b", html)
    assert STRINGS["results"]["severity"] == {
        "High": "Look at this first",
        "Medium": "Look at this soon",
        "Low": "Worth knowing",
        "Info": "For information",
    }


# --- C: coverage rows in their own words ---------------------------------------------------------


def test_every_check_has_its_own_row_wording_and_none_says_safe_or_passed():
    rows = STRINGS["results"]["limits"]["rows"]
    for name in set(DETECTING) | COUNTING:
        assert name in rows or f"{name}_one" in rows, name
    for text in rows.values():
        assert not re.search(r"\b(safe|passed|clear)\b", text, re.I), text


def test_the_pdf_rows_say_what_each_check_heard():
    rows = dict(check_rows(_demo("result_quiet_full")))
    assert rows["Checking for other networks using your Wi-Fi's name"] == (
        "No copies of your Wi-Fi name"
    )
    assert rows["Checking how your Wi-Fi connection is encrypted"] == "No weak encryption found"
    assert re.fullmatch(r"Heard \d+ nearby networks", rows["Looking at nearby Wi-Fi"])
    assert "Not detected" not in rows.values()


# --- E: fonts, bundled ---------------------------------------------------------------------------


def test_the_pdf_embeds_its_fonts_and_fetches_nothing():
    html = _html(_demo("result_full"))
    for family in ("Atkinson Hyperlegible Next", "Plus Jakarta Sans", "JetBrains Mono", "Saira"):
        assert f'font-family: "{family}"' in html
    assert "fonts.googleapis" not in html and "fonts.gstatic" not in html
    assert not re.search(r"url\((?!data:)", html)  # every font is inline data


def test_the_dashboard_still_loads_fonts_only_from_itself():
    assert "font-src 'self'" in CONTENT_SECURITY_POLICY
    main = (ROOT / "web/src/main.tsx").read_text("utf-8")
    for pkg in ("atkinson-hyperlegible-next", "plus-jakarta-sans", "jetbrains-mono", "saira"):
        assert f"@fontsource/{pkg}/" in main
    assert "fonts.googleapis" not in (ROOT / "web/index.html").read_text("utf-8")


def test_every_font_is_credited_with_its_licence():
    licences = (ROOT / "FONT-LICENSES.md").read_text("utf-8")
    readme = (ROOT / "README.md").read_text("utf-8")
    for font, file in (
        ("Plus Jakarta Sans", "plus-jakarta-sans-OFL.txt"),
        ("Atkinson Hyperlegible Next", "atkinson-hyperlegible-next-OFL.txt"),
        ("JetBrains Mono", "jetbrains-mono-OFL.txt"),
        ("Saira", "saira-OFL.txt"),
    ):
        assert font in licences and font in readme
        text = (ROOT / "app/report/data" / file).read_text("utf-8")
        assert "SIL Open Font License, Version 1.1" in text
