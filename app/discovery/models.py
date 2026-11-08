"""Layer 1 data model: raw observations from each collector, merged into devices."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.checks.models import NetworkFacts
from app.explain.models import Explanations
from app.fingerprint.models import Fingerprint, Identity
from app.rules.models import Finding, RoomSummary, StayType
from app.wireless.models import HeardCounts, NearbyItem

Source = Literal["arp_sweep", "arp_passive", "dhcp", "mdns", "ssdp", "onvif", "tuya"]


class Service(BaseModel):
    """Something a device advertised: an mDNS type, an SSDP target, an ONVIF type."""

    kind: Literal["mdns", "ssdp", "onvif", "tuya", "dhcp"]
    name: str
    detail: dict[str, str] = Field(default_factory=dict)


class Observation(BaseModel):
    """One sighting of a host by one collector. Merged into Devices by MAC."""

    source: Source
    seen_at: datetime
    ip: str | None = None
    mac: str | None = None
    hostname: str | None = None
    services: list[Service] = Field(default_factory=list)


class Device(BaseModel):
    id: str
    ip: str | None
    mac: str | None
    mac_is_random: bool
    is_gateway: bool = False
    vendor: str | None = None  # Layer 2; None for private MACs or unregistered prefixes
    hostnames: list[str] = Field(default_factory=list)
    services: list[Service] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    first_seen: datetime
    last_seen: datetime
    identity: Identity | None = None  # Layer 2, consented checks only
    fingerprint: Fingerprint | None = None  # Layer 2


class NetworkInfo(BaseModel):
    interface: str
    own_ip: str
    own_mac: str | None
    gateway_ip: str
    netmask: str
    cidr: str
    prefixlen: int
    sweep_allowed: bool


CheckStatusValue = Literal["ran", "skipped", "failed"]


class CheckStatus(BaseModel):
    """Whether one discovery step ran. `reason` is plain language for the user."""

    name: str
    label: str
    status: CheckStatusValue
    reason: str | None = None
    found: int = 0
    # A few words on why it didn't run, for the one-line rows of Coverage and limits (set by
    # app/coverage.py). None when it ran.
    short_reason: str | None = None


CoverageState = Literal["completed", "limited", "not_run"]


class CoverageItem(BaseModel):
    """One row of the scan coverage table (app/coverage.py): an area of the check and how much
    of it ran, from the real check statuses."""

    area: str
    label: str
    state: CoverageState
    reason: str | None = None  # plain words, without the "Limited:" / "Not run:" prefix
    # The message code behind the reason (e.g. "location_off"), so the page can offer the one
    # recovery step that fixes it. None when there's no code.
    reason_code: str | None = None


class DiscoveryResult(BaseModel):
    started_at: datetime
    finished_at: datetime
    mode: Literal["full", "passive"]
    network: NetworkInfo | None
    devices: list[Device]
    checks: list[CheckStatus]
    client_isolation: bool = False
    messages: list[str] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    network_facts: NetworkFacts | None = None  # Layer 3
    findings: list[Finding] = Field(default_factory=list)  # rules engine
    # Where the user is staying (Start). None: not asked, e.g. the command line.
    stay_type: StayType | None = None
    summary: RoomSummary | None = None  # rules engine
    # Layer 4: flagged nearby items only (salted refs, no addresses), and counts of the rest
    nearby_items: list[NearbyItem] = Field(default_factory=list)
    nearby_heard: HeardCounts | None = None
    room_network: str | None = None  # the Wi-Fi name nearby networks were compared with
    explanations: Explanations | None = None  # Layer 5: AI or standard, each labelled
    coverage: list[CoverageItem] = Field(default_factory=list)  # what each part managed to do
