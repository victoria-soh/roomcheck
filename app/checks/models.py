"""Layer 3 network facts. Collected with I/O in app/checks, judged by the pure rules engine."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class WifiStatus(BaseModel):
    """The current Wi-Fi connection, from `netsh wlan show interfaces`."""

    interface: str
    ssid: str | None = None
    bssid: str | None = None  # the access point you're connected to; used by Layer 4 only
    authentication: str
    cipher: str


class DnsResult(BaseModel):
    """System-resolver checks only. No DoH or other outside resolver is used."""

    random_name: str
    nxdomain: bool | None  # None: no clear answer (timeout or server failure)
    random_name_answers: list[str] = Field(default_factory=list)
    checked_domains: list[str] = Field(default_factory=list)
    non_public_answers: dict[str, list[str]] = Field(default_factory=dict)


class DhcpOffer(BaseModel):
    server_id: str
    server_mac: str | None = None
    offered_ip: str | None = None


class ArpClaim(BaseModel):
    """One MAC seen claiming an IP in ARP traffic during the scan."""

    ip: str
    mac: str
    vendor: str | None = None
    first_seen: datetime
    last_seen: datetime


class CveMatch(BaseModel):
    """Known issues NVD lists for a product matching a device's reported model."""

    model: str  # what the device reported, e.g. "Hikvision DS-2CD2143G2-I"
    cpe: str  # the NVD product it matched, e.g. "cpe:2.3:o:hikvision:ds-2cd2143g2-i_firmware"
    total: int
    cve_ids: list[str] = Field(default_factory=list)  # most recent first, capped
    exploited: list[str] = Field(default_factory=list)  # in CISA's actively-exploited list


class NetworkFacts(BaseModel):
    wifi: WifiStatus | None = None
    dns: DnsResult | None = None
    dhcp_offers: list[DhcpOffer] | None = None  # None: not checked
    arp_claims: list[ArpClaim] = Field(default_factory=list)  # for the gateway IP only
    cves: dict[str, list[CveMatch]] = Field(default_factory=dict)  # by device id
