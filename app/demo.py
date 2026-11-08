"""`python -m app --demo`: the dashboard on made-up data, with no scans, probes or outside calls.

Every check is built by RoomCheck's own pipeline from the made-up raw inputs in app/demo_data.py
(the same inputs as the screenshots and the page tests: 192.0.2.x addresses, "Example-Home",
made-up makers and CVE). Nothing touches the network or the radios:

- No scanner worker is started. A check replays the scanning steps on a short timer, then shows
  the demo check: with permission, the full one; without, the listening-only one.
- The setup strip shows a made-up laptop, connected to "Example-Home", all ready.
- Saved data goes to a temporary folder, never the real store in %LOCALAPPDATA%\\RoomCheck. It
  starts with a demo move-in scan, so Compare has something to compare.
- Reports are built locally, with no trusted timestamp, in that temporary folder.
- Recheck and the locator use made-up readings.
- AI explanations stay off unless an Anthropic API key is set (then they're real calls, as the
  user chose). Known-issue lookups never run: the demo's known issue is made up.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import threading
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import config, demo_data
from app.baseline.store import BaselineStore
from app.discovery.models import CheckStatus, DiscoveryResult
from app.explain.service import explain
from app.handover.recheck import Collectors
from app.handover.session import HandoverSession
from app.rules.models import StayType
from app.scan import ScanProgress
from app.setup_check import ConnectedNetwork, OutsideCalls, Setup, SetupItem
from app.wireless.locator import LocatorTarget
from app.wireless.models import NearbySurvey

STEP_SECONDS = 0.8  # each scanning step, so the progress screen can be seen
BANNER = "Demo mode: made-up data, nothing is scanned"

_lock = threading.Lock()
_checks: dict[tuple[bool, StayType], DiscoveryResult] = {}


def check(consent: bool, stay: StayType) -> DiscoveryResult:
    """The demo check for this answer and stay type, built once by the pipeline."""
    with _lock:
        key = (consent, stay)
        if key not in _checks:
            _checks[key] = (
                demo_data.full_check(stay) if consent else demo_data.listening_check(stay)
            )
        return _checks[key].model_copy(deep=True)


def start(state: Any) -> None:
    """Set the app up for the demo: a temporary store with a demo move-in scan, a temporary
    report folder, and no scanner worker."""
    folder = Path(tempfile.mkdtemp(prefix="roomcheck-demo-"))
    state.demo = True
    state.demo_folder = folder
    state.scanner = None
    state.scanner_process = None
    state.report_dir = folder / "reports"
    state.report_dir.mkdir()
    session = HandoverSession(BaselineStore(folder / "demo.db", demo_data.DemoProtector()))
    session.salt = demo_data.SALT  # the demo's fixed salt: stable subjects and match keys
    session.save_baseline(demo_data._move_in(), now=demo_data.MOVE_IN_SAVED)
    state.handover = session


def stop(state: Any) -> None:
    folder: Path | None = getattr(state, "demo_folder", None)
    if folder is not None:
        shutil.rmtree(folder, ignore_errors=True)


def setup() -> Setup:
    """A made-up laptop: on "Example-Home", everything ready. The real network name, radios
    and installed tools aren't read."""
    settings = config.get_settings()
    return Setup(
        network=ConnectedNetwork(kind="wifi", name="Example-Home"),
        items=[
            SetupItem(name=name, ready=True)
            for name in ("wifi", "bluetooth", "location", "npcap", "nmap")
        ],
        all_ready=True,
        outside=OutsideCalls(
            ai=settings.anthropic_api_key is not None, known_issues=False, timestamp=None
        ),
    )


def run_check(consent: bool, stay: StayType, progress: ScanProgress) -> DiscoveryResult:
    """Replay the scanning steps on a timer, then return the demo check with its explanations."""

    def wait() -> None:
        end = time.monotonic() + STEP_SECONDS
        while time.monotonic() < end:
            progress.raise_if_cancelled()
            time.sleep(0.05)

    result = check(consent, stay)
    # Dated now, like a real check: after the demo move-in scan, so Compare reads naturally.
    result.finished_at = datetime.now(UTC)
    result.started_at = result.finished_at - (demo_data.CHECK_DONE - demo_data.CHECK_AT)
    progress.step("listen", "running")
    progress.step("nearby", "running")
    if not consent:
        progress.step("services", "skipped", "needs_permission")
    wait()
    progress.devices(len(result.devices))
    heard = result.nearby_heard
    if heard is not None:
        progress.heard(
            "nearby", {"wifi": heard.wifi_access_points, "bluetooth": heard.bluetooth_devices}
        )
    wait()
    progress.step("listen", "done")
    if consent:
        progress.step("services", "running")
        wait()
        progress.step("services", "done")
    progress.step("router", "running")
    wait()
    progress.step("router", "done")
    progress.step("nearby", "done")
    progress.step("explain", "running")
    online = config.get_settings().anthropic_api_key is not None  # AI only with a key
    result.explanations = explain(
        result.findings, result.devices, result.nearby_items, online=online
    )
    progress.step("explain", "done")
    progress.raise_if_cancelled()
    return result


def recheck_collectors(result: DiscoveryResult) -> Collectors:
    """Made-up rechecks: the host has turned WPS off, and the devices are as before."""

    def wifi(_typed: str | None) -> tuple[NearbySurvey, list[CheckStatus], list[str]]:
        fixed = demo_data.survey(wps=False, open_neighbour=True, hidden=True, tracker=False)
        return fixed, [], []

    def devices(_consent: bool) -> DiscoveryResult:
        return result.model_copy(deep=True)

    return Collectors(wifi=wifi, devices=devices)


async def locator_source(target: LocatorTarget) -> AsyncIterator[int | None]:
    """Made-up signal readings that get warmer, then colder, then warmer again."""
    levels = [-80, -76, -71, -66, -61, -57, -54, -58, -63, -60, -55, -51, -48]
    i = 0
    while True:
        yield levels[i % len(levels)]
        i += 1
        await asyncio.sleep(0.5)


def is_on(state: Any) -> bool:
    return bool(getattr(state, "demo", False))
