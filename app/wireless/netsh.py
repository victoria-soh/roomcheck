"""Fallback Wi-Fi survey: parse `netsh wlan show networks mode=bssid`.

Used only when the WLAN API can't be loaded. netsh shows no information elements, so WPS
can't be read this way, and it reports signal as a percentage (converted to approximate dBm).
netsh labels are translated on non-English Windows; unrecognised output is reported as
unreadable rather than guessed at.
"""

from __future__ import annotations

import re
import subprocess
import time
from collections.abc import Callable

from app.checks.wifi import _netsh_path
from app.discovery.netinfo import normalize_mac
from app.wireless.ie import security_from_netsh
from app.wireless.models import BssReading
from app.wireless.radio import mhz_from_channel, percent_to_dbm
from app.wireless.wlanapi import SCAN_INTERVAL_SECONDS, SCAN_ROUNDS, WirelessError

NETSH_TIMEOUT_SECONDS = 15

_SSID_KEY = re.compile(r"^ssid \d+$")
_BSSID_KEY = re.compile(r"^bssid \d+$")


def parse_networks(text: str) -> list[BssReading]:
    """One reading per BSSID. Raises WirelessError for location-off, no-Wi-Fi or unreadable text."""
    readings: list[BssReading] = []
    ssid: str | None = None
    auth = cipher = ""
    current: dict[str, str] | None = None
    blocks = 0

    def flush() -> None:
        if current is None or "bssid" not in current:
            return
        try:
            bssid = normalize_mac(current["bssid"])
        except ValueError:
            return
        pct = re.match(r"\d+", current.get("signal", ""))
        channel_m = re.match(r"\d+", current.get("channel", ""))
        channel = int(channel_m.group()) if channel_m else None
        readings.append(
            BssReading(
                bssid=bssid,
                ssid=ssid,
                rssi_dbm=percent_to_dbm(int(pct.group())) if pct else -100,
                frequency_mhz=mhz_from_channel(channel, current.get("band")) if channel else None,
                channel=channel,
                security=security_from_netsh(auth, cipher),
                wps=None,
                wps_known=False,
            )
        )

    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip()
        if _SSID_KEY.match(key):
            flush()
            current = None
            blocks += 1
            ssid = value or None
            auth = cipher = ""
        elif _BSSID_KEY.match(key):
            flush()
            current = {"bssid": value}
        elif key == "authentication":
            auth = value
        elif key == "encryption":
            cipher = value
        elif current is not None and key in ("signal", "channel", "band"):
            current[key] = value
    flush()

    if not blocks:
        lower = text.lower()
        if "location" in lower:
            raise WirelessError("location_off")
        if "no wireless interface" in lower or "wlansvc" in lower or "powered down" in lower:
            raise WirelessError("no_wifi")
        if re.search(r"\b0 networks\b", lower) or not text.strip():
            return []
        raise WirelessError("nearby_unreadable")
    if blocks and not readings:
        raise WirelessError("nearby_unreadable")  # SSIDs but no BSSID lines: translated labels
    return readings


def show_networks() -> str:
    netsh = _netsh_path()
    if not netsh.exists():
        raise WirelessError("no_wifi")
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argument list, no shell
            [str(netsh), "wlan", "show", "networks", "mode=bssid"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=NETSH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise WirelessError("no_wifi") from e
    return proc.stdout + proc.stderr


def survey_rounds(
    rounds: int = SCAN_ROUNDS,
    interval: float = SCAN_INTERVAL_SECONDS,
    *,
    run: Callable[[], str] = show_networks,
    sleep: Callable[[float], None] = time.sleep,
) -> list[list[BssReading]]:
    out: list[list[BssReading]] = []
    for r in range(rounds):
        if r:
            sleep(interval)
        out.append(parse_networks(run()))
    return out
