"""Rules engine: fixed rules from rules.yaml decide every finding and the room summary.

Pure functions over already-collected facts; no I/O apart from loading the YAML once.
Predicates are a fixed registry of named Python functions: the YAML picks one and gives it
arguments, it never contains code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from app.checks.dns import is_tampered
from app.checks.models import ArpClaim, NetworkFacts
from app.checks.wifi import is_weak
from app.discovery.models import CheckStatus, Device, NetworkInfo
from app.fingerprint.models import Band
from app.rules.models import Finding, RoomSummary, Severity

RULES_FILE = Path(__file__).resolve().parent / "rules.yaml"
SEVERITY_ORDER: dict[str, int] = {"High": 0, "Medium": 1, "Low": 2, "Info": 3}

# Virtual router MACs that legitimately share a gateway IP (VRRP, HSRP).
_VIRTUAL_MAC_PREFIXES = ("00:00:5e:00:01:", "00:00:5e:00:02:", "00:00:0c:07:ac:", "00:00:0c:9f:f")


@dataclass
class RoomFacts:
    devices: list[Device]
    network: NetworkInfo | None
    net: NetworkFacts = field(default_factory=NetworkFacts)
    checks: list[CheckStatus] = field(default_factory=list)

    def device(self, device_id: str) -> Device | None:
        return next((d for d in self.devices if d.id == device_id), None)


@dataclass
class Match:
    band: Band
    evidence: list[str]
    variant: str | None = None
    device_ref: str | None = None  # network rules may point at the device involved


DevicePredicate = Callable[[Device, RoomFacts, dict[str, Any]], Match | None]
NetworkPredicate = Callable[[RoomFacts, dict[str, Any]], Match | None]


# --- device predicates ------------------------------------------------------------------------


def _type_score(device: Device, type_id: str) -> tuple[float, Band, list[str], str] | None:
    fp = device.fingerprint
    if fp is None:
        return None
    if fp.type == type_id:
        return fp.confidence, fp.band, [e.text for e in fp.evidence], fp.label
    for t in fp.other_types + fp.weak_types:
        if t.type == type_id:
            return t.score, t.band, [e.text for e in t.evidence], t.label
    return None


def type_score(device: Device, facts: RoomFacts, args: dict[str, Any]) -> Match | None:
    found = _type_score(device, str(args["type"]))
    if found is None or found[0] < float(args["min"]):
        return None
    _, band, evidence, label = found
    return Match(
        band=band, evidence=[f"Looks like a {label.lower()}: {band}", *evidence], variant=band
    )


def open_port(device: Device, facts: RoomFacts, args: dict[str, Any]) -> Match | None:
    ports = device.identity.open_ports if device.identity else None
    port = int(args["port"])
    if not ports or port not in ports:
        return None
    return Match(band="Likely", evidence=[f"Port {port} ({args['service']}) is open"])


def cloud_link(device: Device, facts: RoomFacts, args: dict[str, Any]) -> Match | None:
    evidence: list[str] = []
    band: Band | None = None
    if any(s.kind == "tuya" for s in device.services):
        evidence.append("Sends Tuya / Smart Life broadcasts, so it is run through a cloud account")
        band = "Likely"
    ports = device.identity.open_ports if device.identity else None
    if ports and 6668 in ports:
        evidence.append("Has the Tuya local-control port (6668) open")
        band = "Likely"
    for type_id in args.get("types", []):
        found = _type_score(device, str(type_id))
        if found and found[0] >= float(args.get("min", 0.5)):
            evidence.append(f"Looks like a {found[3].lower()}: {found[1]}")
            band = band or found[1]
    return Match(band=band, evidence=evidence) if band else None


def known_issues(device: Device, facts: RoomFacts, args: dict[str, Any]) -> Match | None:
    matches = facts.net.cves.get(device.id)
    if not matches:
        return None
    evidence = []
    exploited: list[str] = []
    for m in matches:
        product = m.cpe.split(":", 4)[-1].replace("\\", "")
        evidence.append(
            f'Known issues reported for this model: the device reported "{m.model}", which '
            f'matches NVD product "{product}" with {m.total} reported issue(s), '
            f"for example {', '.join(m.cve_ids[:3])}"
        )
        exploited += m.exploited
    if exploited:
        evidence.append(
            "Some are on CISA's list of issues known to be actively exploited: "
            + ", ".join(dict.fromkeys(exploited))
        )
    # The firmware version can't be confirmed, so the match itself is only "Possible".
    return Match(
        band="Possible", evidence=evidence, variant="exploited" if exploited else "reported"
    )


# --- network predicates -----------------------------------------------------------------------


def wifi_weak(facts: RoomFacts, args: dict[str, Any]) -> Match | None:
    wifi = facts.net.wifi
    if wifi is None or not is_weak(wifi):
        return None
    name = f'"{wifi.ssid}"' if wifi.ssid else "your Wi-Fi network"
    return Match(
        band="Likely",
        evidence=[
            f'Your connection to {name} uses authentication "{wifi.authentication}" '
            f'and encryption "{wifi.cipher}"'
        ],
    )


def _is_igd(device: Device) -> bool:
    names = [s.name for s in device.services if s.kind == "ssdp"]
    if device.identity and device.identity.upnp and device.identity.upnp.device_type:
        names.append(device.identity.upnp.device_type)
    return any("InternetGatewayDevice" in n for n in names)


def upnp_igd(facts: RoomFacts, args: dict[str, Any]) -> Match | None:
    igds = [d for d in facts.devices if _is_igd(d)]
    if not igds:
        return None
    ref = next((d for d in igds if d.is_gateway), igds[0])
    evidence = [
        f"{d.ip or 'A device'} ({d.vendor or 'maker unknown'}) offers internet gateway "
        "controls (UPnP)" + (", and it is this network's router" if d.is_gateway else "")
        for d in igds
    ]
    return Match(band="Likely", evidence=evidence, device_ref=ref.id)


def dns_tampered(facts: RoomFacts, args: dict[str, Any]) -> Match | None:
    dns = facts.net.dns
    if dns is None or not is_tampered(dns):
        return None
    evidence = []
    if dns.nxdomain is False:
        evidence.append(
            f"A made-up web address ({dns.random_name}) got an answer "
            f'({", ".join(dns.random_name_answers)}) instead of "doesn\'t exist"'
        )
    for domain, ips in dns.non_public_answers.items():
        evidence.append(f"{domain} pointed to a private or reserved address ({', '.join(ips)})")
    return Match(band="Likely", evidence=evidence)


def _is_virtual_router_mac(mac: str) -> bool:
    return mac.lower().startswith(_VIRTUAL_MAC_PREFIXES)


def gateway_claimed_twice(facts: RoomFacts, args: dict[str, Any]) -> Match | None:
    if facts.network is None:
        return None
    gw = facts.network.gateway_ip
    claims = [c for c in facts.net.arp_claims if c.ip == gw and not _is_virtual_router_mac(c.mac)]
    by_mac = {c.mac: c for c in claims}
    if len(by_mac) < 2:
        return None
    vendors = {c.vendor for c in by_mac.values()}
    same_maker = None not in vendors and len(vendors) == 1
    flipping = _flip_flops(list(by_mac.values()))
    evidence = [
        f"{c.mac} ({c.vendor or 'maker unknown'}) answered for the router's address {gw} "
        f"between {c.first_seen:%H:%M:%S} and {c.last_seen:%H:%M:%S}"
        for c in sorted(by_mac.values(), key=lambda c: c.first_seen)
    ]
    if same_maker:
        evidence.append("All answers came from the same maker")
    if flipping:
        evidence.append("The answer kept switching back and forth between them during the scan")
    if not same_maker:
        variant = "different_makers"
    elif flipping:
        variant = "same_maker_flip_flop"
    else:
        variant = "same_maker"
    router = next((d for d in facts.devices if d.is_gateway), None)
    return Match(
        band="Possible" if variant == "same_maker" else "Likely",
        evidence=evidence,
        variant=variant,
        device_ref=router.id if router else None,
    )


def _flip_flops(claims: list[ArpClaim]) -> bool:
    """True if one MAC was seen both before and after another: A, then B, then A again.

    Only first and last sightings are kept per MAC, so overlapping sighting windows are the
    sign of switching back and forth. A clean handover (A stops, then B starts) doesn't count.
    """
    for i, a in enumerate(claims):
        for b in claims[i + 1 :]:
            if a.first_seen < b.last_seen and b.first_seen < a.last_seen:
                return True
    return False


def dhcp_servers(facts: RoomFacts, args: dict[str, Any]) -> Match | None:
    offers = facts.net.dhcp_offers
    if not offers:
        return None
    servers: dict[str, list[str]] = {}
    for o in offers:
        servers.setdefault(o.server_id, [])
        if o.server_mac and o.server_mac not in servers[o.server_id]:
            servers[o.server_id].append(o.server_mac)
    if len(servers) < int(args.get("min", 2)):
        return None
    evidence = [
        f"{sid} offered an address" + (f" (sent from {', '.join(macs)})" if macs else "")
        for sid, macs in servers.items()
    ]
    return Match(band="Likely", evidence=evidence)


DEVICE_PREDICATES: dict[str, DevicePredicate] = {
    "type_score": type_score,
    "open_port": open_port,
    "cloud_link": cloud_link,
    "known_issues": known_issues,
}
NETWORK_PREDICATES: dict[str, NetworkPredicate] = {
    "wifi_weak": wifi_weak,
    "upnp_igd": upnp_igd,
    "dns_tampered": dns_tampered,
    "gateway_claimed_twice": gateway_claimed_twice,
    "dhcp_servers": dhcp_servers,
}


# --- evidence fields --------------------------------------------------------------------------


def _field(name: str, d: Device) -> str | None:
    if name == "maker":
        if d.vendor:
            return f"Maker: {d.vendor}"
        return "Maker: unknown (private address)" if d.mac_is_random else "Maker: unknown"
    if name == "address":
        return f"Network address: {d.ip}" if d.ip else None
    if name == "open_ports":
        ports = d.identity.open_ports if d.identity else None
        return f"Open services on ports: {', '.join(map(str, ports))}" if ports else None
    if name == "notes":
        notes = d.fingerprint.notes if d.fingerprint else []
        return "; ".join(notes) or None
    if name == "identification":
        if d.fingerprint and d.fingerprint.identification == "partial":
            return "Partly identified: some checks on this device didn't finish"
        return None
    raise ValueError(f"unknown evidence field {name!r}")


# --- rules file -------------------------------------------------------------------------------

EVIDENCE_FIELDS = ("maker", "address", "open_ports", "notes", "identification")


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    scope: str
    when: dict[str, dict[str, Any]]
    severity: Severity | dict[str, Severity]
    title: str | dict[str, str]
    next_step: str | dict[str, str]
    guidance: list[str] = []
    evidence_fields: list[str] = []

    @field_validator("when")
    @classmethod
    def _one_known_predicate(
        cls, v: dict[str, dict[str, Any]], info: Any
    ) -> dict[str, dict[str, Any]]:
        if len(v) != 1:
            raise ValueError("`when` must name exactly one predicate")
        (name,) = v
        if name not in DEVICE_PREDICATES and name not in NETWORK_PREDICATES:
            raise ValueError(f"unknown predicate {name!r}")
        return v

    @field_validator("scope")
    @classmethod
    def _scope(cls, v: str) -> str:
        if v not in ("device", "network"):
            raise ValueError("scope must be device or network")
        return v

    @field_validator("evidence_fields")
    @classmethod
    def _fields(cls, v: list[str]) -> list[str]:
        unknown = set(v) - set(EVIDENCE_FIELDS)
        if unknown:
            raise ValueError(f"unknown evidence fields {sorted(unknown)}")
        return v

    def predicate_name(self) -> str:
        return next(iter(self.when))

    def pick(self, value: Any, variant: str | None) -> Any:
        if isinstance(value, dict):
            if variant not in value:
                raise ValueError(f"{self.id}: no entry for variant {variant!r}")
            return value[variant]
        return value


class RulesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cant_see: list[str]
    not_yet_checked: list[str] = []
    rules: list[Rule]


@lru_cache(maxsize=4)
def load_rules(path: Path = RULES_FILE) -> RulesFile:
    with path.open(encoding="utf-8") as f:
        rules = RulesFile.model_validate(yaml.safe_load(f))
    for r in rules.rules:
        pred = r.predicate_name()
        expected = DEVICE_PREDICATES if r.scope == "device" else NETWORK_PREDICATES
        if pred not in expected:
            raise ValueError(f"{r.id}: predicate {pred!r} doesn't fit scope {r.scope!r}")
    return rules


# --- evaluation -------------------------------------------------------------------------------


def _finding(rule: Rule, m: Match, device: Device | None) -> Finding:
    evidence = list(m.evidence)
    if device is not None:
        evidence += [x for x in (_field(f, device) for f in rule.evidence_fields) if x]
    ref = device.id if device is not None else m.device_ref
    return Finding(
        id=f"{rule.id}:{device.id if device is not None else 'network'}",
        rule_id=rule.id,
        severity=rule.pick(rule.severity, m.variant),
        confidence_band=m.band,
        device_ref=ref,
        title=rule.pick(rule.title, m.variant),
        evidence=evidence,
        next_step=" ".join(rule.pick(rule.next_step, m.variant).split()),
        guidance=[" ".join(g.split()) for g in rule.guidance],
    )


def evaluate(facts: RoomFacts, rules: RulesFile | None = None) -> list[Finding]:
    rules = rules or load_rules()
    findings: list[Finding] = []
    for rule in rules.rules:
        name = rule.predicate_name()
        args = rule.when[name]
        if rule.scope == "device":
            for d in facts.devices:
                m = DEVICE_PREDICATES[name](d, facts, args)
                if m is not None:
                    findings.append(_finding(rule, m, d))
        else:
            m = NETWORK_PREDICATES[name](facts, args)
            if m is not None:
                findings.append(_finding(rule, m, None))
    order = {r.id: i for i, r in enumerate(rules.rules)}
    return sorted(findings, key=lambda f: (SEVERITY_ORDER[f.severity], order[f.rule_id]))


def summarise(
    findings: list[Finding], checks: list[CheckStatus], rules: RulesFile | None = None
) -> RoomSummary:
    rules = rules or load_rules()
    high = sum(f.severity == "High" for f in findings)
    medium = sum(f.severity == "Medium" for f in findings)
    if high:
        status = "Needs attention"
    elif medium:
        status = "Check these items"
    else:
        status = "Nothing found by these checks"
    not_checked = [
        f"{c.label}: {c.reason}" if c.reason else c.label for c in checks if c.status != "ran"
    ] + list(rules.not_yet_checked)
    return RoomSummary(
        status=status,  # type: ignore[arg-type]
        high=high,
        medium=medium,
        other=len(findings) - high - medium,
        not_checked=not_checked,
        cant_see=list(rules.cant_see),
    )
