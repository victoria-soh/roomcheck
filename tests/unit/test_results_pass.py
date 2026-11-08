"""The Results wording pass, backend side: every rule's "What it could mean" sentence differs
from its "What we observed" sentence (in the rules and in the PDF), no rule text reassures,
"host" instead of "landlord" in user-facing text, and the short reason each check gets for the
Coverage and limits rows."""

import re
from pathlib import Path

import yaml

from app.coverage import coverage, short_phrase
from app.discovery.messages import MESSAGES, message_for
from app.discovery.models import CheckStatus
from app.explain.models import Explanations
from app.explain.validator import _REASSURANCE
from app.report import render
from app.rules.engine import Rule, load_rules
from app.rules.models import Finding
from tests.unit.test_report import scan_result

ROOT = Path(__file__).resolve().parents[2]


def norm(text: str) -> str:
    return " ".join(text.lower().split()).rstrip(".")


def variants(rule: Rule) -> list[str | None]:
    """Every variant a rule's texts can take (None for rules without variants)."""
    keys: set[str] = set()
    for value in (rule.severity, rule.title, rule.observed, rule.could_mean, rule.explanation):
        if isinstance(value, dict):
            keys |= set(value)
    return sorted(keys) or [None]


def finding_for(rule: Rule, variant: str | None) -> Finding:
    pick = lambda v: rule.pick(v, variant)  # noqa: E731
    return Finding(
        id=f"{rule.id}:test",
        rule_id=rule.id,
        severity=pick(rule.severity),
        confidence_band="Likely",
        device_ref=None,
        title=pick(rule.title),
        observed=pick(rule.observed),
        could_mean=pick(rule.could_mean),
        evidence=["test evidence"],
        next_step=pick(rule.next_step),
        standard_explanation=pick(rule.explanation),
        standard_why=pick(rule.why_it_matters),
    )


def test_every_rule_has_a_could_mean_sentence_that_isnt_what_was_observed():
    rules = load_rules().rules
    assert len(rules) >= 19
    for rule in rules:
        for v in variants(rule):
            f = finding_for(rule, v)
            assert f.could_mean.strip(), rule.id
            assert norm(f.could_mean) != norm(f.observed), (rule.id, v)
            # Nor a sentence of the observed text, nor the observed text inside it.
            assert norm(f.observed) not in norm(f.could_mean), (rule.id, v)


def test_in_the_pdf_what_it_could_mean_never_repeats_what_was_observed():
    result = scan_result()
    result.findings = [finding_for(r, v) for r in load_rules().rules for v in variants(r)]
    when = result.finished_at
    view = render.build_view(result, Explanations(), room_label=None, generated_at=when)
    html = render.render_html(view)
    observed = re.findall(r"<b>What we observed:</b>\s*(.*?)</p>", html, re.S)
    meaning = re.findall(r"<b>What it could mean:</b>\s*(.*?)</p>", html, re.S)
    assert len(observed) == len(meaning) == len(result.findings)
    for o, m in zip(observed, meaning, strict=True):
        assert m.strip() and norm(m) != norm(o)


def test_no_rule_text_reassures():
    for rule in load_rules().rules:
        for v in variants(rule):
            f = finding_for(rule, v)
            texts = (f.observed, f.could_mean, f.next_step, f.standard_explanation, f.standard_why)
            for text in texts:
                assert not _REASSURANCE.search(text), (rule.id, text)


def strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)


def test_host_never_landlord_in_user_facing_text():
    texts = list(MESSAGES.values())
    for f in ("app/rules/rules.yaml", "app/handover/tasks.yaml"):
        data = yaml.safe_load((ROOT / f).read_text(encoding="utf-8"))
        # Values only: "landlord_or_host" is a stored value for "who", never shown as is.
        texts += [s for s in strings(data) if s != "landlord_or_host"]
    template = (ROOT / "app/report/templates/report.html.j2").read_text(encoding="utf-8")
    texts.append(re.sub(r"\{[{%].*?[%}]\}", " ", template))
    texts += list(render.ANSWER_TEXT.values())
    # Only "the landlord's agent", whom a renter reports a hidden camera to.
    assert [t for t in texts if re.search(r"landlord(?!'s agent)", t, re.I)] == []


def test_each_check_that_didnt_run_gets_a_short_reason():
    result = scan_result()
    result.checks = [
        CheckStatus(name="dhcp", label="x", status="failed", reason=message_for("no_dhcp_offer")),
        CheckStatus(
            name="bluetooth", label="x", status="failed", reason=message_for("bluetooth_off")
        ),
        CheckStatus(name="dns", label="x", status="skipped", reason=message_for("passive_mode")),
        CheckStatus(name="upnp", label="x", status="ran"),
    ]
    coverage(result)
    short = {c.name: c.short_reason for c in result.checks}
    assert short["upnp"] is None
    assert short["dns"] == "you chose a listen-only check"
    assert short["dhcp"] and len(short["dhcp"]) < len(message_for("no_dhcp_offer"))
    assert short["bluetooth"]


def test_no_short_reason_repeats_not_checked():
    """Every message a check can carry becomes a short phrase, so "Not checked: <reason>" (in
    Coverage and limits and the PDF's table) never says "Not checked" twice."""
    for code, text in MESSAGES.items():
        for name, status in (("dhcp", "failed"), ("dns", "skipped"), ("bluetooth", "failed")):
            result = scan_result()
            result.checks = [CheckStatus(name=name, label="x", status=status, reason=text)]
            rows = coverage(result)
            short = result.checks[0].short_reason or ""
            assert not re.search(r"not checked", short, re.I), (code, short)
            assert not short.endswith("."), (code, short)
            for row in rows:
                assert not re.search(r"not checked", row.reason or "", re.I), (code, row.reason)
    assert short_phrase(message_for("passive_mode")) == "you chose a listen-only check"
    assert short_phrase(message_for("no_dhcp_offer")) == "no device answered the address request"
