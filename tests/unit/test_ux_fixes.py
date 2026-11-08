"""Backend parts of the UX fixes: the reason code behind each coverage row (so the Results page
can offer the one recovery step that fixes it), and "move-in scan" instead of "baseline"."""

import re

from app.coverage import coverage
from app.discovery.messages import MESSAGES, message_for
from app.discovery.models import CheckStatus
from tests.unit.test_report import scan_result


def with_checks(*checks: CheckStatus):
    result = scan_result()
    result.checks = list(checks)
    return result


def check(name: str, status: str, code: str | None = None, reason: str | None = None):
    text = message_for(code) if code else reason
    return CheckStatus(name=name, label=name, status=status, reason=text)


def test_each_partial_coverage_row_carries_its_reason_code():
    rows = coverage(
        with_checks(
            check("nearby_wifi", "failed", "location_off"),
            check("bluetooth", "failed", "bluetooth_off"),
            check("dns", "ran"),
            check("dhcp", "skipped", "passive_mode"),
        )
    )
    codes = {r.area: r.reason_code for r in rows}
    assert codes == {
        "nearby_wifi": "location_off",
        "bluetooth": "bluetooth_off",
        "router": "passive_mode",
    }


def test_a_completed_row_or_an_unknown_reason_has_no_code():
    rows = coverage(
        with_checks(
            check("nearby_wifi", "ran"),
            check("bluetooth", "failed", reason="Something odd happened."),
        )
    )
    assert [(r.area, r.reason_code) for r in rows] == [("nearby_wifi", None), ("bluetooth", None)]


def test_no_message_uses_the_bare_word_baseline():
    assert [m for m in MESSAGES.values() if re.search(r"\bbaseline\b", m, re.IGNORECASE)] == []
    assert message_for("baseline_unreadable").endswith("Start a new move-in scan.")
