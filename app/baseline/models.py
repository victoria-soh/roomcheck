"""What the move-in baseline stores (exactly what docs/original-plan.md lists), and the
comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.discovery.models import CoverageItem
from app.fingerprint.models import Band
from app.rules.models import Severity


class BaselineFinding(BaseModel):
    rule_id: str
    severity: Severity
    title: str


class BaselineDevice(BaseModel):
    """One device on the network at move-in. No address, name or maker: only its keys."""

    key: str  # "mac:..." or "soft:..."
    kind: Literal["mac", "soft"]
    soft: str | None = None
    type: str  # the fingerprint type, e.g. "camera"
    type_label: str  # e.g. "Camera"
    ports: list[int] = Field(default_factory=list)
    ports_checked: bool = True  # False: this check didn't look at its services (no permission)
    findings: list[BaselineFinding] = Field(default_factory=list)
    # How sure the type guess was, and the names of the clues behind it (e.g. "onvif"), so a
    # later check can tell "identification varied" from "the device changed". None: saved
    # before these were kept.
    band: Band | None = None
    signals: list[str] = Field(default_factory=list)


class BaselineNearby(BaseModel):
    """One flagged nearby item at move-in, keyed by a salted hash of its BSSID or address."""

    key: str
    kind: Literal["wifi", "bluetooth"]
    findings: list[BaselineFinding] = Field(default_factory=list)


class Baseline(BaseModel):
    saved_at: datetime
    devices: list[BaselineDevice] = Field(default_factory=list)
    unkeyed_devices: int = 0  # private address and no name: can't be matched later
    nearby: list[BaselineNearby] = Field(default_factory=list)
    network_findings: list[BaselineFinding] = Field(default_factory=list)
    # How the move-in check ran, to say when two checks can't be compared like for like.
    mode: Literal["full", "passive"] | None = None  # None: saved before this was kept
    coverage: list[CoverageItem] = Field(default_factory=list)


@dataclass
class BaselineFacts:
    """What the rules engine needs from the baseline: the keys it knew, and when."""

    saved_at: datetime
    salt: bytes
    keys: set[str] = field(default_factory=set)
    soft_keys: set[str] = field(default_factory=set)

    @classmethod
    def of(cls, baseline: Baseline, salt: bytes) -> BaselineFacts:
        return cls(
            saved_at=baseline.saved_at,
            salt=salt,
            keys={d.key for d in baseline.devices},
            soft_keys={d.soft for d in baseline.devices if d.soft},
        )


# unchanged: only for "possibly the same device" pairs, listed so the user can answer them.
CompareStatus = Literal["new", "gone", "changed", "unchanged"]
# The user's answer to "possibly the same device": saved like the recognition answers.
MatchDecision = Literal["same", "different"]


class CompareItem(BaseModel):
    kind: Literal["device", "nearby", "network"]
    status: CompareStatus
    # exact: same MAC address or nearby address. possible: only the soft key matched, so this
    # is "possibly the same device", never a confident match. None for new and gone items.
    match: Literal["exact", "possible"] | None = None
    label: str  # plain words, e.g. "Camera" or "Nearby Wi-Fi"
    maker: str | None = None  # from the current scan only; the baseline doesn't store makers
    changes: list[str] = Field(default_factory=list)  # plain words
    findings: list[BaselineFinding] = Field(default_factory=list)
    device_ref: str | None = None  # the current scan's device id, if it's in the current scan
    # What recognition answers and names attach to, so Compare shows the user's own name.
    subject: str | None = None
    # A "possibly the same device" pair: its id, and the user's answer if there is one. On
    # "different", the pair shows as one New and one Not seen item, both with this id.
    match_id: str | None = None
    decision: MatchDecision | None = None
    # The type guess's band: the higher of the two checks' when only the confidence moved.
    band: Band | None = None
    # True when the type stayed the same, the clues overlapped, and only the confidence
    # (Likely / Possible) moved: shown as "identification varied between checks", not a change.
    identification_varied: bool = False


class Comparison(BaseModel):
    baseline_saved_at: datetime
    scan_at: datetime
    baseline_mode: Literal["full", "passive"] | None = None  # None: saved before this was kept
    scan_mode: Literal["full", "passive"] | None = None
    new: list[CompareItem] = Field(default_factory=list)
    gone: list[CompareItem] = Field(default_factory=list)
    changed: list[CompareItem] = Field(default_factory=list)
    unchanged: int = 0
    unchanged_possible: int = 0  # of those, matched by soft key only and not answered yet
    # Unchanged "possibly the same device" pairs, so each can be confirmed or rejected.
    possible: list[CompareItem] = Field(default_factory=list)
    # Unchanged devices whose identification varied (Likely in one check, Possible in the
    # other, with overlapping clues): listed with the higher band, never as Changed.
    varied: list[CompareItem] = Field(default_factory=list)
    not_compared: int = 0  # devices with a private address and nothing else to match on
    # One plain note at the top when one check had permission and the other only listened.
    ran_differently: bool = False
    # Other notes for the top: parts of this check that were limited or didn't run.
    warnings: list[str] = Field(default_factory=list)
    # Findings from the move-in scan this check couldn't look for: never shown as "not seen".
    not_checked: list[str] = Field(default_factory=list)
