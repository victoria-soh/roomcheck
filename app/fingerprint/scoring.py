"""Noisy-OR scoring of device types over weighted evidence from rules/weights.yaml.

P(type) = 1 - prod(1 - w_i) over the signals that matched. Every score comes with the list of
evidence behind it. The output never says a device is safe; low scores are "Unclear".
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.fingerprint.facts import Facts
from app.fingerprint.models import Band, Evidence, Fingerprint, TypeScore

WEIGHTS_FILE = Path(__file__).resolve().parents[1] / "rules" / "weights.yaml"
UNKNOWN_TYPE = "unknown"
UNKNOWN_LABEL = "Unidentified device"


class When(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_regex: str | None = None
    server_regex: str | None = None
    vendor_regex: str | None = None
    ports_any: list[int] | None = None
    rtsp: bool | None = None
    onvif_type: str | None = None
    mdns_type_any: list[str] | None = None
    ssdp_regex: str | None = None
    hap_category_any: list[int] | None = None
    dhcp_vendor_regex: str | None = None
    gateway: bool | None = None
    random_mac: bool | None = None
    tuya: bool | None = None

    @field_validator(
        "name_regex", "server_regex", "vendor_regex", "ssdp_regex", "dhcp_vendor_regex"
    )
    @classmethod
    def _compiles(cls, v: str | None) -> str | None:
        if v is not None:
            re.compile(v)
        return v


class Signal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    weight: float = Field(gt=0, lt=1)
    when: When
    evidence: str


class TypeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    signals: list[Signal]


class Bands(BaseModel):
    likely: float = Field(gt=0, le=1)
    possible: float = Field(gt=0, le=1)


class Weights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bands: Bands
    other_type_min: float = Field(ge=0, le=1)
    types: dict[str, TypeSpec]


@lru_cache(maxsize=4)
def load_weights(path: Path = WEIGHTS_FILE) -> Weights:
    with path.open(encoding="utf-8") as f:
        return Weights.model_validate(yaml.safe_load(f))


def noisy_or(weights: list[float]) -> float:
    p = 1.0
    for w in weights:
        p *= 1.0 - w
    return 1.0 - p


def band_for(score: float, bands: Bands) -> Band:
    if score >= bands.likely:
        return "Likely"
    if score >= bands.possible:
        return "Possible"
    return "Unclear"


def _search(pattern: str, values: list[str]) -> str | None:
    rx = re.compile(pattern, re.IGNORECASE)
    return next((v for v in values if rx.search(v)), None)


def _conditions(when: When, f: Facts) -> list[str | None]:
    """One entry per condition set in `when`: a detail string ("" if none), or None if unmet."""
    out: list[str | None] = []
    if when.name_regex is not None:
        out.append(_search(when.name_regex, f.names))
    if when.server_regex is not None:
        out.append(_search(when.server_regex, f.servers))
    if when.vendor_regex is not None:
        rx = re.compile(when.vendor_regex, re.IGNORECASE)
        out.append(next((f"{where}: {who}" for where, who in f.makers if rx.search(who)), None))
    if when.ports_any is not None:
        ports = sorted(f.open_ports.intersection(when.ports_any))
        out.append(f"port {', '.join(map(str, ports))}" if ports else None)
    if when.rtsp is not None:
        found = f"port {f.rtsp_ports[0]}" if f.rtsp_ports else ""
        out.append(found if bool(f.rtsp_ports) == when.rtsp else None)
    if when.onvif_type is not None:
        out.append("" if when.onvif_type in f.onvif_types else None)
    if when.mdns_type_any is not None:
        out.append(next((t for t in when.mdns_type_any if t in f.mdns_types), None))
    if when.ssdp_regex is not None:
        out.append(_search(when.ssdp_regex, f.ssdp_types))
    if when.hap_category_any is not None:
        cats = f.hap_categories.intersection(when.hap_category_any)
        out.append(f"category {min(cats)}" if cats else None)
    if when.dhcp_vendor_regex is not None:
        out.append(_search(when.dhcp_vendor_regex, f.dhcp_vendors))
    for expected, actual in (
        (when.gateway, f.gateway),
        (when.random_mac, f.random_mac),
        (when.tuya, f.tuya),
    ):
        if expected is not None:
            out.append("" if expected == actual else None)
    return out


def match(when: When, f: Facts) -> str | None:
    """Short detail of what matched ("" if nothing to add), or None unless every condition holds."""
    results = _conditions(when, f)
    if not results or any(r is None for r in results):
        return None
    return "; ".join(r for r in results if r)


def score_types(f: Facts, weights: Weights) -> list[TypeScore]:
    """Every type with at least one matching signal, highest score first."""
    scores = []
    for type_id, spec in weights.types.items():
        evidence = []
        for s in spec.signals:
            detail = match(s.when, f)
            if detail is not None:
                text = f"{s.evidence} ({detail})" if detail else s.evidence
                evidence.append(Evidence(signal=s.id, weight=s.weight, text=text))
        if evidence:
            score = round(noisy_or([e.weight for e in evidence]), 3)
            scores.append(
                TypeScore(
                    type=type_id,
                    label=spec.label,
                    score=score,
                    band=band_for(score, weights.bands),
                    evidence=sorted(evidence, key=lambda e: -e.weight),
                )
            )
    order = list(weights.types)
    return sorted(scores, key=lambda s: (-s.score, order.index(s.type)))


Identification = Literal["full", "partial", "passive"]


def fingerprint(
    f: Facts, identification: Identification, weights: Weights | None = None
) -> Fingerprint:
    weights = weights or load_weights()
    scores = score_types(f, weights)
    if not scores:
        return Fingerprint(
            type=UNKNOWN_TYPE,
            label=UNKNOWN_LABEL,
            confidence=0.0,
            band="Unclear",
            evidence=[],
            notes=f.notes,
            identification=identification,
        )
    best, *rest = scores
    return Fingerprint(
        type=best.type,
        label=best.label,
        confidence=best.score,
        band=best.band,
        evidence=best.evidence,
        other_types=[s for s in rest if s.score >= weights.other_type_min],
        weak_types=[s for s in rest if s.score < weights.other_type_min],
        notes=f.notes,
        identification=identification,
    )
