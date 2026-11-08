"""Matching keys, so a later scan can be compared with the move-in scan. Pure functions.

Every key is a salted HMAC: the salt is fixed and kept in the encrypted baseline store, so the
same device gives the same key in every scan, but the key alone says nothing about the device.

- A device with a real (globally unique) MAC address is matched by that address: "mac:...".
- A device with a randomised (private) MAC gets a soft key from its hostname, the services it
  announced and its maker: "soft:...". A soft match is never a confident match; the comparison
  says "possibly the same device".
- A device with a private MAC and none of those has no stable key at all, and isn't compared.
- Flagged nearby items are keyed by their BSSID or Bluetooth address: "wifi:..." / "bluetooth:...".
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Literal

from app.discovery.models import Device

KEY_CHARS = 24


def _hmac(salt: bytes, text: str) -> str:
    return hmac.new(salt, text.encode(), hashlib.sha256).hexdigest()[:KEY_CHARS]


def _normalise_mac(mac: str) -> str:
    return "".join(c for c in mac.lower() if c in "0123456789abcdef")


@dataclass(frozen=True)
class DeviceKeys:
    key: str | None  # the device's matching key: the MAC key, else the soft key
    kind: Literal["mac", "soft", "none"]
    soft: str | None  # the soft key, for every device that has one


def soft_basis(device: Device) -> str | None:
    """Hostname, announced services and maker, normalised. None if there's nothing to use."""
    hosts = sorted({h.lower().rstrip(".") for h in device.hostnames if h})
    services = sorted({f"{s.kind}:{s.name.lower()}" for s in device.services})
    vendor = (device.vendor or "").lower()
    if not hosts and not services and not vendor:
        return None
    return f"h={','.join(hosts)};s={','.join(services)};v={vendor}"


def device_keys(device: Device, salt: bytes) -> DeviceKeys:
    basis = soft_basis(device)
    soft = f"soft:{_hmac(salt, basis)}" if basis else None
    if device.mac and not device.mac_is_random:
        return DeviceKeys(
            key=f"mac:{_hmac(salt, _normalise_mac(device.mac))}", kind="mac", soft=soft
        )
    if soft:
        return DeviceKeys(key=soft, kind="soft", soft=soft)
    return DeviceKeys(key=None, kind="none", soft=None)


def nearby_key(kind: Literal["wifi", "bluetooth"], address: str, salt: bytes) -> str:
    return f"{kind}:{_hmac(salt, _normalise_mac(address))}"


def device_subject(device: Device, salt: bytes) -> str:
    """What recognition answers and handover tasks attach to. A device without a stable key
    gets one for this scan only."""
    keys = device_keys(device, salt)
    return f"device:{keys.key}" if keys.key else f"device:scan:{device.id}"
