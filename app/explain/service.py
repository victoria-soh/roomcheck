"""Explain findings: AI when allowed, configured and valid; the rule YAML's text otherwise.

Fallbacks (docs/original-plan.md, "Error handling"): no ANTHROPIC_API_KEY, offline mode, an API
error, the 8 s timeout or rejected output all fall back to the standard text. Nothing else is shown
to the user except the label switching to "Standard explanation".
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

from app.config import Settings, get_settings
from app.discovery.models import Device
from app.explain import ai, validator
from app.explain.models import (
    AI_LABEL,
    AI_MESSAGE_LABEL,
    STANDARD_LABEL,
    STANDARD_MESSAGE_LABEL,
    AiStatus,
    Explanation,
    Explanations,
    LandlordMessage,
    reason_text,
)
from app.rules.models import Finding
from app.wireless.models import NearbyItem

log = logging.getLogger(__name__)

OPEN_SEVERITIES = ("High", "Medium")
AiCall = Callable[[Settings, list[dict[str, Any]]], dict[str, Any]]


def standard_explanation(f: Finding) -> Explanation:
    return Explanation(
        finding_id=f.id,
        explanation=f.standard_explanation,
        why_it_matters=f.standard_why,
        source="standard",
        label=STANDARD_LABEL,
    )


def message_findings(findings: Sequence[Finding]) -> list[Finding]:
    """The findings a message to the landlord or host asks about: High or Medium, with a
    question."""
    return [f for f in findings if f.severity in OPEN_SEVERITIES and f.landlord_question]


def standard_landlord_message(findings: Sequence[Finding]) -> LandlordMessage | None:
    """One polite message asking each open finding's question once, most serious first."""
    covered = message_findings(findings)
    questions = list(
        dict.fromkeys(validator.hedge_camera(f.landlord_question or "") for f in covered)
    )
    if not questions:
        return None
    lines = [
        "Hello,",
        "",
        "I've just moved in and ran a quick check of the connected devices and Wi-Fi in the "
        "room. A few things came up that I'd like to ask you about:",
        "",
        *[f"{n}. {q}" for n, q in enumerate(questions, 1)],
        "",
        "Thank you for your help.",
    ]
    return LandlordMessage(
        text="\n".join(lines),
        source="standard",
        label=STANDARD_MESSAGE_LABEL,
        covers=[f.id for f in covered],
    )


def explain(
    findings: Sequence[Finding],
    devices: Sequence[Device] = (),
    nearby: Sequence[NearbyItem] = (),
    *,
    online: bool = True,
    settings: Settings | None = None,
    call: AiCall = ai.call_ai,
) -> Explanations:
    standard = {f.id: standard_explanation(f) for f in findings}
    message = standard_landlord_message(findings)

    def result(
        status: AiStatus,
        items: dict[str, Explanation] | None = None,
        reason: str | None = None,
        rejected: dict[str, str] | None = None,
    ) -> Explanations:
        chosen = items or standard
        return Explanations(
            items=[chosen[f.id] for f in findings],
            landlord_message=message,
            ai_status=status,
            ai_reason=reason,
            ai_reason_text=reason_text(reason) if reason else None,
            ai_rejected=rejected or {},
        )

    if not findings:
        return result("none")
    if not online:
        return result("offline", reason="offline")
    settings = settings or get_settings()
    if settings.anthropic_api_key is None:
        return result("not_configured", reason="not_configured")

    payload, ids = ai.build_payload(findings, devices, nearby)
    try:
        raw = call(settings, payload)
        out = validator.parse_output(raw, set(ids))
    except ai.AiUnavailable as e:
        log.info("AI explanations not used (%s); using standard text", e.reason)
        return result("failed", reason=e.reason)
    except validator.OutputRejected as e:
        log.info("AI explanations rejected (%s); using standard text", e.reason)
        return result("rejected", reason=e.reason)

    by_id = {f.id: f for f in findings}
    items = dict(standard)
    rejected: dict[str, str] = {}
    used = 0
    for item in out.explanations:
        finding = by_id[ids[item.finding_id]]
        problem = validator.check_explanation(item, finding.severity, finding.rule_id)
        if problem:
            log.info("AI explanation for %s rejected (%s)", finding.rule_id, problem)
            rejected[finding.rule_id] = problem
            continue
        items[finding.id] = Explanation(
            finding_id=finding.id,
            explanation=" ".join(item.explanation.split()),
            why_it_matters=" ".join(item.why_it_matters.split()),
            source="ai",
            label=AI_LABEL,
        )
        used += 1

    if message is not None:
        covered = message_findings(findings)
        problem = validator.check_landlord_message(
            out.landlord_message, [f.rule_id for f in covered]
        )
        if problem:
            log.info("AI landlord message rejected (%s); using the standard message", problem)
            rejected["landlord_message"] = problem
        else:
            message = LandlordMessage(
                text=out.landlord_message.strip(),
                source="ai",
                label=AI_MESSAGE_LABEL,
                covers=[f.id for f in covered],
            )

    status: AiStatus = "used" if used == len(findings) else "partly_used" if used else "rejected"
    if rejected:
        reason: str | None = "item_checks"
    elif used < len(findings):
        reason = "missing_items"
    else:
        reason = None
    return result(status, items, reason, rejected)
