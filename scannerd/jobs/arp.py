"""Step 1: ARP sweep of the laptop's own subnet, two passes about 20 s apart.

The target is always the subnet scannerd works out for itself; callers can't choose it.

The sweep keeps its own deadline (budget_seconds) and always ends by it, returning what it has
heard so far. Replies are collected by a listener that runs for the whole sweep, while the
requests go out in small batches with the deadline checked between them, so a slow send (a
/22 is 1,024 addresses, sent from Python) can't run on after the app has stopped waiting.
"""

from __future__ import annotations

import ipaddress
import logging
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field
from scapy.layers.l2 import ARP, Ether
from scapy.packet import Packet

from app.discovery.models import Observation, Source
from app.discovery.netinfo import NoNetworkError, default_route, get_network_info
from scannerd import session
from scannerd.protocol import JobError, require_pcap

log = logging.getLogger("scannerd.arp")

BATCH = 128  # requests per send; the deadline is checked between batches
REPLY_WAIT_SECONDS = 2.0  # how long to keep listening after a pass's last request
ARP_REPLY_FILTER = "arp and arp[6:2] = 2"  # replies only (opcode 2)


class ArpSweepParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passes: int = Field(default=2, ge=1, le=2)
    gap_seconds: float = Field(default=20.0, ge=0, le=30)
    # The sweep ends by this, whatever it has heard. The app waits a little longer than this.
    budget_seconds: float = Field(default=45.0, ge=5, le=90)


def observation_from_arp(pkt: Packet, source: Source, now: datetime) -> Observation | None:
    """The sender of any ARP packet (request or reply) is a live host."""
    arp = pkt.getlayer(ARP)
    if arp is None or not arp.psrc or arp.psrc == "0.0.0.0":  # 0.0.0.0 = address probe
        return None
    return Observation(source=source, seen_at=now, ip=arp.psrc, mac=arp.hwsrc)


class Listener(Protocol):
    def stop(self) -> Any: ...


def _listen(iface: Any, on_packet: Callable[[Packet], None]) -> Listener:
    """Start capturing ARP replies on iface in the background."""
    from scapy.sendrecv import AsyncSniffer

    sniffer = AsyncSniffer(iface=iface, filter=ARP_REPLY_FILTER, prn=on_packet, store=False)
    sniffer.start()
    return sniffer


def _send(packets: list[Packet], iface: Any) -> None:
    from scapy.sendrecv import sendp

    sendp(packets, iface=iface, verbose=False)


def _batches(subnet: ipaddress.IPv4Network, own_ip: str) -> Iterator[list[str]]:
    hosts = [str(h) for h in subnet.hosts() if str(h) != own_ip]
    for i in range(0, len(hosts), BATCH):
        yield hosts[i : i + BATCH]


def arp_sweep(
    params: ArpSweepParams,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    require_pcap()
    try:
        iface, _, _ = default_route()
        net = get_network_info()
    except NoNetworkError as e:
        raise JobError("no_network") from e
    if not net.sweep_allowed:
        raise JobError("subnet_too_large")

    subnet = ipaddress.IPv4Network(net.cidr)
    deadline = clock() + params.budget_seconds
    found: dict[str, Observation] = {}
    lock = threading.Lock()

    def on_packet(pkt: Packet) -> None:
        obs = observation_from_arp(pkt, "arp_sweep", datetime.now(UTC))
        if obs and obs.ip and ipaddress.IPv4Address(obs.ip) in subnet:
            with lock:
                found.setdefault(obs.ip, obs)

    def wait_until(t: float) -> None:
        while (left := min(t, deadline) - clock()) > 0:
            sleep(min(left, 0.5))

    started = clock()
    complete = True
    listener = _listen(iface, on_packet)
    try:
        pass_took = 0.0
        for i in range(params.passes):
            if i:
                # The second pass only starts if it can finish by the deadline.
                if clock() + params.gap_seconds + pass_took > deadline:
                    complete = False
                    break
                wait_until(clock() + params.gap_seconds)
            pass_start = clock()
            for batch in _batches(subnet, net.own_ip):
                if clock() >= deadline:
                    complete = False
                    break
                _send([Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=ip) for ip in batch], iface)
            wait_until(clock() + REPLY_WAIT_SECONDS)
            pass_took = clock() - pass_start
            if not complete:
                break
    finally:
        listener.stop()

    with lock:
        observations = list(found.values())
    took = clock() - started
    if complete:
        log.info("arp_sweep: %d hosts in %.1f s", len(observations), took)
    else:
        log.warning(
            "arp_sweep stopped at its %.0f s limit after %.1f s, with %d hosts so far",
            params.budget_seconds,
            took,
            len(observations),
        )
    session.record_swept([o.ip for o in observations if o.ip])
    return [o.model_dump(mode="json") for o in observations]
