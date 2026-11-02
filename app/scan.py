"""One full check: Layer 1 discovery, then Layer 2 fingerprinting."""

from __future__ import annotations

from app.discovery.models import DiscoveryResult
from app.discovery.runner import default_collectors, run_discovery
from app.fingerprint.pipeline import fingerprint_devices
from app.scanner import Scanner


def run_scan(consent: bool, scanner: Scanner | None, duration_seconds: int) -> DiscoveryResult:
    result = run_discovery(
        "full" if consent else "passive", default_collectors(scanner, duration_seconds)
    )
    if result.network is None:
        return result
    checks, messages = fingerprint_devices(result.devices, consent=consent, scanner=scanner)
    result.checks += checks
    result.messages += messages
    return result
