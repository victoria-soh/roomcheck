"""Run every Layer 1 collector at once, merge their observations, and record what ran.

Each collector fails on its own. A failure becomes a CheckStatus with a plain message;
the other collectors' results are still used.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.discovery import mdns, onvif, ssdp
from app.discovery.merge import detect_client_isolation, merge_observations
from app.discovery.messages import message_for
from app.discovery.models import (
    CheckStatus,
    Device,
    DiscoveryResult,
    NetworkInfo,
    Observation,
)
from app.discovery.netinfo import NoNetworkError, get_network_info
from app.scanner import Scanner, ScannerError

log = logging.getLogger(__name__)

Mode = Literal["full", "passive"]
DEFAULT_DURATION_SECONDS = 60
# The worker ends the sweep by its own budget and returns what it heard; the app waits this
# much longer for the reply, so it never gives up on a sweep that's still within its budget.
SWEEP_REPLY_MARGIN_SECONDS = 15.0
# Called as each collector finishes: its status and the number of devices seen so far.
CollectorDone = Callable[[CheckStatus, int], None]


@dataclass(frozen=True)
class Collector:
    name: str
    label: str  # plain words for the progress screen
    active: bool  # sends probes; needs the user's consent
    run: Callable[[NetworkInfo], list[Observation]]
    sweep: bool = False  # skipped on networks larger than /22


def _via_scanner(
    scanner: Scanner | None, job: str, params: dict[str, float], timeout: float
) -> Callable[[NetworkInfo], list[Observation]]:
    def run(_net: NetworkInfo) -> list[Observation]:
        if scanner is None:
            raise ScannerError("scanner_not_started")
        raw = scanner.run(job, params, timeout)
        return [Observation.model_validate(o) for o in raw or []]

    return run


def sweep_budget(duration_seconds: float, gap: float) -> float:
    """The sweep's own time limit: the listening window it runs inside (the listen step waits
    for that anyway), and never less than the gap plus time for two passes."""
    return min(90.0, max(gap + 25.0, float(duration_seconds)))


def default_collectors(
    scanner: Scanner | None, duration_seconds: float = DEFAULT_DURATION_SECONDS
) -> list[Collector]:
    gap = min(20.0, max(0.0, duration_seconds - 5))
    budget = sweep_budget(duration_seconds, gap)
    return [
        Collector(
            "passive_listen",
            "Listening for devices",
            active=False,
            run=_via_scanner(
                scanner,
                "passive_listen",
                {"duration_seconds": duration_seconds},
                duration_seconds + 30,
            ),
        ),
        Collector(
            "mdns",
            "Listening for devices that announce themselves",
            active=False,
            run=lambda net: mdns.browse(net, min(15.0, duration_seconds)),
        ),
        Collector(
            "arp_sweep",
            "Asking every address on this network to answer",
            active=True,
            sweep=True,
            run=_via_scanner(
                scanner,
                "arp_sweep",
                {"gap_seconds": gap, "budget_seconds": budget},
                budget + SWEEP_REPLY_MARGIN_SECONDS,
            ),
        ),
        Collector(
            "ssdp",
            "Asking devices on the network to identify themselves",
            active=True,
            run=ssdp.search,
        ),
        Collector(
            "onvif",
            "Sending a camera discovery request (ONVIF)",
            active=True,
            run=onvif.probe,
        ),
    ]


def _skipped(c: Collector, code: str) -> CheckStatus:
    return CheckStatus(name=c.name, label=c.label, status="skipped", reason=message_for(code))


def _run_one(c: Collector, net: NetworkInfo) -> tuple[CheckStatus, list[Observation]]:
    try:
        found = c.run(net)
    except ScannerError as e:
        return CheckStatus(
            name=c.name, label=c.label, status="failed", reason=message_for(e.code)
        ), []
    except Exception:
        log.exception("collector %s failed", c.name)
        return CheckStatus(
            name=c.name, label=c.label, status="failed", reason=message_for("internal")
        ), []
    return CheckStatus(name=c.name, label=c.label, status="ran", found=len(found)), found


def run_discovery(
    mode: Mode,
    collectors: Sequence[Collector],
    *,
    get_network: Callable[[], NetworkInfo] = get_network_info,
    clock: Callable[[], float] = time.monotonic,
    on_collector: CollectorDone | None = None,
) -> DiscoveryResult:
    started_at = datetime.now(UTC)
    start = clock()

    try:
        net = get_network()
    except NoNetworkError:
        return DiscoveryResult(
            started_at=started_at,
            finished_at=datetime.now(UTC),
            mode=mode,
            network=None,
            devices=[],
            checks=[_skipped(c, "no_network") for c in collectors],
            messages=[message_for("no_network")],
        )

    messages: list[str] = []
    statuses: dict[str, CheckStatus] = {}
    to_run: list[Collector] = []
    for c in collectors:
        if c.active and mode == "passive":
            statuses[c.name] = _skipped(c, "passive_mode")
        elif c.sweep and not net.sweep_allowed:
            statuses[c.name] = _skipped(c, "subnet_too_large")
            messages.append(message_for("subnet_too_large"))
        else:
            to_run.append(c)

    def merged(observations: list[Observation]) -> list[Device]:
        return merge_observations(
            observations,
            gateway_ip=net.gateway_ip,
            exclude_ips=[net.own_ip],
            exclude_macs=[net.own_mac] if net.own_mac else [],
        )

    found_by: dict[str, list[Observation]] = {}
    if to_run:
        with ThreadPoolExecutor(max_workers=len(to_run)) as pool:
            futures = {pool.submit(_run_one, c, net): c for c in to_run}
            for future in as_completed(futures):
                c = futures[future]
                statuses[c.name], found_by[c.name] = future.result()
                if on_collector is not None:
                    so_far = [o for f in found_by.values() for o in f]
                    on_collector(statuses[c.name], len(merged(so_far)))

    # Merged in collector order, whatever order they finished in.
    observations = [o for c in to_run for o in found_by[c.name]]
    devices = merged(observations)
    sweep_ran = any(c.sweep and statuses[c.name].status == "ran" for c in collectors)
    isolation = detect_client_isolation(
        devices,
        gateway_ip=net.gateway_ip,
        elapsed_seconds=clock() - start,
        sweep_ran=sweep_ran,
    )
    if isolation:
        messages.append(message_for("client_isolation"))

    return DiscoveryResult(
        started_at=started_at,
        finished_at=datetime.now(UTC),
        mode=mode,
        network=net,
        devices=devices,
        checks=[statuses[c.name] for c in collectors],
        client_isolation=isolation,
        messages=messages,
        observations=observations,
    )
