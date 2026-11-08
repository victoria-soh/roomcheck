"""Handover tasks, their saved states, the answers to "Do you recognise this device?", whether
the host confirmed a device is theirs, and the short names the user gives devices."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.explain.models import LandlordMessage
from app.rules.models import Draft, Location, Severity

# mine: the user's own. landlord: the landlord's or host's ("Host's"); whether the host has
# confirmed it is asked separately (HandoverState.confirmed). unknown: the same as no answer.
# An answer changes the guidance and next step, never the detection: the finding stays, with
# its evidence and severity.
Answer = Literal["mine", "landlord", "unknown"]
# Workflow status only. What the host said and what RoomCheck saw are evidence, kept apart.
TaskStatus = Literal["todo", "asked", "resolved"]
Who = Literal["landlord_or_host", "booking_platform", "you"]
MAX_NOTES = 2000
MAX_NAME = 40  # a short device name, e.g. "Hallway camera"
MAX_NOTE = 200  # a short note from "Help identify this", e.g. "White box above the TV"
_NOT_PLAIN = re.compile(r"[<>\x00-\x1f\x7f]")


def clean_name(text: str) -> str:
    """A device name as plain text: trimmed, single spaces, at most 40 characters, and no
    markup or control characters. Raises ValueError otherwise. "" means no name."""
    name = " ".join(text.split())
    if len(name) > MAX_NAME or _NOT_PLAIN.search(text):
        raise ValueError("not a plain short name")
    return name


def clean_note(text: str) -> str:
    """A short note as plain text: trimmed, at most 200 characters, no markup or control
    characters (line breaks are fine). Raises ValueError otherwise. "" means no note."""
    note = "\n".join(" ".join(line.split()) for line in text.strip().splitlines()).strip()
    if len(note) > MAX_NOTE or _NOT_PLAIN.search(text.replace("\n", "").replace("\r", "")):
        raise ValueError("not a plain short note")
    return note


# The guided physical check: places to look with your own eyes and a phone torch. The words
# for each are in web/src/strings/en.json (physical.items). Nothing here is ever "clear".
PHYSICAL_ITEMS = (
    "smoke_detector",
    "chargers",
    "clocks",
    "tv_box",
    "purifier_speaker",
    "facing_bed",
    "mirrors",
    "lenses",
)
PhysicalItemId = Literal[
    "smoke_detector",
    "chargers",
    "clocks",
    "tv_box",
    "purifier_speaker",
    "facing_bed",
    "mirrors",
    "lenses",
]


class PhysicalItem(BaseModel):
    looked: bool = False  # the user ticked it: they looked there
    note: str = ""  # optional, plain text (clean_note)


class PhysicalCheck(BaseModel):
    """What the user looked at, and their notes. Saved encrypted with the other answers."""

    items: dict[PhysicalItemId, PhysicalItem] = Field(default_factory=dict)
    done_at: datetime | None = None  # when they pressed Done; None while it's in progress

    @property
    def looked(self) -> int:
        return sum(1 for i in self.items.values() if i.looked)


RecheckKind = Literal["devices", "nearby_wifi"]
# fixed / gone: RoomCheck observed the fix ("Observed by RoomCheck"). still_there: it didn't.
# couldnt_check / needs_permission: no answer this time, with the reason.
RecheckOutcome = Literal["fixed", "gone", "still_there", "couldnt_check", "needs_permission"]
# What a task offers: a recheck (once Done or Host confirmed), "RoomCheck can't check this",
# or nothing.
RecheckOffer = Literal["available", "needs_status", "unobservable", "none"]


class Recheck(BaseModel):
    outcome: RecheckOutcome
    text: str  # fixed words from app/handover/recheck.py
    checked_at: datetime

    @property
    def observed(self) -> bool:
        return self.outcome in ("fixed", "gone")


MAX_RECHECKS = 20


class TaskState(BaseModel):
    """What the user changed about a task, its evidence and its rechecks. Saved, encrypted, in
    the local store whether or not a move-in scan exists."""

    status: TaskStatus = "todo"
    notes: str = Field(default="", max_length=MAX_NOTES)
    changed_at: datetime | None = None
    check_at: datetime | None = None  # when the check this task came from started
    # Evidence: the user records that the host confirmed it ("Host confirmed").
    host_confirmed: bool = False
    host_confirmed_at: datetime | None = None
    # Evidence: every recheck, oldest first. A recheck never replaces the original finding.
    rechecks: list[Recheck] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate(cls, data: Any) -> Any:
        """Saved values from before status and evidence were split: Done is Resolved, and the
        old "Host confirmed" status becomes Asked plus the Host confirmed evidence."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if data.get("status") == "done":
            data["status"] = "resolved"
        elif data.get("status") == "confirmed":
            data["status"] = "asked"
            data["host_confirmed"] = True
            data.setdefault("host_confirmed_at", data.get("changed_at"))
        old = data.pop("recheck", None)
        if old and not data.get("rechecks"):
            data["rechecks"] = [old]
        return data


