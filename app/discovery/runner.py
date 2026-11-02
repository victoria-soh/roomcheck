"""Run every Layer 1 collector at once, merge their observations, and record what ran.

Each collector fails on its own. A failure becomes a CheckStatus with a plain message;
the other collectors' results are still used.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.discovery import mdns, onvif, ssdp
from app.discovery.merge import detect_client_isolation, merge_observations
from app.discovery.messages import message_for
from app.discovery.models import CheckStatus, DiscoveryResult, NetworkInfo, Observation
from app.discovery.netinfo import NoNetworkError, get_network_info
from app.scanner import Scanner, ScannerError

log = logging.getLogger(__name__)

Mode = Literal["full", "passive"]
DEFAULT_DURATION_SECONDS = 60


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
            raise ScannerError("scanner_unavailable")
        raw = scanner.run(job, params, timeout)
        return [Observation.model_validate(o) for o in raw or []]

    return run


def default_collectors(
    scanner: Scanner | None, duration_seconds: float = DEFAULT_DURATION_SECONDS
) -> list[Collector]:
    gap = min(20.0, max(0.0, duration_seconds - 5))
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
            run=_via_scanner(scanner, "arp_sweep", {"gap_seconds": gap}, gap + 30),
        ),
        Collector(
            "ssdp",
            "Asking smart devices to identify themselves",
            active=True,
            run=ssdp.search,
        ),
        Collector(
            "onvif",
            "Asking cameras to identify themselves",
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

    observations: list[Observation] = []
    if to_run:
        with ThreadPoolExecutor(max_workers=len(to_run)) as pool:
            for c, (status, found) in zip(
                to_run, pool.map(lambda c: _run_one(c, net), to_run), strict=True
            ):
                statuses[c.name] = status
                observations.extend(found)

    devices = merge_observations(
        observations,
        gateway_ip=net.gateway_ip,
        exclude_ips=[net.own_ip],
        exclude_macs=[net.own_mac] if net.own_mac else [],
    )
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
