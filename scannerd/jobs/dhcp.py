"""R-DHCP input: send one DHCPDISCOVER and count the distinct servers that offer within 5 s.

Uses the laptop's own MAC and client ID, so a server just offers the lease the laptop already
has. Nothing is requested or accepted (no DHCPREQUEST), so no address is taken. Takes no
parameters.
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any

from pydantic import BaseModel, ConfigDict
from scapy.layers.dhcp import BOOTP, DHCP
from scapy.layers.inet import IP, UDP
from scapy.layers.l2 import Ether
from scapy.packet import Packet

from app.discovery.netinfo import NoNetworkError, default_route, get_network_info
from scannerd.protocol import JobError, require_pcap

LISTEN_SECONDS = 5.0
MAX_OFFERS = 32
DHCP_OFFER = 2


class DhcpProbeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


def client_id(mac: str) -> bytes:
    return bytes([1]) + bytes.fromhex(mac.replace(":", ""))  # 1 = hardware type Ethernet


def discover_packet(mac: str, xid: int) -> Packet:
    chaddr = bytes.fromhex(mac.replace(":", ""))
    return (
        Ether(src=mac, dst="ff:ff:ff:ff:ff:ff")
        / IP(src="0.0.0.0", dst="255.255.255.255")
        / UDP(sport=68, dport=67)
        / BOOTP(op=1, chaddr=chaddr, xid=xid, flags=0x8000)  # broadcast replies
        / DHCP(
            options=[
                ("message-type", "discover"),
                # Option 61, as Windows sends it (type 1 = Ethernet, then the MAC). Routers key
                # leases on it, so the server offers the lease the laptop already holds.
                ("client_id", client_id(mac)),
                ("param_req_list", [1, 3, 6]),
                "end",
            ]
        )
    )


def parse_offers(packets: list[Packet], xid: int) -> list[dict[str, Any]]:
    """Offers answering our transaction, one per (server id, server MAC)."""
    seen: dict[tuple[str, str | None], dict[str, Any]] = {}
    for pkt in packets:
        bootp = pkt.getlayer(BOOTP)
        dhcp = pkt.getlayer(DHCP)
        if bootp is None or dhcp is None or bootp.op != 2 or bootp.xid != xid:
            continue
        opts = {o[0]: o[1] for o in dhcp.options if isinstance(o, tuple) and len(o) >= 2}
        if opts.get("message-type") != DHCP_OFFER:
            continue
        server_id = str(opts.get("server_id") or (pkt[IP].src if pkt.getlayer(IP) else ""))
        if not server_id:
            continue
        server_mac = pkt[Ether].src if pkt.getlayer(Ether) is not None else None
        seen.setdefault(
            (server_id, server_mac),
            {"server_id": server_id, "server_mac": server_mac, "offered_ip": bootp.yiaddr},
        )
        if len(seen) >= MAX_OFFERS:
            break
    return list(seen.values())


def dhcp_probe(params: DhcpProbeParams) -> list[dict[str, Any]]:
    from scapy.sendrecv import AsyncSniffer, sendp

    require_pcap()
    try:
        iface, _, _ = default_route()
        net = get_network_info()
    except NoNetworkError as e:
        raise JobError("no_network") from e
    if not net.own_mac:
        raise JobError("internal", "no MAC address for the interface")

    xid = secrets.randbits(32)
    ready = threading.Event()
    sniffer = AsyncSniffer(
        iface=iface,
        filter="udp and src port 67 and dst port 68",
        store=True,
        started_callback=ready.set,
    )
    sniffer.start()
    ready.wait(3)
    sendp(discover_packet(net.own_mac, xid), iface=iface, verbose=False)
    time.sleep(LISTEN_SECONDS)
    packets: list[Packet] = list(sniffer.stop() or [])
    return parse_offers(packets, xid)
