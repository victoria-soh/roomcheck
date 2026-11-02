"""Collect Layer 3 network facts. Each check fails on its own with a plain message.

Runs without consent: Wi-Fi encryption (local), DNS (two ordinary lookups through the
system resolver, as any browser makes) and the ARP check (from traffic already heard).
Needs consent: the DHCP probe and UPnP (from the SSDP search). The NVD lookup needs consent
(models come from consented checks) and can be switched off with online=False.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from app.checks import cve as cve_mod
from app.checks.dns import check_dns
from app.checks.models import ArpClaim, DhcpOffer, DnsResult, NetworkFacts, WifiStatus
from app.checks.wifi import WifiCheckError, current_wifi
from app.discovery.merge import _clean_mac
from app.discovery.messages import message_for
from app.discovery.models import CheckStatus, DiscoveryResult
from app.fingerprint.oui import lookup_vendor
from app.scanner import Scanner, ScannerError

log = logging.getLogger(__name__)

DHCP_JOB_TIMEOUT_SECONDS = 30
NVD_BUDGET_SECONDS = 35.0

LABELS = {
    "wifi_encryption": "Checking how your Wi-Fi connection is encrypted",
    "dns": "Checking that web addresses are looked up honestly",
    "arp": "Watching which devices answer for the router",
    "dhcp": "Checking for a second device handing out network addresses",
    "upnp": "Checking whether the router lets devices open internet ports",
    "cve": "Looking up known issues for identified models",
}


def _status(name: str, status: str, code: str | None = None, found: int = 0) -> CheckStatus:
    return CheckStatus(
        name=name,
        label=LABELS[name],
        status=status,  # type: ignore[arg-type]
        reason=message_for(code) if code else None,
        found=found,
    )


def gateway_claims(result: DiscoveryResult) -> list[ArpClaim]:
    """Every MAC seen claiming the gateway IP in ARP traffic, with first and last sighting."""
    if result.network is None:
        return []
    gw = result.network.gateway_ip
    claims: dict[str, ArpClaim] = {}
    for o in result.observations:
        if o.source not in ("arp_passive", "arp_sweep") or o.ip != gw:
            continue
        mac = _clean_mac(o.mac)
        if mac is None:
            continue
        c = claims.get(mac)
        if c is None:
            claims[mac] = ArpClaim(
                ip=gw, mac=mac, vendor=lookup_vendor(mac), first_seen=o.seen_at, last_seen=o.seen_at
            )
        else:
            c.first_seen = min(c.first_seen, o.seen_at)
            c.last_seen = max(c.last_seen, o.seen_at)
    return list(claims.values())


def _ran(result: DiscoveryResult, name: str) -> bool:
    return any(c.name == name and c.status == "ran" for c in result.checks)


def run_network_checks(
    result: DiscoveryResult,
    *,
    consent: bool,
    scanner: Scanner | None,
    online: bool = True,
    wifi_fn: Callable[[str], WifiStatus | None] = current_wifi,
    dns_fn: Callable[[], DnsResult] = check_dns,
    nvd_factory: Callable[[], cve_mod.NvdClient] = cve_mod.make_client,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[NetworkFacts, list[CheckStatus], list[str]]:
    facts = NetworkFacts()
    checks: list[CheckStatus] = []
    messages: list[str] = []
    net = result.network
    if net is None:
        return facts, [_status(n, "skipped", "no_network") for n in LABELS], messages

    # Wi-Fi encryption (local only)
    try:
        facts.wifi = wifi_fn(net.interface)
        if facts.wifi is None:
            checks.append(_status("wifi_encryption", "skipped", "not_wifi"))
        else:
            checks.append(_status("wifi_encryption", "ran", found=1))
    except WifiCheckError as e:
        code = "wifi_unreadable" if e.code == "unreadable" else "not_wifi"
        checks.append(
            _status("wifi_encryption", "failed" if code == "wifi_unreadable" else "skipped", code)
        )

    # DNS through the system resolver
    try:
        facts.dns = dns_fn()
        if facts.dns.nxdomain is None and not facts.dns.checked_domains:
            checks.append(_status("dns", "failed", "dns_unclear"))
        else:
            checks.append(_status("dns", "ran", found=1 + len(facts.dns.checked_domains)))
    except Exception:
        log.exception("DNS check failed")
        checks.append(_status("dns", "failed", "dns_unclear"))

    # ARP: who answered for the gateway, from traffic already heard
    if _ran(result, "passive_listen") or _ran(result, "arp_sweep"):
        facts.arp_claims = gateway_claims(result)
        checks.append(_status("arp", "ran", found=len(facts.arp_claims)))
    else:
        checks.append(_status("arp", "skipped", "no_listener"))

    # DHCP: one DISCOVER through the scanner worker, with consent only
    if not consent:
        checks.append(_status("dhcp", "skipped", "passive_mode"))
    else:
        try:
            if scanner is None:
                raise ScannerError("scanner_unavailable")
            raw = scanner.run("dhcp_probe", {}, DHCP_JOB_TIMEOUT_SECONDS) or []
            facts.dhcp_offers = [DhcpOffer.model_validate(o) for o in raw]
            if facts.dhcp_offers:
                found = len({o.server_id for o in facts.dhcp_offers})
                checks.append(_status("dhcp", "ran", found=found))
            else:
                checks.append(_status("dhcp", "ran", "no_dhcp_offer"))
        except ScannerError as e:
            checks.append(_status("dhcp", "failed", e.code))

    # UPnP: judged from the SSDP search, which needs consent
    if _ran(result, "ssdp"):
        checks.append(_status("upnp", "ran", found=1))
    else:
        ssdp = next((c for c in result.checks if c.name == "ssdp"), None)
        checks.append(
            CheckStatus(
                name="upnp",
                label=LABELS["upnp"],
                status="skipped",
                reason=ssdp.reason if ssdp and ssdp.reason else message_for("passive_mode"),
            )
        )

    # Known issues for reported models (NVD, optional outside call)
    if not online:
        checks.append(_status("cve", "skipped", "offline"))
    elif not consent:
        checks.append(_status("cve", "skipped", "passive_mode"))
    else:
        queries = {d.id: cve_mod.model_queries(d) for d in result.devices}
        queries = {k: v for k, v in queries.items() if v}
        if not queries:
            checks.append(_status("cve", "ran", "no_models"))
        else:
            client = nvd_factory()
            deadline = clock() + NVD_BUDGET_SECONDS
            try:
                for device_id, qs in queries.items():
                    for word, model in qs:
                        matches = client.lookup(word, model, deadline)
                        if matches:
                            facts.cves.setdefault(device_id, []).extend(matches)
                checks.append(_status("cve", "ran", found=len(facts.cves)))
            except cve_mod.NvdUnavailable as e:
                log.info("NVD lookup skipped: %s", e)
                checks.append(_status("cve", "skipped", "nvd_unavailable"))
            finally:
                client.cache.close()

    return facts, checks, messages
