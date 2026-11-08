"""Scan jobs. A check runs in a background thread (never on the server's event loop); the
scanning screen follows its live state over a WebSocket, or by polling GET /api/scans/{id}
if the WebSocket drops. Both give the same snapshot. Kept in memory only, never saved."""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from app.discovery.messages import message_for
from app.discovery.models import DiscoveryResult
from app.scan import STEPS, ScanCancelled, ScanProgress, SkipReason, Step, StepState

log = logging.getLogger(__name__)

JobState = Literal["running", "done", "failed", "cancelled"]
StepStatus = Literal["upcoming", "active", "done", "failed", "skipped"]
KEEP_JOBS = 5  # older finished jobs are forgotten


class ScanBusy(Exception):
    """A check is running, or a cancelled one is still winding down. One at a time."""

    def __init__(self, stopping: bool = False) -> None:
        super().__init__("stopping" if stopping else "running")
        self.stopping = stopping


class StepView(BaseModel):
    key: Step
    # upcoming, active, done, skipped, or failed: finished, but something in it didn't work
    status: StepStatus
    problems: list[str] = []  # plain messages; the rest of the check carried on
    reason: SkipReason | None = None  # why it was skipped
    # Live counts while it runs, from real data: {"devices": 3} or {"wifi": 12, "bluetooth": 4}
    detail: dict[str, int] | None = None


class ScanSnapshot(BaseModel):
    """Everything the scanning screen shows. No addresses or names, only counts and steps."""

    id: str
    state: JobState
    steps: list[StepView]
    current_step: Step | None  # the most recently started step that's still running
    current_index: int | None  # 1-based position of current_step
    total_steps: int  # tasks this check does: skipped ones don't count
    done_steps: int  # of those, finished (done or couldn't finish), for "2 of 4 tasks done"
    devices: int | None  # None until discovery has reported a count
    started_at: datetime
    elapsed_seconds: float
    last_update_at: datetime  # when the check last changed (heartbeats don't count)
    version: int  # goes up on every change
    result: DiscoveryResult | None = None  # only from GET, once done
    error: str | None = None  # plain words, if it failed or was cancelled
    # Cancelled, but its last tasks or the scanner worker's restart haven't finished yet. A new
    # check can start once this is False; the page says "Stopping…" until then.
    stopping: bool = False
    # Waiting for the previous check's scanner work to end before this one starts.
    preparing: bool = False


