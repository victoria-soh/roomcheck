"""R-WIFI-ENC input: how the current Wi-Fi connection is encrypted. Local only, sends nothing.

Reads `netsh wlan show interfaces`. netsh labels are translated on non-English Windows; if the
labels aren't found the check reports that it couldn't read them rather than guessing.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.checks.models import WifiStatus

NETSH_TIMEOUT_SECONDS = 10


class WifiCheckError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def parse_netsh_interfaces(text: str) -> list[dict[str, str]]:
    """One dict per interface block, keyed by lower-cased label ("name", "state", ...)."""
    blocks: list[dict[str, str]] = []
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        if key == "name":
            blocks.append({})
        if blocks and key not in blocks[-1]:
            blocks[-1][key] = value.strip()
    return blocks


def status_for_interface(text: str, interface: str) -> WifiStatus | None:
    """The connected Wi-Fi interface matching `interface`, or None if it isn't Wi-Fi."""
    blocks = parse_netsh_interfaces(text)
    for b in blocks:
        if b.get("name", "").lower() != interface.lower():
            continue
        if b.get("state", "").lower() != "connected":
            return None
        if "authentication" not in b or "cipher" not in b:
            raise WifiCheckError("unreadable")
        return WifiStatus(
            interface=b["name"],
            ssid=b.get("ssid") or None,
            authentication=b["authentication"],
            cipher=b["cipher"],
        )
    if not blocks and sum(" : " in line for line in text.splitlines()) >= 3:
        raise WifiCheckError("unreadable")  # label/value lines, but no "Name": translated labels
    return None


def _netsh_path() -> Path:
    # Full path from SystemRoot, so a netsh.exe elsewhere on PATH is never run.
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "netsh.exe"


def current_wifi(interface: str) -> WifiStatus | None:
    netsh = _netsh_path()
    if not netsh.exists():
        raise WifiCheckError("no_wlan")
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argument list, no shell
            [str(netsh), "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=NETSH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise WifiCheckError("no_wlan") from e
    if proc.returncode != 0:
        raise WifiCheckError("no_wlan")  # e.g. the WLAN service isn't running
    return status_for_interface(proc.stdout, interface)


def is_weak(status: WifiStatus) -> bool:
    """Open (no password) or WEP: traffic on the air can be read."""
    auth = status.authentication.lower()
    cipher = status.cipher.lower()
    return auth in ("open", "shared") or cipher in ("wep", "none")
