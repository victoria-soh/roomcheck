"""One full check: Layer 1 discovery, Layer 2 fingerprinting, Layer 3 network checks and the
Layer 4 nearby check, then the rules engine's findings and room summary."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from functools import partial
from typing import Literal

from app.baseline.compare import assign_subjects
from app.baseline.models import BaselineFacts
from app.checks.models import NetworkFacts
from app.checks.runner import run_network_checks
from app.coverage import coverage
from app.discovery.messages import message_for
from app.discovery.models import CheckStatus, DiscoveryResult
from app.discovery.runner import default_collectors, run_discovery
from app.fingerprint.pipeline import fingerprint_devices
from app.rules.engine import RoomFacts, evaluate, summarise
from app.rules.models import StayType
from app.scanner import Scanner
from app.wireless import survey as nearby
from app.wireless.models import NearbySurvey

NearbyCollector = Callable[[], tuple[NearbySurvey, list[CheckStatus], list[str]]]

# The steps of a check, in the order they start (run_scan below), so tasks that run at the same
# time sit next to each other: listening and nearby start together, then services, the router
# and the results. The order never changes. The words for each are in the frontend's strings.
Step = Literal["listen", "nearby", "services", "router", "explain"]
STEPS: list[Step] = ["listen", "nearby", "services", "router", "explain"]
StepState = Literal["running", "done", "skipped"]
# Why a task was skipped: needs_permission (a listening-only check), no_network (not connected
# to a network), not_chosen (the user turned it off).
SkipReason = Literal["needs_permission", "no_network", "not_chosen"]


# How often a waiting check looks for a cancel, so Cancel takes effect within a second.
CANCEL_POLL_SECONDS = 0.2


class ScanCancelled(Exception):
    """The user cancelled the check. Raised at the next checkpoint between stages, or while
    waiting for a stage (see _await)."""


class ScanProgress:
    """Where a check has got to, for the scanning screen. This one ignores everything; the scan
    job API (app/jobs.py) records it. Problems are the same plain messages as in the result,
    tied to the step they happened in."""

    def step(self, step: Step, state: StepState, reason: SkipReason | None = None) -> None:
        pass

    def devices(self, count: int) -> None:
        pass

    def heard(self, step: Step, counts: dict[str, int]) -> None:
        """Live counts for a running task, e.g. {"wifi": 12} nearby. Real numbers only."""

    def problem(self, text: str, step: Step | None = None) -> None:
        pass

    def raise_if_cancelled(self) -> None:
        """Raises ScanCancelled once the user has cancelled. Called between stages."""

    def preparing(self, on: bool) -> None:
        """Waiting for the previous check's scanner work to end ("Finishing the previous
        check…") before this one starts."""

    def report(self, step: Step, checks: Iterable[CheckStatus], messages: Iterable[str]) -> None:
        """Failed checks and messages, as each part of the scan finishes. Skipped checks are
        the user's own choice (e.g. listen-only), not problems."""
        for c in checks:
            if c.status == "failed" and c.reason:
                self.problem(c.reason, step)
        for m in messages:
            self.problem(m, step)


def _await[T](progress: ScanProgress, future: Future[T]) -> T:
    """The future's result, checking for a cancel while waiting. A cancelled check returns at
    once; whatever was running carries on in its own thread and its result is dropped (the
    scanner worker's jobs are stopped by restarting the worker)."""
    while True:
        progress.raise_if_cancelled()
        try:
            return future.result(timeout=CANCEL_POLL_SECONDS)
        except FutureTimeout:
            continue


def _in_thread[T](
    progress: ScanProgress, fn: Callable[..., T], *args: object, **kwargs: object
) -> T:
    """Run one stage in a daemon thread and wait for it with _await."""
    future: Future[T] = Future()

    def run() -> None:
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as e:  # handed to the waiting thread
            future.set_exception(e)

    threading.Thread(target=run, name="scan-stage", daemon=True).start()
    return _await(progress, future)


