"""Signal-strength "warmer/colder" locator for one flagged nearby item.

The user walks slowly round the room holding the laptop; each new reading is smoothed with a
rolling median of the last 5 and compared with a few readings earlier. Locating devices from
signal strength as the user walks follows Lumos (Sharma et al., USENIX Security 2022).

Safeguards (docs/original-plan.md): it only accepts refs from the latest nearby check's flagged
items, shows signal strength only, never stores locations and keeps no history: the readings live in
this object and are gone when the session ends.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal

from pydantic import BaseModel

from app.discovery.messages import message_for
from app.wireless import wlanapi
from app.wireless.privacy import SESSION_SALT, ble_ref, wifi_ref
from app.wireless.wlanapi import WirelessError

WINDOW = 5
UNSTABLE_SPREAD_DB = 15  # max - min over the window; starting value, tune on test devices
TREND_DB = 3  # change in the smoothed value needed to say warmer or colder
MIN_DBM, MAX_DBM = -100, -30
BLE_SILENCE_SECONDS = 3.0
MAX_SESSION_SECONDS = 600

Kind = Literal["wifi", "bluetooth"]
Trend = Literal["warmer", "colder", "same"]


class LocatorTarget(BaseModel):
    ref: str
    kind: Kind
    label: str


class LocatorReading(BaseModel):
    ref: str
    heard: bool
    raw_dbm: int | None = None
    smoothed_dbm: float | None = None
    level: float | None = None  # 0..1 for the bar
    trend: Trend | None = None  # None while starting, when lost, or when unstable
    unstable: bool = False
    message: str | None = None
    note: str | None = None  # standing note, e.g. Wi-Fi updates slowly


class Smoother:
    """Rolling median of the last `window` readings, with a spread check and a trend."""

    def __init__(self, ref: str, kind: Kind, window: int = WINDOW) -> None:
        self.ref = ref
        self.kind = kind
        self.raw: deque[int] = deque(maxlen=window)
        self.history: deque[float] = deque(maxlen=8)
        # Compare with a few readings ago: Bluetooth readings come several times a second,
        # Wi-Fi ones once per scan, and the median already smooths over the last five.
        self.lag = 3 if kind == "bluetooth" else 2
        self.note = message_for("locator_wifi_slow") if kind == "wifi" else None

    def add(self, rssi: int | None) -> LocatorReading:
        if rssi is None:
            last = self.history[-1] if self.history else None
            return LocatorReading(
                ref=self.ref,
                heard=False,
                smoothed_dbm=last,
                level=_level(last) if last is not None else None,
                message=message_for("locator_lost"),
                note=self.note,
            )
        self.raw.append(rssi)
        smoothed = float(statistics.median(self.raw))
        self.history.append(smoothed)
        reading = LocatorReading(
            ref=self.ref,
            heard=True,
            raw_dbm=rssi,
            smoothed_dbm=smoothed,
            level=_level(smoothed),
            note=self.note,
        )
        if len(self.raw) >= 3 and max(self.raw) - min(self.raw) > UNSTABLE_SPREAD_DB:
            # Show the raw bar and switch the warmer/colder words off.
            reading.unstable = True
            reading.level = _level(rssi)
            reading.message = message_for("signal_unstable")
            return reading
        if len(self.history) <= self.lag or len(self.raw) < 3:
            reading.message = message_for("locator_starting")
            return reading
        delta = smoothed - self.history[-1 - self.lag]
        reading.trend = (
            "warmer" if delta >= TREND_DB else "colder" if delta <= -TREND_DB else "same"
        )
        return reading


def _level(dbm: float) -> float:
    return round(min(1.0, max(0.0, (dbm - MIN_DBM) / (MAX_DBM - MIN_DBM))), 3)


async def locate(
    target: LocatorTarget,
    source: AsyncIterator[int | None],
    *,
    max_seconds: float = MAX_SESSION_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> AsyncIterator[LocatorReading]:
    smoother = Smoother(target.ref, target.kind)
    deadline = clock() + max_seconds
    async for rssi in source:
        yield smoother.add(rssi)
        if clock() >= deadline:
            return


# --- reading sources ---------------------------------------------------------------------------


async def ble_source(
    ref: str,
    salt: bytes = SESSION_SALT,
    *,
    scanner_factory: Callable[..., Any] | None = None,
    silence: float = BLE_SILENCE_SECONDS,
) -> AsyncIterator[int | None]:
    """Every advertisement from the flagged device (several a second), or None after silence."""
    if scanner_factory is None:
        from bleak import BleakScanner

        scanner_factory = BleakScanner
    queue: asyncio.Queue[int] = asyncio.Queue()

    def on_advert(device: Any, adv: Any) -> None:
        if ble_ref(device.address, salt) == ref:
            queue.put_nowait(adv.rssi)

    from app.wireless.ble import is_bluetooth_unavailable

    try:
        scanner = scanner_factory(detection_callback=on_advert, scanning_mode="active")
        await scanner.start()
    except Exception as e:
        if is_bluetooth_unavailable(e):
            raise WirelessError("bluetooth_off") from e
        raise
    try:
        while True:
            try:
                yield await asyncio.wait_for(queue.get(), timeout=silence)
            except TimeoutError:
                yield None
    finally:
        await scanner.stop()


async def wifi_source(
    ref: str,
    salt: bytes = SESSION_SALT,
    *,
    api_factory: Callable[[], wlanapi.WlanApi] = wlanapi.WlanApi,
    settle: float = wlanapi.SCAN_SETTLE_SECONDS,
) -> AsyncIterator[int | None]:
    """One reading per Wi-Fi scan (every few seconds). Needs the WLAN API: netsh can't scan."""
    try:
        api = api_factory()
        api.__enter__()
    except WirelessError as e:
        code = "locator_wifi_unavailable" if e.code == "wlanapi_unavailable" else e.code
        raise WirelessError(code) from e
    try:
        iface = wlanapi.pick_interface(api.interfaces())
        last_ts: int | None = None
        while True:
            readings = await asyncio.to_thread(wlanapi.read_once, api, iface, settle)
            match = next((b for b in readings if wifi_ref(b.bssid, salt) == ref), None)
            if match is None or match.host_timestamp == last_ts:
                yield None  # not heard in this scan (a cached entry doesn't count)
            else:
                last_ts = match.host_timestamp
                yield match.rssi_dbm
    finally:
        api.__exit__(None, None, None)


def source_for(target: LocatorTarget) -> AsyncIterator[int | None]:
    return ble_source(target.ref) if target.kind == "bluetooth" else wifi_source(target.ref)


def bar(reading: LocatorReading, width: int = 20) -> str:
    """A text bar for the CLI: [########------------] -58 dBm  warmer"""
    filled = round((reading.level or 0.0) * width)
    dbm = f"{reading.smoothed_dbm:.0f} dBm" if reading.smoothed_dbm is not None else "   -   "
    if reading.unstable and reading.raw_dbm is not None:
        dbm = f"{reading.raw_dbm} dBm (raw)"
    word = {"warmer": "WARMER", "colder": "colder", "same": "about the same"}.get(
        reading.trend or "", ""
    )
    return f"[{'#' * filled}{'-' * (width - filled)}] {dbm:>14}  {word}"
