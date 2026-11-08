"""Snapshot a check as the move-in baseline, and compare a later check with it. Pure functions.

The baseline keeps exactly what docs/original-plan.md lists: per device, a matching key, its type,
open ports and findings; per flagged nearby item, a salted hash and its findings. No addresses,
names, makers or network names.
"""

from __future__ import annotations

from datetime import datetime

from app.baseline.keys import DeviceKeys, device_keys, device_subject
from app.baseline.models import (
    Baseline,
    BaselineDevice,
    BaselineFinding,
    BaselineNearby,
    CompareItem,
    Comparison,
    MatchDecision,
)
from app.discovery.models import CoverageItem, Device, DiscoveryResult
from app.fingerprint.models import Band
from app.rules.models import Finding

NEARBY_LABELS = {"wifi": "Nearby Wi-Fi", "bluetooth": "Nearby Bluetooth device"}


def assign_subjects(result: DiscoveryResult, salt: bytes) -> None:
    """Give every finding the stable subject its recognition answer and task attach to."""
    devices = {d.id: d for d in result.devices}
    items = {i.ref: i for i in result.nearby_items}
    for f in result.findings:
        if f.scope == "nearby":
            item = items.get(f.nearby_ref or "")
            f.subject = item.match_key if item and item.match_key else f"nearby:scan:{f.nearby_ref}"
        elif f.scope == "device" and f.device_ref in devices:
            f.subject = device_subject(devices[f.device_ref], salt)
        else:
            f.subject = f"network:{f.rule_id}"


def _bf(f: Finding) -> BaselineFinding:
    return BaselineFinding(rule_id=f.rule_id, severity=f.severity, title=f.title)


def _type(d: Device) -> tuple[str, str]:
    if d.fingerprint is None:
        return "unknown", "Unknown device"
    return d.fingerprint.type, d.fingerprint.label


def _band(d: Device) -> Band | None:
    return d.fingerprint.band if d.fingerprint is not None else None


def _signals(d: Device) -> list[str]:
    return sorted({e.signal for e in d.fingerprint.evidence}) if d.fingerprint else []


BAND_ORDER: dict[str, int] = {"Unclear": 0, "Possible": 1, "Likely": 2}
CONFIDENT = ("Likely", "Possible")


def identification_varied(old: BaselineDevice, d: Device) -> bool:
    """Same type, overlapping clues, and only the confidence moved between Likely and
    Possible. That is the identification varying between checks (a device that missed one
    check's sweep gives fewer clues), not the device changing."""
    now = _band(d)
    if old.band is None or now is None or old.band == now:
        return False
    if old.band not in CONFIDENT or now not in CONFIDENT:
        return False
    if _type(d)[0] != old.type:
        return False
    return bool(set(old.signals) & set(_signals(d)))


def _higher(a: Band | None, b: Band | None) -> Band | None:
    if a is None or b is None:
        return a or b
    return a if BAND_ORDER[a] >= BAND_ORDER[b] else b


def _ports(d: Device) -> list[int]:
    return sorted(d.identity.open_ports or []) if d.identity else []


def _ports_checked(d: Device) -> bool:
    return d.identity is not None and d.identity.open_ports is not None


# The coverage areas (app/coverage.py) each rule needs, to tell "not seen" from "not checked".
RULE_AREAS: dict[str, tuple[str, ...]] = {
    "R-CAM": ("services",),
    "R-NEW-CAMERA": ("services",),
    "R-LOCK": ("services",),
    "R-CLOUD": ("services",),
    "R-TELNET": ("services",),
    "R-CVE": ("known_issues",),
    "R-UPNP": ("devices", "services"),
    "R-WIFI-ENC": ("router",),
    "R-DNS": ("router",),
    "R-ARP": ("router",),
    "R-DHCP": ("router",),
    "R-TRACKER": ("bluetooth",),
}


