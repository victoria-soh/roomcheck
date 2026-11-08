"""Turn High and Medium findings into handover tasks, from fixed templates (tasks.yaml), and
bundle the open ones into one message for the landlord or host. Pure functions, no I/O apart
from reading the template file once."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from app.discovery.models import DiscoveryResult
from app.explain import validator
from app.explain.models import STANDARD_MESSAGE_LABEL, LandlordMessage
from app.handover.models import (
    AdjustedSteps,
    Answer,
    RecheckOffer,
    Suggestion,
    SupportLink,
    Task,
    TaskState,
    Who,
)
from app.rules.engine import location_step
from app.rules.models import Finding, Location, StayType

TEMPLATES_FILE = Path(__file__).with_name("tasks.yaml")
TASK_SEVERITIES = ("High", "Medium")
SEVERITY_ORDER = {"High": 0, "Medium": 1, "Low": 2, "Info": 3}


class Template(BaseModel):
    category: str
    title: str
    ask: str
    who: Who
    steps: list[str] = []
    optional: list[Suggestion] = []


class Templates(BaseModel):
    categories: dict[str, dict[str, list[str]]]
    templates: dict[str, Template]
    recognition: dict[str, str]
    support_pages: list[dict[str, str]]

    def steps_for(self, rule_id: str) -> list[str]:
        t = self.templates[rule_id]
        return [*self.categories[t.category]["steps"], *t.steps]


@lru_cache(maxsize=1)
def load_templates(path: Path = TEMPLATES_FILE) -> Templates:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    templates = Templates.model_validate(data)
    for rule_id, t in templates.templates.items():
        if t.category not in templates.categories:
            raise ValueError(f"{rule_id}: unknown category {t.category!r}")
        if not t.ask.rstrip().endswith("?"):
            raise ValueError(f"{rule_id}: ask must be a question")
    return templates


def support_for(maker: str | None, templates: Templates) -> SupportLink | None:
    """The maker's own support page, if the maker is one we have a page for."""
    if not maker:
        return None
    for page in templates.support_pages:
        if re.search(rf"\b{re.escape(page['match'])}\b", maker, re.IGNORECASE):
            return SupportLink(name=page["name"], url=page["url"])
    return None


def _maker_for(finding: Finding, result: DiscoveryResult) -> str | None:
    if finding.device_ref:
        device = next((d for d in result.devices if d.id == finding.device_ref), None)
        return device.vendor if device else None
    if finding.nearby_ref:
        item = next((i for i in result.nearby_items if i.ref == finding.nearby_ref), None)
        return item.maker if item else None
    if finding.scope == "network":  # the router itself
        gateway = next((d for d in result.devices if d.is_gateway), None)
        return gateway.vendor if gateway else None
    return None


def task_id(finding: Finding) -> str:
    return f"{finding.rule_id}|{finding.subject or finding.id}"


