"""One full check: Layer 1 discovery, Layer 2 fingerprinting, Layer 3 network checks and the
Layer 4 nearby check, then the rules engine's findings and room summary."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from app.checks.models import NetworkFacts
from app.checks.runner import run_network_checks
from app.discovery.messages import message_for
from app.discovery.models import CheckStatus, DiscoveryResult
from app.discovery.runner import default_collectors, run_discovery
from app.fingerprint.pipeline import fingerprint_devices
from app.rules.engine import RoomFacts, evaluate, summarise
from app.scanner import Scanner
from app.wireless import survey as nearby
from app.wireless.models import NearbySurvey

NearbyCollector = Callable[[], tuple[NearbySurvey, list[CheckStatus], list[str]]]


def run_scan(
    consent: bool,
    scanner: Scanner | None,
    duration_seconds: int,
    online: bool = True,
    *,
    include_nearby: bool = True,
    typed_room: str | None = None,
    nearby_fn: NearbyCollector = nearby.collect_nearby,
) -> DiscoveryResult:
    # The nearby check (about 30 s) runs alongside discovery, which mostly listens.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="nearby") as pool:
        pending: Future[tuple[NearbySurvey, list[CheckStatus], list[str]]] | None = (
            pool.submit(nearby_fn) if include_nearby else None
        )
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

        survey: NearbySurvey | None = None
        if pending is not None:
            survey, checks, messages = pending.result()
            wifi = result.network_facts.wifi if result.network_facts else None
            if wifi is None:
                from app.checks.wifi import connected_wifi

                wifi = connected_wifi()
            survey.room = nearby.room_network(wifi, typed_room)
            result.checks += checks + nearby.room_checks(survey)
            result.messages += messages
        else:
            result.checks += [
                CheckStatus(
                    name=n,
                    label=nearby.LABELS[n],
                    status="skipped",
                    reason=message_for("nearby_off"),
                )
                for n in ("nearby_wifi", "lookalike", "wps", "bluetooth")
            ]

    room = RoomFacts(
        devices=result.devices,
        network=result.network,
        net=result.network_facts or NetworkFacts(),
        checks=result.checks,
        nearby=survey,
    )
    result.findings = evaluate(room)
    result.summary = summarise(result.findings, result.checks)
    if survey is not None:
        result.nearby_items = nearby.flagged_items(survey, result.findings)
        result.nearby_heard = nearby.heard_counts(survey)
        result.room_network = survey.room.ssid if survey.room else None
    # The survey, with raw addresses, is dropped here: only flagged items were kept.
    return result