def run_scan(
    consent: bool,
    scanner: Scanner | None,
    duration_seconds: int,
    online: bool = True,
    *,
    include_nearby: bool = True,
    typed_room: str | None = None,
    nearby_fn: NearbyCollector | None = None,
    progress: ScanProgress | None = None,
    baseline: BaselineFacts | None = None,
    match_salt: bytes | None = None,
    stay_type: StayType | None = None,
) -> DiscoveryResult:
    """match_salt: the baseline store's fixed salt, for stable matching keys and subjects.
    baseline: the move-in scan's keys, so rules can tell what's new since then."""
    progress = progress or ScanProgress()

    def collector_done(status: CheckStatus, devices: int) -> None:
        progress.devices(devices)
        progress.report("listen", [status], [])

    def nearby_heard(wifi: int | None, bluetooth: int | None) -> None:
        counts = {k: v for k, v in (("wifi", wifi), ("bluetooth", bluetooth)) if v is not None}
        progress.heard("nearby", counts)

    collect = nearby_fn or partial(nearby.collect_nearby, on_heard=nearby_heard)

    # The nearby check (about 30 s) runs alongside discovery, which mostly listens. Not a `with`
    # block: on a cancel, leaving it would wait for the survey to end.
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nearby")
    try:
        pending: Future[tuple[NearbySurvey, list[CheckStatus], list[str]]] | None = (
            pool.submit(collect) if include_nearby else None
        )
        progress.step("listen", "running")
        if not consent:  # known from the start, so it never sits at "Waiting"
            progress.step("services", "skipped", "needs_permission")
        if include_nearby:
            progress.step("nearby", "running")
        else:
            progress.step("nearby", "skipped", "not_chosen")
        result = _in_thread(
            progress,
            run_discovery,
            "full" if consent else "passive",
            default_collectors(scanner, duration_seconds),
            on_collector=collector_done,
        )
        progress.devices(len(result.devices))
        progress.report("listen", [], result.messages)
        progress.step("listen", "done")
        progress.raise_if_cancelled()
        if result.network is not None:
            # Asking devices which services they offer needs permission; the maker lookup and
            # the passive fingerprint run either way.
            if consent:
                progress.step("services", "running")
            checks, messages = _in_thread(
                progress, fingerprint_devices, result.devices, consent=consent, scanner=scanner
            )
            result.checks += checks
            result.messages += messages
            progress.report("services" if consent else "router", checks, messages)
            if consent:
                progress.step("services", "done")
            progress.raise_if_cancelled()
            progress.step("router", "running")
            facts, checks, messages = _in_thread(
                progress,
                run_network_checks,
                result,
                consent=consent,
                scanner=scanner,
                online=online,
            )
            result.network_facts = facts
            result.checks += checks
            result.messages += messages
            # The known-issues lookup is about the devices' models and runs only in a full check,
            # as the services step does: a note about it goes there, not under the router.
            lookup = [c for c in checks if c.name == "cve"]
            progress.report("router", [c for c in checks if c.name != "cve"], messages)
            unanswered = message_for("nvd_unavailable")
            for c in lookup:
                if c.reason and (c.status == "failed" or c.reason == unanswered):
                    progress.problem(c.reason, "services")
            progress.step("router", "done")
            progress.raise_if_cancelled()
        else:
            if consent:
                progress.step("services", "skipped", "no_network")
            progress.step("router", "skipped", "no_network")

        survey: NearbySurvey | None = None
        if pending is not None:
            survey, checks, messages = _await(progress, pending)
            wifi = result.network_facts.wifi if result.network_facts else None
            if wifi is None:
                from app.checks.wifi import connected_wifi

                wifi = connected_wifi()
            survey.room = nearby.room_network(wifi, typed_room)
            room_checks = nearby.room_checks(survey)
            result.checks += checks + room_checks
            result.messages += messages
            progress.report("nearby", checks + room_checks, messages)
            progress.step("nearby", "done")
            progress.raise_if_cancelled()
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
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    return finish_result(
        result, survey, baseline=baseline, match_salt=match_salt, stay_type=stay_type
    )


def finish_result(
    result: DiscoveryResult,
    survey: NearbySurvey | None,
    *,
    baseline: BaselineFacts | None = None,
    match_salt: bytes | None = None,
    stay_type: StayType | None = None,
) -> DiscoveryResult:
    """From collected facts to what the screens show: the rules engine's findings and summary,
    the flagged nearby items, coverage and stable subjects. Every check ends here, and the demo
    data (app/demo_data.py) is made by this same function."""
    room = RoomFacts(
        devices=result.devices,
        network=result.network,
        net=result.network_facts or NetworkFacts(),
        checks=result.checks,
        nearby=survey,
        baseline=baseline,
        stay=stay_type,
    )
    result.stay_type = stay_type
    result.findings = evaluate(room)
    result.summary = summarise(result.findings, result.checks)
    if survey is not None:
        result.nearby_items = nearby.flagged_items(survey, result.findings, match_salt)
        result.nearby_heard = nearby.heard_counts(survey)
        result.room_network = survey.room.ssid if survey.room else None
    result.coverage = coverage(result)
    if match_salt is not None:
        assign_subjects(result, match_salt)
    # The survey, with raw addresses, is dropped here: only flagged items were kept.
    return result
