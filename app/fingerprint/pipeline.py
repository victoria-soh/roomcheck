"""Layer 2: vendor lookup for every device; port and identity checks only with consent;
then a scored type guess for every device.

Each step fails on its own. A device that hangs or sends junk is "partly identified" and is
scored from whatever evidence was gathered.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from app.discovery.messages import message_for
from app.discovery.models import CheckStatus, Device
from app.fingerprint import probes
from app.fingerprint.facts import device_facts
from app.fingerprint.models import HttpIdentity, Identity, RtspIdentity, UpnpIdentity
from app.fingerprint.oui import lookup_vendor
from app.fingerprint.scoring import Identification, fingerprint
from app.scanner import Scanner, ScannerError

log = logging.getLogger(__name__)

PORT_SCAN_TIMEOUT_SECONDS = 300
MAX_PROBE_WORKERS = 16

LABELS = {
    "vendor_lookup": "Looking up who made each device",
    "port_check": "Checking which services each device offers",
    "identity_check": "Reading device names and models",
}


@dataclass(frozen=True)
class Probes:
    http: Callable[[str, int], HttpIdentity] = probes.http_identity
    rtsp: Callable[[str, int], RtspIdentity | None] = probes.rtsp_identity
    upnp: Callable[[str, str], UpnpIdentity | None] = probes.upnp_identity


@dataclass
class _Task:
    device: Device
    kind: str  # "http", "rtsp" or "upnp"
    target: Any  # port number, or the description URL


_KIND_WORDS = {"http": "Web page", "rtsp": "Video stream check", "upnp": "Device description"}


def _status(name: str, status: str, code: str | None = None, found: int = 0) -> CheckStatus:
    return CheckStatus(
        name=name,
        label=LABELS[name],
        status=status,  # type: ignore[arg-type]
        reason=message_for(code) if code else None,
        found=found,
    )


def _run_port_check(
    scanner: Scanner | None,
) -> tuple[CheckStatus, dict[str, tuple[list[int], bool]] | None]:
    try:
        if scanner is None:
            raise ScannerError("scanner_unavailable")
        raw = scanner.run("port_scan", {}, PORT_SCAN_TIMEOUT_SECONDS) or []
    except ScannerError as e:
        status = "skipped" if e.code == "nmap_missing" else "failed"
        return _status("port_check", status, e.code), None
    results = {
        str(r["ip"]): ([int(p) for p in r.get("open_ports", [])], bool(r.get("complete")))
        for r in raw
        if isinstance(r, dict) and "ip" in r
    }
    if not results:
        return _status("port_check", "ran", "no_swept_hosts"), results
    return _status("port_check", "ran", found=len(results)), results


def _tasks_for(device: Device, open_ports: list[int] | None) -> list[_Task]:
    if not device.ip:
        return []
    tasks = []
    for port in open_ports or []:
        if port in probes.HTTP_PORTS:
            tasks.append(_Task(device, "http", port))
        if port in probes.RTSP_PORTS:
            tasks.append(_Task(device, "rtsp", port))
    locations = [
        s.detail["location"]
        for s in device.services
        if s.kind == "ssdp" and probes.location_allowed(s.detail.get("location", ""), device.ip)
    ]
    if locations:
        tasks.append(_Task(device, "upnp", sorted(set(locations))[0]))
    return tasks


def _run_task(task: _Task, p: Probes) -> tuple[_Task, object]:
    ip = task.device.ip
    assert ip is not None
    try:
        if task.kind == "http":
            return task, p.http(ip, task.target)
        if task.kind == "rtsp":
            return task, p.rtsp(ip, task.target)
        return task, p.upnp(task.target, ip)
    except probes.ProbeError as e:
        return task, e
    except Exception:
        log.exception("identity check %s on %s failed", task.kind, ip)
        return task, probes.ProbeError("sent a reply we couldn't read")


def _problem(task: _Task, err: probes.ProbeError) -> str:
    where = f" on port {task.target}" if task.kind != "upnp" else ""
    return f"{_KIND_WORDS[task.kind]}{where} {err}"


def fingerprint_devices(
    devices: list[Device],
    *,
    consent: bool,
    scanner: Scanner | None,
    probe_fns: Probes | None = None,
) -> tuple[list[CheckStatus], list[str]]:
    """Fill in vendor, identity and fingerprint on each device. Returns (checks, messages)."""
    p = probe_fns or Probes()
    for d in devices:
        d.vendor = lookup_vendor(d.mac)
    checks = [_status("vendor_lookup", "ran", found=sum(1 for d in devices if d.vendor))]

    if not consent:
        checks += [
            _status("port_check", "skipped", "passive_mode"),
            _status("identity_check", "skipped", "passive_mode"),
        ]
        for d in devices:
            d.fingerprint = fingerprint(device_facts(d), "passive")
        return checks, []

    port_status, port_results = _run_port_check(scanner)
    checks.append(port_status)

    tasks: list[_Task] = []
    for d in devices:
        ports = port_results.get(d.ip) if port_results is not None and d.ip else None
        d.identity = Identity(
            open_ports=ports[0] if ports else None,
            ports_complete=ports[1] if ports else True,
        )
        if ports and not ports[1]:
            d.identity.problems.append("Service check didn't finish in time")
        tasks += _tasks_for(d, ports[0] if ports else None)

    with ThreadPoolExecutor(max_workers=MAX_PROBE_WORKERS) as pool:
        outcomes = list(pool.map(lambda t: _run_task(t, p), tasks))
    for task, outcome in outcomes:
        ident = task.device.identity
        assert ident is not None
        if isinstance(outcome, probes.TlsMismatchError):
            if probes.TLS_MISMATCH_NOTE not in ident.notes:
                ident.notes.append(probes.TLS_MISMATCH_NOTE)
        elif isinstance(outcome, probes.ProbeError):
            ident.problems.append(_problem(task, outcome))
        elif isinstance(outcome, HttpIdentity):
            ident.http.append(outcome)
        elif isinstance(outcome, RtspIdentity):
            ident.rtsp.append(outcome)
        elif isinstance(outcome, UpnpIdentity):
            ident.upnp = outcome

    identified = sum(
        1 for d in devices if d.identity and (d.identity.http or d.identity.rtsp or d.identity.upnp)
    )
    checks.append(_status("identity_check", "ran", found=identified))

    partly = False
    for d in devices:
        ident = d.identity
        assert ident is not None
        checked = ident.open_ports is not None or any(t.device is d for t in tasks)
        level: Identification = "passive"
        if checked:
            level = "partial" if ident.problems else "full"
        partly = partly or level == "partial"
        d.fingerprint = fingerprint(device_facts(d), level)
    return checks, [message_for("partly_identified")] if partly else []