class ScanJob(ScanProgress):
    def __init__(self, job_id: str, clock: Callable[[], float] = time.monotonic) -> None:
        self.id = job_id
        self.state: JobState = "running"
        self.result: DiscoveryResult | None = None
        self.error: str | None = None
        self._clock = clock
        self._started = clock()
        self.started_at = datetime.now(UTC)
        self.last_update_at = self.started_at
        self._steps: dict[Step, StepState | None] = dict.fromkeys(STEPS)
        self._started_order: list[Step] = []  # steps in the order they started running
        self._problems: dict[Step, list[str]] = {s: [] for s in STEPS}
        # Steps a problem stopped while they ran. A note that arrives after a step finished (the
        # known-issues lookup, under services) leaves it Done, with the note under it.
        self._unfinished: set[Step] = set()
        self._devices: int | None = None
        self._reasons: dict[Step, SkipReason] = {}
        self._heard: dict[Step, dict[str, int]] = {}
        self.version = 0
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)
        self._cancel = threading.Event()
        self._finished = threading.Event()
        self._cleanup = threading.Event()  # cleared while the scanner worker restarts
        self._cleanup.set()
        self._returned = False  # the scan thread has returned
        self._preparing = False
        self.thread: threading.Thread | None = None

    # --- ScanProgress: called from the scan's own thread -----------------------------------

    def _touch(self) -> None:  # with the lock held
        self.version += 1
        self.last_update_at = datetime.now(UTC)
        self._changed.notify_all()

    def step(self, step: Step, state: StepState, reason: SkipReason | None = None) -> None:
        with self._lock:
            if self._steps[step] != state:
                self._steps[step] = state
                if state == "running":
                    self._started_order.append(step)
                if reason:
                    self._reasons[step] = reason
                self._touch()

    def heard(self, step: Step, counts: dict[str, int]) -> None:
        with self._lock:
            if counts and self._heard.get(step) != counts:  # only when a number changes
                self._heard[step] = dict(counts)
                self._touch()

    def devices(self, count: int) -> None:
        with self._lock:
            if count != self._devices:
                self._devices = count
                self._touch()

    def problem(self, text: str, step: Step | None = None) -> None:
        with self._lock:
            key = step or self._active_step() or STEPS[0]
            if all(text not in p for p in self._problems.values()):  # each message once
                self._problems[key].append(text)
                if self._steps[key] != "done":
                    self._unfinished.add(key)
                self._touch()

    def raise_if_cancelled(self) -> None:
        if self._cancel.is_set():
            raise ScanCancelled

    def preparing(self, on: bool) -> None:
        with self._lock:
            if self._preparing != on:
                self._preparing = on
                self._touch()

    # --- stopping ------------------------------------------------------------------------------

    def begin_cleanup(self) -> None:
        """The scanner worker is being restarted for this cancelled check."""
        with self._lock:
            self._cleanup.clear()
            self._touch()

    def end_cleanup(self) -> None:
        with self._lock:
            self._cleanup.set()
            self._touch()

    def returned(self) -> None:
        """Called by the scan thread as it returns, so followers hear that it has stopped."""
        with self._lock:
            self._returned = True
            self._touch()

    def wait_stopped(self, timeout: float) -> bool:
        """Block until the check has stopped completely (thread returned, worker restarted)."""
        with self._lock:
            return self._changed.wait_for(lambda: not self._winding_down(), timeout)

    # --- the job's outcome -----------------------------------------------------------------

    def finish(self, result: DiscoveryResult) -> None:
        with self._lock:
            if self.state != "running":
                return  # cancelled while finishing: the result is dropped
            self.result, self.state = result, "done"
            self._touch()
        self._finished.set()

    def fail(self, text: str) -> None:
        with self._lock:
            if self.state != "running":
                return
            self.error, self.state = text, "failed"
            self._touch()
        self._finished.set()

    def cancel(self) -> bool:
        """Stop following this check. Returns False if it had already ended."""
        self._cancel.set()
        with self._lock:
            if self.state != "running":
                return False
            self.state, self.error = "cancelled", message_for("scan_cancelled")
            self._touch()
        self._finished.set()
        return True

    @property
    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    def _winding_down(self) -> bool:  # with the lock held
        if self.state == "running":
            return False
        thread_busy = self.thread is not None and not self._returned and self.thread.is_alive()
        return thread_busy or not self._cleanup.is_set()

    @property
    def winding_down(self) -> bool:
        """Ended (usually cancelled), but the scan thread hasn't returned yet or the scanner
        worker is still restarting."""
        with self._lock:
            return self._winding_down()

    def wait(self, timeout: float | None = None) -> bool:
        return self._finished.wait(timeout)

    def wait_for_change(self, version: int, timeout: float) -> int:
        """Block (in a worker thread, never on the event loop) until the version moves on."""
        with self._lock:
            self._changed.wait_for(lambda: self.version != version, timeout)
            return self.version

    # --- the snapshot ------------------------------------------------------------------------

    def _active_step(self) -> Step | None:
        """The most recently started step that's still running (several can run at once)."""
        running = [s for s in self._started_order if self._steps[s] == "running"]
        return running[-1] if running else None

    def _status(self, step: Step) -> StepStatus:
        state = self._steps[step]
        if state == "running":
            return "active"
        if state == "done":
            return "failed" if step in self._unfinished else "done"
        if state == "skipped":
            return "skipped"
        return "upcoming"

    def _detail(self, step: Step) -> dict[str, int] | None:  # with the lock held
        if step == "listen" and self._devices is not None:
            return {"devices": self._devices}
        return dict(self._heard[step]) if step in self._heard else None

    def snapshot(self, with_result: bool = False) -> ScanSnapshot:
        with self._lock:
            current = self._active_step() if self.state == "running" else None
            return ScanSnapshot(
                id=self.id,
                state=self.state,
                steps=[
                    StepView(
                        key=s,
                        status=self._status(s),
                        problems=list(self._problems[s]),
                        reason=self._reasons.get(s),
                        detail=self._detail(s),
                    )
                    for s in STEPS
                ],
                current_step=current,
                current_index=STEPS.index(current) + 1 if current else None,
                total_steps=sum(1 for s in STEPS if self._steps[s] != "skipped"),
                done_steps=sum(1 for s in STEPS if self._steps[s] == "done"),
                devices=self._devices,
                started_at=self.started_at,
                elapsed_seconds=round(self._clock() - self._started, 1),
                last_update_at=self.last_update_at,
                version=self.version,
                result=self.result if with_result else None,
                error=self.error,
                stopping=self._winding_down(),
                preparing=self._preparing and self.state == "running",
            )


class ScanJobs:
    def __init__(self, keep: int = KEEP_JOBS) -> None:
        self._jobs: OrderedDict[str, ScanJob] = OrderedDict()
        self._keep = keep
        self._lock = threading.Lock()

    def busy(self) -> bool:
        """A check is running or still stopping."""
        with self._lock:
            return any(j.state == "running" or j.winding_down for j in self._jobs.values())

    def start(self, run: Callable[[ScanJob], DiscoveryResult]) -> ScanJob:
        """Run `run(job)` in a background thread. Raises ScanBusy if a check is running."""
        with self._lock:
            for j in self._jobs.values():
                if j.state == "running":
                    raise ScanBusy
                if j.winding_down:
                    raise ScanBusy(stopping=True)
            job = ScanJob(secrets.token_hex(8))
            self._jobs[job.id] = job
            while len(self._jobs) > self._keep:
                self._jobs.popitem(last=False)

        def target() -> None:
            try:
                try:
                    result = run(job)
                except ScanCancelled:
                    job.cancel()
                    return
                except Exception:
                    if job.cancel_requested:
                        return  # stopping the scanner worker makes its jobs fail; expected
                    log.exception("scan job failed")
                    job.fail(message_for("scan_failed"))
                    return
                job.finish(result)
            finally:
                job.returned()

        job.thread = threading.Thread(target=target, name=f"scan-{job.id}", daemon=True)
        job.thread.start()
        return job

    def get(self, job_id: str) -> ScanJob | None:
        with self._lock:
            return self._jobs.get(job_id)
