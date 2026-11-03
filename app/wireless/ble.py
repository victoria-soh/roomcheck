"""Bluetooth (BLE) scan and classification. Listens to advertisements only; never connects.

Tracker signatures are taken from AirGuard by the SEEMOO lab, TU Darmstadt
(https://github.com/seemoo-lab/AirGuard, files under database/models/device/types/ and
DeviceManager.kt; Heinrich et al., "AirGuard - Protecting Android Users from Stalking Attacks
by Apple Find My Devices", ACM WiSec 2022):

- Apple Find My (company ID 0x004C): manufacturer data starting 0x12 (offline-finding type).
  Byte 2 is the status byte; (status & 0x30) >> 4 gives the device type: 0 Apple device,
  1 AirTag, 2 Find My accessory, 3 AirPods. Byte 1 == 0x19 (full 25-byte key) means the device
  is away from its owner ("overmature offline"); anything else means the owner is near.
- Google Find My Device network: service data under 0xFEAA. Bit 0 of the first byte set means
  the owner hasn't connected for over 4 hours. RoomCheck also requires the first byte to be the
  Find My frame type (0x40 or 0x41), so ordinary Eddystone beacons, which share 0xFEAA, are not
  mistaken for trackers. That check is RoomCheck's, not AirGuard's.
- Samsung SmartTag: service data under 0xFD5A with (byte0 & 0xF8) == 0x10. The low three bits
  give the state; 0b011 is "overmature offline" (separated).
- Tile: service 0xFEED. Chipolo: service 0xFE33 (separated if bit 0 of service-data byte 1 is
  set, for addresses starting at or below D8, as AirGuard does). Pebblebee: service 0xFA25.
  Tile and Pebblebee don't say whether the owner is near.

Other categories (earbuds, locks, phones) are hints from public company IDs, assigned service
UUIDs and names. They are counted, never stored.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable

from app.wireless.models import BleAdvert, BleClass, BleDevice
from app.wireless.privacy import SESSION_SALT, ble_ref
from app.wireless.wlanapi import WirelessError

log = logging.getLogger(__name__)

BLE_ROUNDS = 3
BLE_ROUND_SECONDS = 10.0  # 3 rounds of 10 s: the 30 s scan from PLAN.md

APPLE = 0x004C
MICROSOFT = 0x0006

UUID_FMDN = 0xFEAA
UUID_SMARTTAG = 0xFD5A
UUID_TILE = 0xFEED
UUID_CHIPOLO = 0xFE33
UUID_PEBBLEBEE = 0xFA25
UUID_FAST_PAIR = 0xFE2C
LE_AUDIO_UUIDS = {0x1844, 0x1845, 0x184E, 0x184F, 0x1850, 0x1853}
NUKI_UUIDS = {"a92ee100-5501-11e4-916c-0800200c9a66", "a92ee200-5501-11e4-916c-0800200c9a66"}

_BASE_UUID = re.compile(r"^0000([0-9a-f]{4})-0000-1000-8000-00805f9b34fb$")
_AUDIO_NAME = re.compile(
    r"buds|pods|headphone|headset|earphone|earbud|speaker|soundbar|\b(?:wf|wh)-|jbl|bose|beats",
    re.IGNORECASE,
)
_LOCK_NAME = re.compile(r"\block\b|nuki|yale|igloo|ttlock|smartlock|ultraloq", re.IGNORECASE)
_CAMERA_NAME = re.compile(r"(?:^|[^a-z])(?:ip)?cam(?:era)?(?:[^a-z]|$)|webcam", re.IGNORECASE)

CATEGORY_LABELS = {
    "tracker": "item trackers",
    "audio": "earbuds, headphones or speakers",
    "lock": "smart locks",
    "camera": "cameras",
    "phone_computer": "phones, tablets, watches or computers",
    "other": "other or unidentified devices",
}

_APPLE_TYPES = {
    0: ("apple_findmy_device", "Apple device in Find My offline mode", "phone_computer"),
    1: ("airtag", "Apple AirTag", "tracker"),
    2: ("findmy_accessory", "Find My accessory (a third-party tag or item)", "tracker"),
    3: ("airpods", "AirPods in Find My mode", "tracker"),
}


APPLE_PROXIMITY_PAIRING = 0x07  # AirPods and Beats, e.g. when the case is opened


def apple_types(data: bytes) -> list[int]:
    """Apple packs several (type, length, value) records into one advertisement, e.g. an
    iPhone's 0x10 "nearby" record next to others. Returns the record types, stopping at a
    record that runs past the end."""
    types = []
    i = 0
    while i + 2 <= len(data):
        if i + 2 + data[i + 1] > len(data):
            break
        types.append(data[i])
        i += 2 + data[i + 1]
    return types


def uuid16(uuid: str) -> int | None:
    m = _BASE_UUID.match(uuid.lower())
    return int(m.group(1), 16) if m else None


def _service_data(adv: BleAdvert, short: int) -> bytes | None:
    for k, v in adv.service_data.items():
        if uuid16(k) == short:
            return v
    return None


def _has_service(adv: BleAdvert, short: int) -> bool:
    return (
        any(uuid16(u) == short for u in adv.service_uuids) or _service_data(adv, short) is not None
    )


def classify(adv: BleAdvert) -> BleClass:
    apple = adv.manufacturer_data.get(APPLE)
    if apple and apple[0] == 0x12 and len(apple) >= 3:
        kind, label, category = _APPLE_TYPES[(apple[2] & 0x30) >> 4]
        return BleClass(kind=kind, label=label, category=category, separated=apple[1] == 0x19)  # type: ignore[arg-type]

    fmdn = _service_data(adv, UUID_FMDN)
    if fmdn and fmdn[0] in (0x40, 0x41):
        return BleClass(
            kind="google_fmdn",
            label="Google Find My Device tag",
            category="tracker",
            separated=bool(fmdn[0] & 0x01),
        )
    tag = _service_data(adv, UUID_SMARTTAG)
    if tag and (tag[0] & 0xF8) == 0x10:
        return BleClass(
            kind="smarttag",
            label="Samsung SmartTag",
            category="tracker",
            separated=(tag[0] & 0x07) == 0b011,
        )
    if _has_service(adv, UUID_TILE):
        return BleClass(kind="tile", label="Tile tracker", category="tracker", separated=None)
    if _has_service(adv, UUID_CHIPOLO):
        sd = _service_data(adv, UUID_CHIPOLO)
        separated: bool | None = None
        if sd and len(sd) >= 2 and adv.address[:2].upper() <= "D8":
            separated = bool(sd[1] & 0x01)
        return BleClass(
            kind="chipolo", label="Chipolo tracker", category="tracker", separated=separated
        )
    if _has_service(adv, UUID_PEBBLEBEE):
        return BleClass(
            kind="pebblebee", label="Pebblebee tracker", category="tracker", separated=None
        )

    if apple and APPLE_PROXIMITY_PAIRING in apple_types(apple):
        return BleClass(
            kind="apple_audio", label="Apple or Beats earbuds or headphones", category="audio"
        )
    if _has_service(adv, UUID_FAST_PAIR):
        return BleClass(
            kind="fast_pair", label="Earbuds, headphones or speaker (Fast Pair)", category="audio"
        )
    shorts = {uuid16(u) for u in adv.service_uuids}
    if shorts & LE_AUDIO_UUIDS:
        return BleClass(kind="le_audio", label="Bluetooth audio device", category="audio")
    lowered = {u.lower() for u in adv.service_uuids}
    if lowered & NUKI_UUIDS:
        return BleClass(kind="nuki", label="Nuki smart lock", category="lock")
    name = adv.name or ""
    if _LOCK_NAME.search(name):
        return BleClass(
            kind="lock_name", label="Possible smart lock (from its name)", category="lock"
        )
    if _CAMERA_NAME.search(name):
        return BleClass(
            kind="camera_name", label="Possible camera (from its name)", category="camera"
        )
    if _AUDIO_NAME.search(name):
        return BleClass(kind="audio_name", label="Audio device (from its name)", category="audio")
    if apple:
        return BleClass(
            kind="apple", label="Apple phone, tablet, watch or computer", category="phone_computer"
        )
    ms = adv.manufacturer_data.get(MICROSOFT)
    if ms and ms[0] == 0x01:
        return BleClass(kind="windows", label="Windows computer", category="phone_computer")
    return BleClass(kind="unknown", label="Unidentified Bluetooth device", category="other")


def aggregate(rounds: list[list[BleAdvert]], salt: bytes = SESSION_SALT) -> list[BleDevice]:
    """One record per address, with the strongest reading in each round it was heard in."""
    devices: dict[str, BleDevice] = {}
    for r, adverts in enumerate(rounds):
        for adv in adverts:
            addr = adv.address.upper()
            d = devices.get(addr)
            if d is None:
                devices[addr] = BleDevice(
                    ref=ble_ref(addr, salt),
                    address=addr,
                    name=adv.name,
                    cls=classify(adv),
                    round_rssi={r: adv.rssi_dbm},
                )
                continue
            d.round_rssi[r] = max(d.round_rssi.get(r, -127), adv.rssi_dbm)
            d.name = d.name or adv.name
            new = classify(adv)
            # Keep the most telling class: a tracker format beats a generic one.
            if d.cls.category != "tracker" and new.category == "tracker":
                d.cls = new
            elif d.cls.category == "tracker" and new.kind == d.cls.kind and new.separated:
                d.cls = new
    return list(devices.values())


# --- scanning --------------------------------------------------------------------------------


async def discover_round(seconds: float) -> list[BleAdvert]:
    from bleak import BleakScanner

    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    return [
        BleAdvert(
            address=device.address,
            name=adv.local_name or device.name,
            rssi_dbm=adv.rssi,
            manufacturer_data=dict(adv.manufacturer_data),
            service_uuids=list(adv.service_uuids),
            service_data=dict(adv.service_data),
        )
        for device, adv in found.values()
    ]


def is_bluetooth_unavailable(exc: BaseException) -> bool:
    """bleak raises these when Bluetooth is off, missing or can't scan."""
    try:
        from bleak.exc import BleakError
    except ImportError:  # pragma: no cover - bleak is a dependency
        return isinstance(exc, OSError)
    return isinstance(exc, BleakError | OSError)


async def scan_rounds_async(
    rounds: int = BLE_ROUNDS,
    seconds: float = BLE_ROUND_SECONDS,
    discover: Callable[[float], Awaitable[list[BleAdvert]]] = discover_round,
) -> list[list[BleAdvert]]:
    out: list[list[BleAdvert]] = []
    for _ in range(rounds):
        try:
            out.append(await discover(seconds))
        except Exception as e:
            if is_bluetooth_unavailable(e):
                log.info("Bluetooth scan failed: %r", e)
                raise WirelessError("bluetooth_off") from e
            raise
    return out


def scan_rounds(
    rounds: int = BLE_ROUNDS,
    seconds: float = BLE_ROUND_SECONDS,
    discover: Callable[[float], Awaitable[list[BleAdvert]]] = discover_round,
) -> list[list[BleAdvert]]:
    """Blocking wrapper, for a worker thread."""
    return asyncio.run(scan_rounds_async(rounds, seconds, discover))