def _covered(rule_id: str, coverage: list[CoverageItem]) -> bool:
    if not coverage:
        return True  # an older result: nothing to go on
    states = {r.area: r.state for r in coverage}
    areas = RULE_AREAS.get(rule_id, ("nearby_wifi",))
    return all(states.get(a, "completed") == "completed" for a in areas)


def _checked(rule_id: str, result: DiscoveryResult) -> bool:
    """Could this check have found this rule again? Areas that were limited or didn't run
    can't say a finding is gone."""
    return _covered(rule_id, result.coverage)


def _findings_by_device(result: DiscoveryResult) -> dict[str, list[Finding]]:
    out: dict[str, list[Finding]] = {}
    for f in result.findings:
        if f.scope == "device" and f.device_ref:
            out.setdefault(f.device_ref, []).append(f)
    return out


def snapshot(result: DiscoveryResult, salt: bytes, saved_at: datetime) -> Baseline:
    by_device = _findings_by_device(result)
    devices: list[BaselineDevice] = []
    unkeyed = 0
    for d in result.devices:
        keys = device_keys(d, salt)
        if keys.key is None or keys.kind == "none":
            unkeyed += 1
            continue
        type_id, type_label = _type(d)
        devices.append(
            BaselineDevice(
                key=keys.key,
                kind=keys.kind,
                soft=keys.soft,
                type=type_id,
                type_label=type_label,
                ports=_ports(d),
                ports_checked=_ports_checked(d),
                findings=[_bf(f) for f in by_device.get(d.id, [])],
                band=_band(d),
                signals=_signals(d),
            )
        )
    nearby = [
        BaselineNearby(
            key=i.match_key,
            kind=i.kind,
            findings=[_bf(f) for f in result.findings if f.nearby_ref == i.ref],
        )
        for i in result.nearby_items
        if i.match_key
    ]
    network = [_bf(f) for f in result.findings if f.scope == "network"]
    return Baseline(
        saved_at=saved_at,
        devices=devices,
        unkeyed_devices=unkeyed,
        nearby=nearby,
        network_findings=network,
        mode=result.mode,
        coverage=list(result.coverage),
    )


def _changes(
    old: BaselineDevice,
    d: Device,
    findings: list[Finding],
    result: DiscoveryResult,
    baseline: Baseline,
) -> list[str]:
    """Differences either check could see. When one check only listened, a type guess made
    from fewer clues, or a finding only the permitted check could look for, isn't a change."""
    changes: list[str] = []
    differently = ran_differently(baseline, result)
    type_id, type_label = _type(d)
    both_sure = old.band == "Likely" and _band(d) == "Likely"
    if type_id != old.type and (not differently or both_sure):
        changes.append(f"Now looks like: {type_label} (at move-in: {old.type_label})")
    # Ports only when both checks looked at them: an unchecked port isn't a closed one.
    if old.ports_checked and _ports_checked(d):
        now_ports = set(_ports(d))
        for p in sorted(now_ports - set(old.ports)):
            changes.append(f"Newly open port: {p}")
        for p in sorted(set(old.ports) - now_ports):
            changes.append(f"No longer open: port {p}")
    old_rules = {f.rule_id for f in old.findings}
    now_rules = {f.rule_id for f in findings}
    for f in findings:
        # A finding the move-in check couldn't look for isn't new, only newly checked.
        if f.rule_id not in old_rules and _covered(f.rule_id, baseline.coverage):
            changes.append(f"New finding: {f.title}")
    for b in old.findings:
        if b.rule_id not in now_rules and _checked(b.rule_id, result):
            changes.append(f"No longer found: {b.title}")
    return changes


def ran_differently(baseline: Baseline, result: DiscoveryResult) -> bool:
    """One check had permission and the other only listened. The page then shows one plain
    note ("These checks ran differently, so some differences may come from that.") and no
    difference only the permitted check could see."""
    return baseline.mode is not None and baseline.mode != result.mode


