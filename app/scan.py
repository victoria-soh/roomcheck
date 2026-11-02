"""One full check: Layer 1 discovery, Layer 2 fingerprinting, Layer 3 network checks, then
the rules engine's findings and room summary."""

from __future__ import annotations

from app.checks.models import NetworkFacts
from app.checks.runner import run_network_checks
from app.discovery.models import DiscoveryResult
from app.discovery.runner import default_collectors, run_discovery
from app.fingerprint.pipeline import fingerprint_devices
from app.rules.engine import RoomFacts, evaluate, summarise
from app.scanner import Scanner


def run_scan(
    consent: bool, scanner: Scanner | None, duration_seconds: int, online: bool = True
) -> DiscoveryResult:
    result = run_discovery(
        "full" if consent else "passive", default_collectors(scanner, duration_seconds)
    )
    if result.network is not None:
        checks, messages = fingerprint_devices(result.devices, consent=consent, scanner=scanner)
        result.checks += checks
        result.messages += messages
        facts, checks, messages = run_network_checks(
            result, consent=consent, scanner=scanner, online=online
        )
        result.network_facts = facts
        result.checks += checks
        result.messages += messages
    room = RoomFacts(
        devices=result.devices,
        network=result.network,
        net=result.network_facts or NetworkFacts(),
        checks=result.checks,
    )
    result.findings = evaluate(room)
    result.summary = summarise(result.findings, result.checks)
    return result
