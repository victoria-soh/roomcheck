"""Rules-engine output: findings and the room summary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.fingerprint.models import Band

Severity = Literal["High", "Medium", "Low", "Info"]
SummaryStatus = Literal["Needs attention", "Check these items", "Not detected by these checks"]
# The renter's questions that Results and the report are organised by (rules.yaml, questions).
Question = Literal["watching", "control", "wifi"]
QUESTIONS: tuple[Question, ...] = ("watching", "control", "wifi")
# Where the user is staying (Start): some next steps depend on it (rules.yaml,
# next_step_by_stay). "other" uses each rule's default next step.
StayType = Literal["short_stay", "rental", "hostel", "other"]
# A camera's answer to "Where is it?" (Results): inside the room or unit, outside or in a
# shared area, or the user couldn't find it.
Location = Literal["inside", "outside", "unknown"]
# Which message a card offers for its next step: to the host, or a report to the platform.
Draft = Literal["host", "platform"]


class Finding(BaseModel):
    id: str  # "<rule_id>:<device id>" or "<rule_id>:network"; stable for AI explanations later
    rule_id: str
    scope: Literal["device", "network", "nearby"] = "device"  # the rule's scope
    # Where the finding is shown: Results for your devices and your own network (including its
    # router or access point, even when judged from the Wi-Fi survey); Nearby for other signals.
    shown_on: Literal["results", "nearby"] = "results"
    # Which renter's question it answers (rules.yaml): the section it's shown in.
    question: Question = "wifi"
    severity: Severity
    confidence_band: Band
    device_ref: str | None  # Device.id, or None for a network-wide finding
    title: str
    # One fixed sentence from rules.yaml saying what was seen (the summary and short cards).
    observed: str = ""
    # The specific clues behind it, one fixed plain sentence each (weights.yaml `clue`, or the
    # predicate's own), from data already collected. Empty: `observed` says what was seen.
    clues: list[str] = Field(default_factory=list)
    # The plainest of those clues (weights.yaml plain_rank), for the summary sentence and the
    # PDF banner. "": the first clue, or the observed sentence.
    lead_clue: str = ""
    # One fixed sentence from rules.yaml saying what it could mean: the risk ("What it could mean").
    could_mean: str = ""
    evidence: list[str]
    next_step: str
    guidance: list[str] = Field(default_factory=list)
    # Camera findings ask "Where is it?"; the answer picks the next step (rules.yaml).
    asks_location: bool = False
    draft: Draft = "host"  # the message the card offers for this next step
    nearby_ref: str | None = None  # a flagged nearby item's ref, for the locator
    # Standard (template) text from rules.yaml, shown when there's no valid AI explanation.
    standard_explanation: str = ""
    standard_why: str = ""
    landlord_question: str | None = None  # High and Medium rules: a question, never a claim
    # Layer 6: what recognition answers and handover tasks attach to, stable across scans:
    # "device:<key>", "wifi:<key>" / "bluetooth:<key>" for nearby items, or "network:<rule>".
    subject: str | None = None


@dataclass
class Match:
    """What a rule predicate found: confidence, evidence, and which variant of the rule."""

    band: Band
    evidence: list[str]
    variant: str | None = None
    device_ref: str | None = None  # network rules may point at the device involved
    nearby_ref: str | None = None  # nearby rules point at the flagged access point or device
    clues: list[str] = field(default_factory=list)  # plain sentences for "What we observed"
    lead_clue: str = ""  # the plainest clue, for the summary sentence


class RoomSummary(BaseModel):
    status: SummaryStatus
    high: int
    medium: int
    other: int
    not_checked: list[str]  # checks that didn't run this time, with the reason
    cant_see: list[str]  # what these checks can never see


class QuestionCard(BaseModel):
    """One card under a question: a device, a nearby signal, or one network finding, with its
    findings for this question (most serious first) and the Info items shown inside it."""

    key: str  # unique on the page, also the card's element id
    kind: Literal["device", "nearby", "network"]
    device_ref: str | None = None
    nearby_ref: str | None = None
    finding_ids: list[str]  # High, Medium or Low: what the card is about
    also: list[str] = Field(default_factory=list)  # Info findings: "Also found", not counted


QuestionState = Literal["look", "info", "not_detected", "not_checked"]


class QuestionStatus(BaseModel):
    """One of the renter's questions, as Results, the report summary and the PDF show it.

    things: cards to look at (the only number the headline adds up). state picks the status
    line: look ("1 thing to look at"), info (only Info items), not_detected ("Not detected by
    the checks that ran") or not_checked (none of its checks ran). not_checked_reason is set
    whenever any of its checks didn't run."""

    id: Question
    things: int
    state: QuestionState
    not_checked_reason: str | None = None
    cards: list[QuestionCard] = Field(default_factory=list)
    also: list[str] = Field(default_factory=list)  # Info findings with no card to sit in
    # "Is anything watching?" only: devices with a camera clue too weak to flag (above zero,
    # below R-CAM's threshold). Shown as one line, never counted.
    weak_camera: list[str] = Field(default_factory=list)
