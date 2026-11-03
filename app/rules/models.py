"""Rules-engine output: findings and the room summary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.fingerprint.models import Band

Severity = Literal["High", "Medium", "Low", "Info"]
SummaryStatus = Literal["Needs attention", "Check these items", "Nothing found by these checks"]


class Finding(BaseModel):
    id: str  # "<rule_id>:<device id>" or "<rule_id>:network"; stable for AI explanations later
    rule_id: str
    severity: Severity
    confidence_band: Band
    device_ref: str | None  # Device.id, or None for a network-wide finding
    title: str
    evidence: list[str]
    next_step: str
    guidance: list[str] = Field(default_factory=list)
    nearby_ref: str | None = None  # a flagged nearby item's ref, for the locator


@dataclass
class Match:
    """What a rule predicate found: confidence, evidence, and which variant of the rule."""

    band: Band
    evidence: list[str]
    variant: str | None = None
    device_ref: str | None = None  # network rules may point at the device involved
    nearby_ref: str | None = None  # nearby rules point at the flagged access point or device


class RoomSummary(BaseModel):
    status: SummaryStatus
    high: int
    medium: int
    other: int
    not_checked: list[str]  # checks that didn't run this time, with the reason
    cant_see: list[str]  # what these checks can never see
