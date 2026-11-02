"""Layer 2 data model: what identity checks found, and the scored type guess."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Band = Literal["Likely", "Possible", "Unclear"]


class HttpIdentity(BaseModel):
    port: int
    scheme: Literal["http", "https"]
    status: int
    server: str | None = None
    title: str | None = None


class RtspIdentity(BaseModel):
    port: int
    status: int
    server: str | None = None


class UpnpIdentity(BaseModel):
    manufacturer: str | None = None
    model_name: str | None = None
    device_type: str | None = None


class Identity(BaseModel):
    """Results of the consented checks. `open_ports` is None when ports weren't checked."""

    open_ports: list[int] | None = None
    ports_complete: bool = True
    http: list[HttpIdentity] = Field(default_factory=list)
    rtsp: list[RtspIdentity] = Field(default_factory=list)
    upnp: UpnpIdentity | None = None
    problems: list[str] = Field(default_factory=list)  # e.g. "HTTP on port 80 didn't answer"
    notes: list[str] = Field(default_factory=list)  # observations shown as evidence, not scored


class Evidence(BaseModel):
    signal: str
    weight: float
    text: str


class TypeScore(BaseModel):
    type: str
    label: str
    score: float
    band: Band
    evidence: list[Evidence]


class Fingerprint(BaseModel):
    """The best type guess first, then every other type with any evidence."""

    type: str
    label: str
    confidence: float
    band: Band
    evidence: list[Evidence]
    # Other types scoring at least `other_type_min` (weights.yaml); shown alongside the guess.
    other_types: list[TypeScore] = Field(default_factory=list)
    # Weaker hints, kept for the "Why we think this" detail but not shown as possible types.
    weak_types: list[TypeScore] = Field(default_factory=list)
    # Unscored observations, e.g. outdated encryption on its web page.
    notes: list[str] = Field(default_factory=list)
    identification: Literal["full", "partial", "passive"]