class Suggestion(BaseModel):
    """Something the finding doesn't require, offered apart from the steps, with its reason."""

    text: str
    reason: str


class SupportLink(BaseModel):
    name: str
    url: str  # the maker's own support page; never steps written by RoomCheck


class Task(BaseModel):
    id: str  # "<rule id>|<subject>": the same task in every later scan of the same device
    finding_id: str
    rule_id: str
    subject: str
    severity: Severity
    finding_title: str
    title: str
    ask: str
    who: Who
    steps: list[str]
    optional: list[Suggestion] = Field(default_factory=list)  # never part of the message
    support: SupportLink | None = None
    status: TaskStatus = "todo"
    notes: str = ""
    changed_at: datetime | None = None
    check_at: datetime | None = None  # the check this task came from
    # Evidence, shown alongside the status.
    host_confirmed: bool = False  # "Host confirmed": recorded by the user
    host_confirmed_at: datetime | None = None
    recheck_offer: RecheckOffer = "none"
    rechecks: list[Recheck] = Field(default_factory=list)  # every recheck, oldest first
    recheck: Recheck | None = None  # the latest one
    observed: bool = False  # "Observed by RoomCheck": the latest recheck saw the fix
    observed_at: datetime | None = None

    @property
    def open(self) -> bool:
        """Still to ask: not resolved, and the host hasn't answered yet."""
        return self.status != "resolved" and not self.host_confirmed


class AdjustedSteps(BaseModel):
    next_step: str
    guidance: list[str]
    draft: Draft = "host"  # the message the card offers: to the host, or to the platform


class HandoverState(BaseModel):
    answers: dict[str, Answer] = Field(default_factory=dict)  # by subject
    # "Host's" only: has the host confirmed it? True: yes (its tasks show "Host confirmed").
    confirmed: dict[str, bool] = Field(default_factory=dict)  # by subject
    locations: dict[str, Location] = Field(default_factory=dict)  # "Where is it?", by subject
    names: dict[str, str] = Field(default_factory=dict)  # the user's own short names, by subject
    notes: dict[str, str] = Field(default_factory=dict)  # their short notes, by subject
    adjusted: dict[str, AdjustedSteps] = Field(default_factory=dict)  # by finding id
    tasks: list[Task] = Field(default_factory=list)
    message: LandlordMessage | None = None  # bundles the open tasks; None when none are open
    saved: bool = False  # True: a move-in scan is saved
    # Whether the handover data (tasks, statuses, notes, answers) is saved on this laptop, and
    # if not, why. Saved in the encrypted local store, with or without a move-in scan.
    storage: Literal["saved", "not_saved"] = "saved"
    physical: PhysicalCheck = Field(default_factory=PhysicalCheck)  # the physical check
    storage_reason: str | None = None