def build_tasks(
    result: DiscoveryResult,
    answers: dict[str, Answer],
    states: dict[str, TaskState],
    templates: Templates | None = None,
    *,
    confirmed: dict[str, bool] | None = None,
) -> list[Task]:
    """One task per High or Medium finding that has a template, unless the user said the
    device is theirs. Saved statuses, notes, evidence and rechecks are applied by task id. A
    device the user says is the host's, and that the host has confirmed, has the "Host
    confirmed" evidence; its status stays what the user set."""
    templates = templates or load_templates()
    confirmed = confirmed or {}
    tasks: list[Task] = []
    seen: set[str] = set()
    for f in sorted(result.findings, key=lambda f: SEVERITY_ORDER[f.severity]):
        if f.severity not in TASK_SEVERITIES or f.rule_id not in templates.templates:
            continue
        if f.subject and answers.get(f.subject) == "mine":
            continue  # yours: nothing to ask anyone
        tid = task_id(f)
        if tid in seen:
            continue
        seen.add(tid)
        t = templates.templates[f.rule_id]
        state = states.get(tid, TaskState())
        status = state.status
        host_confirmed = state.host_confirmed or bool(
            f.subject and answers.get(f.subject) == "landlord" and confirmed.get(f.subject)
        )
        offer = recheck_offer(f.rule_id, status, host_confirmed)
        latest = state.rechecks[-1] if state.rechecks else None
        tasks.append(
            Task(
                id=tid,
                finding_id=f.id,
                rule_id=f.rule_id,
                subject=f.subject or f.id,
                severity=f.severity,
                finding_title=f.title,
                title=t.title,
                ask=validator.hedge_camera(t.ask),  # the template guard (B1)
                who=t.who,
                steps=templates.steps_for(f.rule_id),
                support=support_for(_maker_for(f, result), templates),
                status=status,
                notes=state.notes,
                changed_at=state.changed_at,
                check_at=state.check_at,
                host_confirmed=host_confirmed,
                host_confirmed_at=state.host_confirmed_at,
                recheck_offer=offer,
                rechecks=list(state.rechecks),
                recheck=latest,
                observed=bool(latest and latest.observed),
                observed_at=latest.checked_at if latest and latest.observed else None,
            )
        )
    return tasks


def recheck_offer(rule_id: str, status: str, host_confirmed: bool = False) -> RecheckOffer:
    """A recheck once the task is Resolved or Host confirmed, but only where RoomCheck can
    observe the fix; the plain "can't check this" line where it never can."""
    from app.handover.recheck import UNOBSERVABLE, kind_for

    if rule_id in UNOBSERVABLE:
        return "unobservable"
    if kind_for(rule_id) is None:
        return "none"
    return "available" if status == "resolved" or host_confirmed else "needs_status"


def bundle_message(tasks: list[Task], ai_message: LandlordMessage | None) -> LandlordMessage | None:
    """One polite message with a question for every open task meant for the landlord or host:
    never a resolved or host-confirmed task, and never a device the user marked as theirs
    (it has no task). The AI's draft is used only if it was written for exactly these
    findings and mentions nothing else; otherwise the standard numbered message. RoomCheck
    never sends it."""
    to_ask = [t for t in tasks if t.open and t.who != "you"]
    if not to_ask:
        return None
    covers = [t.finding_id for t in to_ask]
    if (
        ai_message is not None
        and ai_message.source == "ai"
        and all(t.status == "todo" for t in to_ask)  # nothing asked yet: the draft still fits
        and set(ai_message.covers) == set(covers)
        and validator.check_landlord_message(ai_message.text, [t.rule_id for t in to_ask]) is None
    ):
        return ai_message
    lines = [f"{n}. {validator.hedge_camera(t.ask)}" for n, t in enumerate(to_ask, start=1)]
    text = (
        "Hello,\n\nI checked the devices and Wi-Fi where I'm staying and have "
        f"{'a question' if len(to_ask) == 1 else 'a few questions'}:\n\n"
        + "\n".join(lines)
        + "\n\nThank you for your help."
    )
    return LandlordMessage(
        text=text, source="standard", label=STANDARD_MESSAGE_LABEL, covers=covers
    )


def adjusted_steps(
    finding: Finding,
    answer: Answer | None,
    templates: Templates | None = None,
    *,
    location: Location | None = None,
    stay: StayType | None = None,
) -> AdjustedSteps | None:
    """What an answer changes: only the next step, the guidance and which message is offered.
    "Mine" replaces the next step and drops the "leave if unsafe / report it" guidance. For a
    camera, "Where is it?" picks the next step for the stay type (rules.yaml). The finding's
    title, severity, confidence and evidence never change."""
    if answer == "mine":
        templates = templates or load_templates()
        return AdjustedSteps(next_step=templates.recognition["mine_next_step"], guidance=[])
    if location is not None and finding.asks_location:
        found = location_step(finding.rule_id, location, stay)
        if found is not None:
            return AdjustedSteps(next_step=found.step, guidance=finding.guidance, draft=found.draft)
    return None
