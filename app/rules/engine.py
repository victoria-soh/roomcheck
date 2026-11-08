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

from app.baseline.keys import device_keys
from app.baseline.models import BaselineFacts
from app.checks.dns import is_tampered
from app.checks.models import ArpClaim, NetworkFacts
from app.checks.wifi import is_weak
from app.discovery.models import CheckStatus, Device, NetworkInfo
from app.fingerprint.models import Band, Evidence
from app.rules.models import (
    Draft,
    Finding,
    Location,
    Match,
    Question,
    RoomSummary,
    Severity,
    StayType,
)
from app.rules.nearby import NEARBY_PREDICATES
from app.wireless.models import NearbySurvey

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
    nearby: NearbySurvey | None = None  # Layer 4, in memory only
    baseline: BaselineFacts | None = None  # Layer 6: the move-in scan's keys, if one is saved
    stay: StayType | None = None  # where the user is staying, from Start

    def device(self, device_id: str) -> Device | None:
        return next((d for d in self.devices if d.id == device_id), None)


DevicePredicate = Callable[[Device, RoomFacts, dict[str, Any]], Match | None]
NetworkPredicate = Callable[[RoomFacts, dict[str, Any]], Match | None]


# --- device predicates ------------------------------------------------------------------------


def _type_score(device: Device, type_id: str) -> tuple[float, Band, list[str], str] | None:
    found = _type_match(device, type_id)
    if found is None:
        return None
    score, band, evidence, label = found
    return score, band, [e.text for e in evidence], label


def _type_match(device: Device, type_id: str) -> tuple[float, Band, list[Evidence], str] | None:
    fp = device.fingerprint
    if fp is None:
        return None
    if fp.type == type_id:
        return fp.confidence, fp.band, fp.evidence, fp.label
    for t in fp.other_types + fp.weak_types:
        if t.type == type_id:
            return t.score, t.band, t.evidence, t.label
    return None


def _lead_clue(evidence: list[Evidence]) -> str:
    """The plainest clue for the summary (weights.yaml plain_rank; the stronger one on a tie).
    Only which sentence leads changes: the score and the clue list stay as they are."""
    ranked = sorted((e for e in evidence if e.clue), key=lambda e: (e.plain_rank, -e.weight))
    return ranked[0].clue if ranked else ""


def _clues(evidence: list[Evidence]) -> list[str]:
    """The plain sentences for "What we observed", strongest clue first, each said once."""
    return list(dict.fromkeys(e.clue for e in evidence if e.clue))


def type_score(device: Device, facts: RoomFacts, args: dict[str, Any]) -> Match | None:
    found = _type_match(device, str(args["type"]))
    if found is None or found[0] < float(args["min"]):
        return None
    _, band, evidence, label = found
    return Match(
        band=band,
        evidence=[f"Looks like a {label.lower()}: {band}", *(e.text for e in evidence)],
        variant=band,
        clues=_clues(evidence),
        lead_clue=_lead_clue(evidence),
    )


def new_since_baseline(device: Device, facts: RoomFacts, args: dict[str, Any]) -> Match | None:
    """A device of this type (e.g. camera-like) that wasn't in the move-in scan. A device whose
    soft key matches is "possibly the same device", so it doesn't count as new; nor does a
    device with no stable key, since there's nothing to compare it on."""
    if facts.baseline is None:
        return None
    found = _type_match(device, str(args["type"]))
    if found is None or found[0] < float(args["min"]):
        return None
    keys = device_keys(device, facts.baseline.salt)
    if keys.key is None or keys.key in facts.baseline.keys or keys.soft in facts.baseline.soft_keys:
        return None
    _, band, evidence, label = found
    when = f"{facts.baseline.saved_at:%d %b %Y}".lstrip("0")
    return Match(
        band=band,
        evidence=[
            f"It wasn't in your move-in scan on {when}.",
            f"Looks like a {label.lower()}: {band}",
            *(e.text for e in evidence),
        ],
        clues=[f"It wasn't in your move-in scan on {when}.", *_clues(evidence)],
        lead_clue=_lead_clue(evidence),
    )


def open_port(device: Device, facts: RoomFacts, args: dict[str, Any]) -> Match | None:
    ports = device.identity.open_ports if device.identity else None
    port = int(args["port"])
    if not ports or port not in ports:
        return None
    return Match(band="Likely", evidence=[f"Port {port} ({args['service']}) is open"])


def cloud_link(device: Device, facts: RoomFacts, args: dict[str, Any]) -> Match | None:
    evidence: list[str] = []
    clues: list[str] = []
    band: Band | None = None
    if any(s.kind == "tuya" for s in device.services):
        evidence.append("Sends Tuya / Smart Life broadcasts, so it is run through a cloud account")
        clues.append("It sends Tuya / Smart Life broadcasts, which come from cloud-run devices.")
        band = "Likely"
    ports = device.identity.open_ports if device.identity else None
    if ports and 6668 in ports:
        evidence.append("Has the Tuya local-control port (6668) open")
        clues.append("It has the Tuya local-control port (6668) open.")
        band = "Likely"
    for type_id in args.get("types", []):
        found = _type_match(device, str(type_id))
        if found and found[0] >= float(args.get("min", 0.5)):
            evidence.append(f"Looks like a {found[3].lower()}: {found[1]}")
            clues += _clues(found[2])
            band = band or found[1]
    return Match(band=band, evidence=evidence, clues=list(dict.fromkeys(clues))) if band else None


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
    "new_since_baseline": new_since_baseline,
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


class LocationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: str
    draft: Draft = "host"


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    scope: str
    question: Question  # the renter's question it answers (Results and the report)
    when: dict[str, dict[str, Any]]
    severity: Severity | dict[str, Severity]
    title: str | dict[str, str]
    observed: str | dict[str, str]  # what was seen, in one sentence
    # What it could mean for the person, in one fixed sentence: the risk, never a repeat of
    # what was observed.
    could_mean: str | dict[str, str]
    next_step: str | dict[str, str]
    # Next steps for a stay type; next_step is the default ("Other", or not listed).
    next_step_by_stay: dict[StayType, str] = {}
    guidance: list[str] = []
    guidance_by_stay: dict[StayType, list[str]] = {}  # guidance is the default
    # Camera rules: the next step once the user says where it is, by stay type ("other"
    # is the default), with the message the card offers for it.
    next_step_by_location: dict[Location, dict[StayType, LocationStep]] = {}
    evidence_fields: list[str] = []
    # Layer 5 standard text: used whenever the AI explanation isn't available or is rejected.
    explanation: str | dict[str, str]
    why_it_matters: str | dict[str, str]
    landlord_question: str | dict[str, str] | None = None
    # Nearby rules about the network you're connected to (its router or access point) are shown
    # with your network on Results, not on Nearby.
    about_your_network: bool = False

    @field_validator("when")
    @classmethod
    def _one_known_predicate(
        cls, v: dict[str, dict[str, Any]], info: Any
    ) -> dict[str, dict[str, Any]]:
        if len(v) != 1:
            raise ValueError("`when` must name exactly one predicate")
        (name,) = v
        if name not in DEVICE_PREDICATES | NETWORK_PREDICATES | NEARBY_PREDICATES:
            raise ValueError(f"unknown predicate {name!r}")
        return v

    @field_validator("scope")
    @classmethod
    def _scope(cls, v: str) -> str:
        if v not in ("device", "network", "nearby"):
            raise ValueError("scope must be device, network or nearby")
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


class QuestionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checks: list[str]  # the checks this question's status line depends on


class RulesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cant_see: list[str]
    not_yet_checked: list[str] = []
    questions: dict[Question, QuestionSpec]
    rules: list[Rule]


@lru_cache(maxsize=4)
def load_rules(path: Path = RULES_FILE) -> RulesFile:
    with path.open(encoding="utf-8") as f:
        rules = RulesFile.model_validate(yaml.safe_load(f))
    for r in rules.rules:
        pred = r.predicate_name()
        scopes: dict[str, dict[str, Any]] = {
            "device": DEVICE_PREDICATES,
            "network": NETWORK_PREDICATES,
            "nearby": NEARBY_PREDICATES,
        }
        expected = scopes[r.scope]
        if pred not in expected:
            raise ValueError(f"{r.id}: predicate {pred!r} doesn't fit scope {r.scope!r}")
    return rules


# --- evaluation -------------------------------------------------------------------------------


def _next_step(rule: Rule, m: Match, stay: StayType | None) -> str:
    step = rule.next_step_by_stay.get(stay) if stay else None
    return " ".join((step or rule.pick(rule.next_step, m.variant)).split())


def _finding(rule: Rule, m: Match, device: Device | None, stay: StayType | None = None) -> Finding:
    evidence = list(m.evidence)
    if device is not None:
        evidence += [x for x in (_field(f, device) for f in rule.evidence_fields) if x]
    ref = device.id if device is not None else m.device_ref
    if device is not None:
        key = device.id
    elif rule.scope == "nearby":
        key = m.nearby_ref or "nearby"
    else:
        key = "network"
    return Finding(
        id=f"{rule.id}:{key}",
        rule_id=rule.id,
        scope=rule.scope,  # type: ignore[arg-type]  # Rule._scope checks the value
        shown_on="nearby" if rule.scope == "nearby" and not rule.about_your_network else "results",
        question=rule.question,
        severity=rule.pick(rule.severity, m.variant),
        confidence_band=m.band,
        device_ref=ref,
        title=rule.pick(rule.title, m.variant),
        observed=" ".join(rule.pick(rule.observed, m.variant).split()),
        clues=list(m.clues),
        lead_clue=m.lead_clue,
        could_mean=" ".join(rule.pick(rule.could_mean, m.variant).split()),
        evidence=evidence,
        next_step=_next_step(rule, m, stay),
        guidance=[
            " ".join(g.split())
            for g in (rule.guidance_by_stay.get(stay) if stay else None) or rule.guidance
        ],
        asks_location=bool(rule.next_step_by_location),
        nearby_ref=m.nearby_ref,
        standard_explanation=" ".join(rule.pick(rule.explanation, m.variant).split()),
        standard_why=" ".join(rule.pick(rule.why_it_matters, m.variant).split()),
        landlord_question=(
            " ".join(rule.pick(rule.landlord_question, m.variant).split())
            if rule.landlord_question
            else None
        ),
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
                    findings.append(_finding(rule, m, d, facts.stay))
        elif rule.scope == "nearby":
            if facts.nearby is not None:
                for m in NEARBY_PREDICATES[name](facts.nearby, args):
                    findings.append(_finding(rule, m, None, facts.stay))
        else:
            m = NETWORK_PREDICATES[name](facts, args)
            if m is not None:
                findings.append(_finding(rule, m, None, facts.stay))
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
        status = "Not detected by these checks"
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


def location_step(
    rule_id: str, location: Location, stay: StayType | None, rules: RulesFile | None = None
) -> LocationStep | None:
    """The next step for a camera once the user says where it is, for their stay type."""
    rules = rules or load_rules()
    rule = next((r for r in rules.rules if r.id == rule_id), None)
    if rule is None or location not in rule.next_step_by_location:
        return None
    by_stay = rule.next_step_by_location[location]
    found = by_stay.get(stay or "other") or by_stay.get("other")
    if found is None:
        return None
    return LocationStep(step=" ".join(found.step.split()), draft=found.draft)
