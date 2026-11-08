"""Follow-up to the typography pass: digits, R-UPNP, timeout reasons, handover fixtures, totals."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import yaml

from app.coverage import AREAS, CHECK_NOUN, check_counts, check_rows, table_rows
from app.discovery.models import DiscoveryResult
from app.explain.models import Explanations
from app.handover.models import HandoverState
from app.report import render
from tests.unit import demo_data

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "web" / "src" / "test" / "demo"


def _demo(name: str) -> DiscoveryResult:
    return DiscoveryResult.model_validate_json((DEMO / f"{name}.json").read_text("utf-8"))


def _html(result: DiscoveryResult) -> str:
    return render.render_html(
        render.build_view(result, Explanations(), room_label=None, generated_at=result.finished_at)
    )


# --- 1: digits from Plus Jakarta Sans ----------------------------------------------------------


def test_the_pdf_takes_digits_from_plus_jakarta_under_the_body_family_name():
    html = _html(_demo("result_quiet_full"))
    faces = re.findall(r"@font-face \{[^}]*\}", html)
    body = [f for f in faces if '"Atkinson Hyperlegible Next"' in f]
    digits = [f for f in body if "unicode-range: U+0030-0039" in f]
    assert sorted(re.search(r"font-weight: (\d+)", f)[1] for f in digits) == ["400", "600", "700"]
    # Each digit face is Plus Jakarta Sans's own file at the same weight...
    for weight in (400, 600, 700):
        jakarta = (ROOT / "app/report/data" / f"jakarta-{weight}.woff2").read_bytes()
        data = base64.b64encode(jakarta).decode("ascii")
        assert any(data in f and f"font-weight: {weight}" in f for f in digits), weight
    # ...declared after Atkinson's own faces, so it wins for digits only.
    atkinson = [faces.index(f) for f in body if f not in digits]
    assert max(atkinson) < min(faces.index(f) for f in digits)
    # JetBrains Mono keeps its own digits.
    assert not any("unicode-range" in f for f in faces if "JetBrains Mono" in f)


def test_the_page_takes_digits_from_plus_jakarta_too():
    css = (ROOT / "web/src/styles/digits.css").read_text("utf-8")
    assert css.count('font-family: "Atkinson Hyperlegible Next"') == 3
    assert css.count("unicode-range: U+0030-0039") == 3
    for weight in (400, 600, 700):
        assert f"plus-jakarta-sans-latin-{weight}-normal.woff2" in css
    assert "http" not in css  # bundled, never fetched
    main = (ROOT / "web/src/main.tsx").read_text("utf-8")
    assert main.index("atkinson-hyperlegible-next/700.css") < main.index("./styles/digits.css")


# --- 2: R-UPNP's next step ---------------------------------------------------------------------


def test_upnp_next_step_is_one_ask():
    rules = yaml.safe_load((ROOT / "app/rules/rules.yaml").read_text("utf-8"))["rules"]
    upnp = next(r for r in rules if r["id"] == "R-UPNP")
    assert upnp["next_step"] == "Ask the host whether UPnP can be turned off."


# --- 3: a timed-out check is named -------------------------------------------------------------


def test_a_timeout_reason_names_the_check_lowercase_after_the_colon():
    rows = dict(check_rows(_demo("result_full")))
    assert rows["Checking for a second device handing out network addresses"] == (
        "Not checked: the second-address-server check took too long and was stopped"
    )
    # Every check has a name for its own timeout reason.
    assert {n for _, _, names in AREAS for n in names} <= set(CHECK_NOUN)
    assert not any("it took too long" in line for line in rows.values())


# --- 5: each nothing-found fixture has its own handover data -----------------------------------


def test_each_demo_check_has_handover_data_that_matches_its_findings():
    for result_name, handover_name in (
        ("result_full", "handover"),
        ("result_listening", "handover_listening"),
        ("result_quiet_full", "handover_quiet_full"),
    ):
        result = _demo(result_name)
        handover = HandoverState.model_validate(
            json.loads((DEMO / f"{handover_name}.json").read_text("utf-8"))
        )
        finding_ids = {f.id for f in result.findings}
        assert {t.finding_id for t in handover.tasks} <= finding_ids, result_name
    built = demo_data.build()
    assert built["handover_listening"] == demo_data.handover_for(built["result_listening"])


# --- 6: the device rows add up to the summary's number -----------------------------------------


def test_the_total_row_matches_the_summary_and_is_not_counted_as_a_check():
    for name in ("result_quiet_full", "result_listening", "result_full"):
        result = _demo(name)
        rows = table_rows(result)
        assert len(rows) == len(result.checks) + 1  # the total isn't a check
        assert check_counts(result)[0] + check_counts(result)[1] == len(result.checks)
        labels = [label for label, _ in rows]
        total = labels.index("Devices heard in all")
        # Straight after the device-finding checks.
        assert labels[total - 1] == "Sending a camera discovery request (ONVIF)"
        n = len(result.devices)
        assert rows[total][1] == f"{n} devices, each counted once however many checks heard it"
    quiet = _demo("result_quiet_full")
    html = _html(quiet)
    assert "Devices heard in all" in html
    assert "9 devices, each counted once however many checks heard it" in html
