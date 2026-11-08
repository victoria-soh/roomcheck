"""Is this laptop ready for a check? The connected network, five quick readiness checks, and
which optional outside calls this build makes. Read-only: RoomCheck never changes Windows
settings. Used by the Start screen (GET /api/setup), and everything here stays on this laptop:
the network name is shown locally only and is never sent to the AI or anywhere else.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel

from app.config import Settings

log = logging.getLogger(__name__)

CheckName = Literal["wifi", "bluetooth", "location", "npcap", "nmap"]
ORDER: list[CheckName] = ["wifi", "bluetooth", "location", "npcap", "nmap"]


class SetupItem(BaseModel):
    name: CheckName
    ready: bool  # the Start screen words (Ready / Missing, how to fix) are in its strings file


class ConnectedNetwork(BaseModel):
    kind: Literal["wifi", "cable", "none"]
    name: str | None = None  # the Wi-Fi name, shown on this laptop only


class OutsideCalls(BaseModel):
    """The optional calls this build makes, so the privacy text can't drift from the app."""

    ai: bool  # AI explanations (Anthropic): only with an API key in .env
    known_issues: bool  # NIST's vulnerability database: product names only
    timestamp: str | None  # the timestamp service's host, e.g. freetsa.org: the hash only


class Setup(BaseModel):
    network: ConnectedNetwork
    items: list[SetupItem]
    all_ready: bool
    outside: OutsideCalls


# --- the checks ---------------------------------------------------------------------------------


def radio_states() -> dict[str, bool]:
    """Wi-Fi and Bluetooth radio on/off from Windows (WinRT Radios). Missing means no radio."""
    import asyncio

    from winrt.windows.devices.radios import Radio, RadioKind, RadioState

    async def read() -> dict[str, bool]:
        out: dict[str, bool] = {}
        for radio in await Radio.get_radios_async():
            kind = RadioKind(radio.kind)
            if kind in (RadioKind.WI_FI, RadioKind.BLUETOOTH):
                key = "wifi" if kind == RadioKind.WI_FI else "bluetooth"
                out[key] = out.get(key, False) or RadioState(radio.state) == RadioState.ON
        return out

    return asyncio.run(read())


def location_allowed() -> bool:
    """Windows Location for desktop apps (needed to list nearby Wi-Fi). Read from Windows' own
    privacy settings; "Deny" at any level means off."""
    import winreg

    store = (
        r"Software\Microsoft\Windows\CurrentVersion"
        r"\CapabilityAccessManager\ConsentStore\location"
    )
    places = [
        (winreg.HKEY_LOCAL_MACHINE, store),
        (winreg.HKEY_CURRENT_USER, store),
        (winreg.HKEY_CURRENT_USER, store + r"\NonPackaged"),
    ]
    for hive, path in places:
        try:
            with winreg.OpenKey(hive, path) as key:
                value, _ = winreg.QueryValueEx(key, "Value")
        except OSError:
            continue  # not set at this level
        if str(value).lower() == "deny":
            return False
    return True


def npcap_installed() -> bool:
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    return (system / "Npcap" / "wpcap.dll").is_file() or (system / "Npcap" / "Packet.dll").is_file()


def nmap_installed() -> bool:
    return shutil.which("nmap") is not None  # the same lookup the port check uses


def connected_network() -> ConnectedNetwork:
    from app.checks.wifi import connected_wifi
    from app.discovery.netinfo import NoNetworkError, get_network_info

    try:
        get_network_info()
    except NoNetworkError:
        return ConnectedNetwork(kind="none")
    except Exception:
        log.exception("couldn't read the network")
        return ConnectedNetwork(kind="none")
    wifi = connected_wifi()
    if wifi is not None and wifi.ssid:
        return ConnectedNetwork(kind="wifi", name=wifi.ssid)
    return ConnectedNetwork(kind="cable")


def _safe(check: Callable[[], bool]) -> bool:
    try:
        return check()
    except Exception:
        log.exception("readiness check failed")
        return False


def outside_calls(settings: Settings) -> OutsideCalls:
    host = urlparse(settings.tsa_url).hostname if settings.tsa_url else None
    return OutsideCalls(
        ai=settings.anthropic_api_key is not None,
        known_issues=True,  # lookups run whenever a check is online; an NVD key is optional
        timestamp=host,
    )


def check_setup(
    settings: Settings,
    *,
    radios: Callable[[], dict[str, bool]] = radio_states,
    location: Callable[[], bool] = location_allowed,
    npcap: Callable[[], bool] = npcap_installed,
    nmap: Callable[[], bool] = nmap_installed,
    network: Callable[[], ConnectedNetwork] = connected_network,
) -> Setup:
    on_windows = sys.platform == "win32"
    states: dict[str, bool] = {}
    if on_windows:
        try:
            states = radios()
        except Exception:
            log.exception("couldn't read the radios")
    ready = {
        "wifi": states.get("wifi", False),
        "bluetooth": states.get("bluetooth", False),
        "location": on_windows and _safe(location),
        "npcap": _safe(npcap),
        "nmap": _safe(nmap),
    }
    items = [SetupItem(name=n, ready=ready[n]) for n in ORDER]
    try:
        net = network()
    except Exception:
        log.exception("couldn't read the network")
        net = ConnectedNetwork(kind="none")
    return Setup(
        network=net,
        items=items,
        all_ready=all(i.ready for i in items),
        outside=outside_calls(settings),
    )
