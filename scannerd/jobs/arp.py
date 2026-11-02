"""Step 1: ARP sweep of the laptop's own subnet, two passes about 20 s apart.

The target is always the subnet scannerd works out for itself; callers can't choose it.
"""

from __future__ import annotations

import ipaddress
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from scapy.layers.l2 import ARP, Ether
from scapy.packet import Packet

from app.discovery.models import Observation, Source
from app.discovery.netinfo import NoNetworkError, default_route, get_network_info
from scannerd import session
from scannerd.protocol import JobError, require_pcap


class ArpSweepParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passes: int = Field(default=2, ge=1, le=2)
    gap_seconds: float = Field(default=20.0, ge=0, le=30)


def observation_from_arp(pkt: Packet, source: Source, now: datetime) -> Observation | None:
    """The sender of any ARP packet (request or reply) is a live host."""
    arp = pkt.getlayer(ARP)
    if arp is None or not arp.psrc or arp.psrc == "0.0.0.0":  # 0.0.0.0 = address probe
        return None
    return Observation(source=source, seen_at=now, ip=arp.psrc, mac=arp.hwsrc)


def arp_sweep(params: ArpSweepParams) -> list[dict[str, Any]]:
    from scapy.sendrecv import srp

    require_pcap()
    try:
        iface, _, _ = default_route()
        net = get_network_info()
    except NoNetworkError as e:
        raise JobError("no_network") from e
    if not net.sweep_allowed:
        raise JobError("subnet_too_large")

    subnet = ipaddress.IPv4Network(net.cidr)
    found: list[Observation] = []
    for i in range(params.passes):
        if i:
            time.sleep(params.gap_seconds)
        answered, _ = srp(
            Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=net.cidr),
            timeout=2,
            retry=1,
            iface=iface,
            verbose=False,
        )
        now = datetime.now(UTC)
        for _sent, received in answered:
            obs = observation_from_arp(received, "arp_sweep", now)
            if obs and obs.ip and ipaddress.IPv4Address(obs.ip) in subnet:
                found.append(obs)
    session.record_swept([o.ip for o in found if o.ip])
    return [o.model_dump(mode="json") for o in found]
