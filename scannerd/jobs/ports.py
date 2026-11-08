"""Layer 2 port check: nmap with a fixed port list and fixed settings, run only by scannerd.

The job takes no parameters. Targets are the hosts scannerd's own ARP sweep or passive listener
saw this session (see scannerd/session.py),
re-checked against the current subnet; the arguments are constants. Nothing from the app ever
reaches the nmap command line.
"""

from __future__ import annotations

import ipaddress
import shutil
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.discovery.netinfo import NoNetworkError, get_network_info
from scannerd import session
from scannerd.protocol import JobError

PORTS = (23, 80, 443, 554, 8554, 1883, 8883, 6668, 8000, 8080, 8443, 34567, 37777)
PORT_LIST = ",".join(map(str, PORTS))
NMAP_ARGUMENTS = "-sT -Pn -T3 --max-retries 1 --host-timeout 30s"
MAX_HOSTS = 256
NMAP_TIMEOUT_SECONDS = 240


class PortScanParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


def select_targets(swept: list[str], cidr: str, own_ip: str) -> list[str]:
    net = ipaddress.IPv4Network(cidr)
    targets = []
    for ip in swept:
        addr = ipaddress.IPv4Address(ip)
        if (
            addr in net
            and addr not in (net.network_address, net.broadcast_address)
            and ip != own_ip
        ):
            targets.append(ip)
    return targets[:MAX_HOSTS]


def parse_scan(scan: dict[str, Any], targets: list[str]) -> list[dict[str, Any]]:
    """python-nmap result -> [{ip, open_ports, complete}] for every target.

    A target missing from nmap's output (for example after --host-timeout) is incomplete.
    """
    hosts = scan.get("scan") if isinstance(scan, dict) else None
    if not isinstance(hosts, dict):
        hosts = {}
    out = []
    for ip in targets:
        host = hosts.get(ip)
        if not isinstance(host, dict):
            out.append({"ip": ip, "open_ports": [], "complete": False})
            continue
        tcp = host.get("tcp", {}) or {}
        open_ports = sorted(
            int(p)
            for p, info in tcp.items()
            if isinstance(info, dict) and info.get("state") == "open" and int(p) in PORTS
        )
        out.append({"ip": ip, "open_ports": open_ports, "complete": True})
    return out


def port_scan(params: PortScanParams) -> list[dict[str, Any]]:
    import nmap

    nmap_path = shutil.which("nmap")
    if nmap_path is None:
        raise JobError("nmap_missing")
    try:
        net = get_network_info()
    except NoNetworkError as e:
        raise JobError("no_network") from e

    targets = select_targets(session.port_targets(), net.cidr, net.own_ip)
    if not targets:
        return []
    try:
        scanner = nmap.PortScanner(nmap_search_path=(nmap_path,))
        result = scanner.scan(
            hosts=" ".join(targets),
            ports=PORT_LIST,
            arguments=NMAP_ARGUMENTS,
            timeout=NMAP_TIMEOUT_SECONDS,
        )
    except nmap.PortScannerTimeout as e:
        raise JobError("timeout") from e
    except nmap.PortScannerError as e:
        if "not found" in str(e).lower():
            raise JobError("nmap_missing") from e
        raise JobError("nmap_failed", str(e)[:200]) from e
    return parse_scan(result, targets)