def _warnings(baseline: Baseline, result: DiscoveryResult) -> list[str]:
    if ran_differently(baseline, result):
        return []  # the one note covers it: the limited parts follow from how they ran
    out: list[str] = []
    before = {r.area: r for r in baseline.coverage}
    for row in result.coverage:
        old = before.get(row.area)
        if row.state != "completed" and (old is None or old.state != row.state):
            how = "was only partly checked" if row.state == "limited" else "wasn't checked"
            reason = f" ({row.reason})" if row.reason else ""
            out.append(f"{row.label} {how} this time{reason}, so differences there may not show.")
    return out


def match_id(old: BaselineDevice, d: Device, salt: bytes) -> str:
    """The stable id of a "possibly the same device" pair: the old key and the device now."""
    return f"{old.key}>{device_subject(d, salt)}"


def compare(
    baseline: Baseline,
    result: DiscoveryResult,
    salt: bytes,
    matches: dict[str, MatchDecision] | None = None,
) -> Comparison:
    """Each item is New, Gone or Changed. Devices match by MAC key first, then by soft key
    ("possibly the same device"). Devices with nothing to match on aren't compared.

    matches: the user's answers to "possibly the same device". "same" counts the pair as one
    device; "different" shows it as one New and one Not seen item. Only how Compare groups
    things changes: the findings and their priorities never do."""
    matches = matches or {}
    by_device = _findings_by_device(result)
    out = Comparison(
        baseline_saved_at=baseline.saved_at,
        scan_at=result.finished_at,
        baseline_mode=baseline.mode,
        scan_mode=result.mode,
        ran_differently=ran_differently(baseline, result),
        warnings=_warnings(baseline, result),
    )
    rejected: list[tuple[Device, BaselineDevice, str]] = []
    unmatched = {d.key: d for d in baseline.devices}
    by_soft = {d.soft: d for d in baseline.devices if d.soft}

    current: list[tuple[Device, DeviceKeys]] = []
    for d in result.devices:
        keys = device_keys(d, salt)
        if keys.key is None:
            out.not_compared += 1
        else:
            current.append((d, keys))

    # Exact (MAC) matches first, so a soft key can't take a device another one matches exactly.
    pairs: list[tuple[Device, BaselineDevice, str]] = []
    rest: list[tuple[Device, DeviceKeys]] = []
    for d, keys in current:
        if keys.kind == "mac" and keys.key in unmatched:
            pairs.append((d, unmatched.pop(keys.key), "exact"))
        else:
            rest.append((d, keys))
    for d, keys in rest:
        old = by_soft.get(keys.soft) if keys.soft else None
        if old is not None and old.key in unmatched:
            unmatched.pop(old.key)
            mid = match_id(old, d, salt)
            if matches.get(mid) == "different":
                rejected.append((d, old, mid))  # the user says they're two devices
            else:
                pairs.append((d, old, "possible"))  # only the soft key matched
            continue
        _, label = _type(d)
        out.new.append(
            CompareItem(
                kind="device",
                status="new",
                label=label,
                maker=d.vendor,
                findings=[_bf(f) for f in by_device.get(d.id, [])],
                device_ref=d.id,
                subject=device_subject(d, salt),
            )
        )

    for d, old, how in pairs:
        findings = by_device.get(d.id, [])
        changes = _changes(old, d, findings, result, baseline)
        _, label = _type(d)
        pair_id = match_id(old, d, salt) if how == "possible" else None
        decision = matches.get(pair_id) if pair_id else None
        varied = identification_varied(old, d)
        band = _higher(old.band, _band(d)) if varied else _band(d)
        if changes:
            out.changed.append(
                CompareItem(
                    kind="device",
                    status="changed",
                    match=how,  # type: ignore[arg-type]
                    label=label,
                    maker=d.vendor,
                    changes=changes,
                    findings=[_bf(f) for f in findings],
                    device_ref=d.id,
                    subject=device_subject(d, salt),
                    match_id=pair_id,
                    decision=decision,
                    band=band,
                    identification_varied=varied,
                )
            )
        else:
            out.unchanged += 1
            if varied and how != "possible":  # a possible pair is listed (and noted) below
                out.varied.append(
                    CompareItem(
                        kind="device",
                        status="unchanged",
                        match=how,  # type: ignore[arg-type]
                        label=label,
                        maker=d.vendor,
                        findings=[_bf(f) for f in findings],
                        device_ref=d.id,
                        subject=device_subject(d, salt),
                        match_id=pair_id,
                        decision=decision,
                        band=band,
                        identification_varied=True,
                    )
                )
            if how == "possible":
                if decision is None:
                    out.unchanged_possible += 1
                out.possible.append(
                    CompareItem(
                        kind="device",
                        status="unchanged",
                        match="possible",
                        label=label,
                        maker=d.vendor,
                        findings=[_bf(f) for f in findings],
                        device_ref=d.id,
                        subject=device_subject(d, salt),
                        match_id=pair_id,
                        decision=decision,
                        band=band,
                        identification_varied=varied,
                    )
                )

    # Pairs the user said are two different devices: one New, one Not seen this time.
    for d, old, mid in rejected:
        _, label = _type(d)
        out.new.append(
            CompareItem(
                kind="device",
                status="new",
                label=label,
                maker=d.vendor,
                findings=[_bf(f) for f in by_device.get(d.id, [])],
                device_ref=d.id,
                subject=device_subject(d, salt),
                match_id=mid,
                decision="different",
            )
        )
        out.gone.append(
            CompareItem(
                kind="device",
                status="gone",
                label=old.type_label,
                findings=old.findings,
                subject=f"device:{old.key}",
                match_id=mid,
                decision="different",
            )
        )

    for old in unmatched.values():
        out.gone.append(
            CompareItem(
                kind="device",
                status="gone",
                label=old.type_label,
                findings=old.findings,
                subject=f"device:{old.key}",
            )
        )

    # Flagged nearby items: only an exact key can match.
    now_nearby = {i.match_key: i for i in result.nearby_items if i.match_key}
    old_nearby = {n.key: n for n in baseline.nearby}
    for key, item in now_nearby.items():
        found = [_bf(nf) for nf in result.findings if nf.nearby_ref == item.ref]
        old_n = old_nearby.get(key)
        now_rules = {b.rule_id for b in found}
        old_rules = {b.rule_id for b in old_n.findings} if old_n else set()
        if old_n is None:
            out.new.append(
                CompareItem(
                    kind="nearby",
                    status="new",
                    label=NEARBY_LABELS[item.kind],
                    findings=found,
                    subject=key,
                )
            )
        elif now_rules != old_rules:
            changes = [f"New finding: {b.title}" for b in found if b.rule_id not in old_rules]
            changes += [
                f"No longer found: {b.title}" for b in old_n.findings if b.rule_id not in now_rules
            ]
            out.changed.append(
                CompareItem(
                    kind="nearby",
                    status="changed",
                    match="exact",
                    label=NEARBY_LABELS[item.kind],
                    changes=changes,
                    findings=found,
                    subject=key,
                )
            )
        else:
            out.unchanged += 1
    for key, old_n in old_nearby.items():
        if key not in now_nearby:
            out.gone.append(
                CompareItem(
                    kind="nearby",
                    status="gone",
                    label=NEARBY_LABELS[old_n.kind],
                    findings=old_n.findings,
                    subject=old_n.key,
                )
            )

    # Network-wide findings, by rule.
    now_net = {nf.rule_id: nf for nf in result.findings if nf.scope == "network"}
    old_net = {b.rule_id: b for b in baseline.network_findings}
    for rule_id, nf in now_net.items():
        if rule_id not in old_net:
            out.new.append(
                CompareItem(kind="network", status="new", label=nf.title, findings=[_bf(nf)])
            )
    for rule_id, old_f in old_net.items():
        if rule_id not in now_net and not _checked(rule_id, result):
            out.not_checked.append(old_f.title)
        elif rule_id not in now_net:
            out.gone.append(
                CompareItem(kind="network", status="gone", label=old_f.title, findings=[old_f])
            )
    return out
