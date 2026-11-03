"""Windows Native Wi-Fi API (wlanapi.dll) through ctypes: list nearby access points.

Read-only. It asks Windows for a fresh scan (WlanScan) and reads the access points Windows
heard (WlanGetNetworkBssList). It never connects to, or sends anything to, any network.

Functions used: WlanOpenHandle, WlanEnumInterfaces, WlanScan, WlanGetNetworkBssList,
WlanFreeMemory, WlanCloseHandle. Structures follow wlanapi.h and windot11.h; their sizes are
checked by tests.
"""

from __future__ import annotations

import ctypes
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.discovery.netinfo import normalize_mac
from app.wireless.ie import parse_beacon_ies, ssid_from_bytes
from app.wireless.models import BssReading
from app.wireless.radio import channel_from_mhz

log = logging.getLogger(__name__)

CLIENT_VERSION = 2  # Windows Vista and later
DOT11_BSS_TYPE_ANY = 3

ERROR_SUCCESS = 0
ERROR_ACCESS_DENIED = 5
ERROR_INVALID_STATE = 5023
ERROR_SERVICE_NOT_ACTIVE = 1062
ERROR_NDIS_DOT11_POWER_STATE_INVALID = 0x80342002  # the Wi-Fi radio is switched off

INTERFACE_NOT_READY = 0
INTERFACE_CONNECTED = 1

SCAN_ROUNDS = 3
SCAN_INTERVAL_SECONDS = 10.0
SCAN_SETTLE_SECONDS = 4.0  # Windows finishes a scan within about 4 s


class WirelessError(Exception):
    """A nearby check couldn't run. `code` is a key into app.discovery.messages."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_uint8 * 8),
    ]


class WLAN_INTERFACE_INFO(ctypes.Structure):  # noqa: N801 - Windows names
    _fields_ = [
        ("InterfaceGuid", GUID),
        ("strInterfaceDescription", ctypes.c_wchar * 256),
        ("isState", ctypes.c_uint32),
    ]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):  # noqa: N801
    _fields_ = [
        ("dwNumberOfItems", ctypes.c_uint32),
        ("dwIndex", ctypes.c_uint32),
        ("InterfaceInfo", WLAN_INTERFACE_INFO * 1),
    ]


class DOT11_SSID(ctypes.Structure):  # noqa: N801
    _fields_ = [("uSSIDLength", ctypes.c_uint32), ("ucSSID", ctypes.c_uint8 * 32)]


class WLAN_RATE_SET(ctypes.Structure):  # noqa: N801
    _fields_ = [("uRateSetLength", ctypes.c_uint32), ("usRateSet", ctypes.c_uint16 * 126)]


class WLAN_BSS_ENTRY(ctypes.Structure):  # noqa: N801
    _fields_ = [
        ("dot11Ssid", DOT11_SSID),
        ("uPhyId", ctypes.c_uint32),
        ("dot11Bssid", ctypes.c_uint8 * 6),
        ("dot11BssType", ctypes.c_int32),
        ("dot11BssPhyType", ctypes.c_int32),
        ("lRssi", ctypes.c_int32),
        ("uLinkQuality", ctypes.c_uint32),
        ("bInRegDomain", ctypes.c_uint8),
        ("usBeaconPeriod", ctypes.c_uint16),
        ("ullTimestamp", ctypes.c_uint64),
        ("ullHostTimestamp", ctypes.c_uint64),
        ("usCapabilityInformation", ctypes.c_uint16),
        ("ulChCenterFrequency", ctypes.c_uint32),  # kHz
        ("wlanRateSet", WLAN_RATE_SET),
        ("ulIeOffset", ctypes.c_uint32),  # from the start of this entry
        ("ulIeSize", ctypes.c_uint32),
    ]


class WLAN_BSS_LIST(ctypes.Structure):  # noqa: N801
    _fields_ = [
        ("dwTotalSize", ctypes.c_uint32),
        ("dwNumberOfItems", ctypes.c_uint32),
        ("wlanBssEntries", WLAN_BSS_ENTRY * 1),
    ]


@dataclass
class RawBss:
    bssid: str
    ssid_bytes: bytes
    rssi_dbm: int
    frequency_khz: int
    capability: int
    host_timestamp: int
    ies: bytes


def decode_bss_list(address: int) -> list[RawBss]:
    """Read a WLAN_BSS_LIST at `address`, never past its dwTotalSize."""
    lst = WLAN_BSS_LIST.from_address(address)
    total = lst.dwTotalSize
    first = WLAN_BSS_LIST.wlanBssEntries.offset
    size = ctypes.sizeof(WLAN_BSS_ENTRY)
    count = min(lst.dwNumberOfItems, max(0, (total - first) // size))
    out: list[RawBss] = []
    for i in range(count):
        offset = first + i * size
        e = WLAN_BSS_ENTRY.from_address(address + offset)
        ies = b""
        if e.ulIeSize and offset + e.ulIeOffset + e.ulIeSize <= total:
            ies = ctypes.string_at(address + offset + e.ulIeOffset, e.ulIeSize)
        n = min(e.dot11Ssid.uSSIDLength, 32)
        out.append(
            RawBss(
                bssid=":".join(f"{b:02x}" for b in e.dot11Bssid),
                ssid_bytes=bytes(e.dot11Ssid.ucSSID[:n]),
                rssi_dbm=e.lRssi,
                frequency_khz=e.ulChCenterFrequency,
                capability=e.usCapabilityInformation,
                host_timestamp=e.ullHostTimestamp,
                ies=ies,
            )
        )
    return out


def reading_from_raw(raw: RawBss) -> BssReading:
    parsed = parse_beacon_ies(raw.ies, raw.capability)
    # Prefer the SSID element; fall back to the entry's own SSID field if the IEs lack it.
    ssid = parsed.ssid if parsed.ssid_present else ssid_from_bytes(raw.ssid_bytes)
    mhz = raw.frequency_khz // 1000 or None
    return BssReading(
        bssid=normalize_mac(raw.bssid),
        ssid=ssid,
        rssi_dbm=raw.rssi_dbm,
        frequency_mhz=mhz,
        channel=channel_from_mhz(mhz) if mhz else None,
        security=parsed.security,
        wps=parsed.wps,
        wps_known=True,
        host_timestamp=raw.host_timestamp,
    )


@dataclass
class Interface:
    guid: GUID
    description: str
    state: int


class WlanApi:
    """A thin wrapper over wlanapi.dll. Raises WirelessError with a message code."""

    def __init__(self, dll: Any = None) -> None:
        if dll is None:
            try:
                dll = ctypes.WinDLL("wlanapi.dll")  # type: ignore[attr-defined]
            except (AttributeError, OSError) as e:
                raise WirelessError("wlanapi_unavailable") from e
        self._dll = dll
        self._handle = ctypes.c_void_p()
        self._setup()

    def _setup(self) -> None:
        d = self._dll
        p = ctypes.POINTER
        d.WlanOpenHandle.argtypes = [
            ctypes.c_uint32,
            ctypes.c_void_p,
            p(ctypes.c_uint32),
            p(ctypes.c_void_p),
        ]
        d.WlanEnumInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, p(ctypes.c_void_p)]
        d.WlanScan.argtypes = [
            ctypes.c_void_p,
            p(GUID),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        d.WlanGetNetworkBssList.argtypes = [
            ctypes.c_void_p,
            p(GUID),
            ctypes.c_void_p,
            ctypes.c_int32,
            ctypes.c_int32,
            ctypes.c_void_p,
            p(ctypes.c_void_p),
        ]
        d.WlanFreeMemory.argtypes = [ctypes.c_void_p]
        d.WlanCloseHandle.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        for name in (
            "WlanOpenHandle",
            "WlanEnumInterfaces",
            "WlanScan",
            "WlanGetNetworkBssList",
            "WlanCloseHandle",
        ):
            getattr(d, name).restype = ctypes.c_uint32
        d.WlanFreeMemory.restype = None

    def __enter__(self) -> WlanApi:
        negotiated = ctypes.c_uint32()
        rc = self._dll.WlanOpenHandle(
            CLIENT_VERSION, None, ctypes.byref(negotiated), ctypes.byref(self._handle)
        )
        if rc == ERROR_SERVICE_NOT_ACTIVE:
            raise WirelessError("no_wifi")  # WLAN AutoConfig isn't running: no Wi-Fi in use
        if rc != ERROR_SUCCESS:
            raise WirelessError("wlanapi_unavailable")
        return self

    def __exit__(self, *exc: object) -> None:
        if self._handle:
            self._dll.WlanCloseHandle(self._handle, None)
            self._handle = ctypes.c_void_p()

    def interfaces(self) -> list[Interface]:
        ptr = ctypes.c_void_p()
        rc = self._dll.WlanEnumInterfaces(self._handle, None, ctypes.byref(ptr))
        if rc != ERROR_SUCCESS:
            raise WirelessError("no_wifi")
        try:
            lst = WLAN_INTERFACE_INFO_LIST.from_address(ptr.value or 0)
            first = WLAN_INTERFACE_INFO_LIST.InterfaceInfo.offset
            size = ctypes.sizeof(WLAN_INTERFACE_INFO)
            out = []
            for i in range(lst.dwNumberOfItems):
                info = WLAN_INTERFACE_INFO.from_address((ptr.value or 0) + first + i * size)
                guid = GUID.from_buffer_copy(info.InterfaceGuid)
                out.append(Interface(guid, info.strInterfaceDescription, info.isState))
            return out
        finally:
            self._dll.WlanFreeMemory(ptr)

    def scan(self, iface: Interface) -> None:
        rc = self._dll.WlanScan(self._handle, ctypes.byref(iface.guid), None, None, None)
        if rc == ERROR_ACCESS_DENIED:
            raise WirelessError("location_off")
        if rc == ERROR_NDIS_DOT11_POWER_STATE_INVALID:
            raise WirelessError("no_wifi")
        if rc != ERROR_SUCCESS:
            # Busy or throttled: the cached list is still worth reading.
            log.info("WlanScan returned %s; reading the cached list", rc)

    def bss_list(self, iface: Interface) -> list[RawBss]:
        ptr = ctypes.c_void_p()
        rc = self._dll.WlanGetNetworkBssList(
            self._handle,
            ctypes.byref(iface.guid),
            None,
            DOT11_BSS_TYPE_ANY,
            0,
            None,
            ctypes.byref(ptr),
        )
        if rc == ERROR_ACCESS_DENIED:
            raise WirelessError("location_off")
        if rc in (ERROR_NDIS_DOT11_POWER_STATE_INVALID, ERROR_INVALID_STATE):
            raise WirelessError("no_wifi")
        if rc != ERROR_SUCCESS:
            raise WirelessError("wlanapi_unavailable")
        try:
            return decode_bss_list(ptr.value or 0) if ptr.value else []
        finally:
            if ptr.value:
                self._dll.WlanFreeMemory(ptr)


def pick_interface(interfaces: list[Interface]) -> Interface:
    ready = [i for i in interfaces if i.state != INTERFACE_NOT_READY]
    if not ready:
        raise WirelessError("no_wifi")  # no adapter, or every radio is off
    return next((i for i in ready if i.state == INTERFACE_CONNECTED), ready[0])


def survey_rounds(
    rounds: int = SCAN_ROUNDS,
    interval: float = SCAN_INTERVAL_SECONDS,
    settle: float = SCAN_SETTLE_SECONDS,
    *,
    api_factory: Callable[[], WlanApi] = WlanApi,
    sleep: Callable[[float], None] = time.sleep,
) -> list[list[BssReading]]:
    """`rounds` fresh scans about `interval` seconds apart, one list of readings per scan."""
    out: list[list[BssReading]] = []
    with api_factory() as api:
        iface = pick_interface(api.interfaces())
        for r in range(rounds):
            if r:
                sleep(max(0.0, interval - settle))
            api.scan(iface)
            sleep(settle)
            out.append([reading_from_raw(b) for b in api.bss_list(iface)])
    return out


def read_once(
    api: WlanApi,
    iface: Interface,
    settle: float = SCAN_SETTLE_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> list[BssReading]:
    """One scan and read, for the locator."""
    api.scan(iface)
    sleep(settle)
    return [reading_from_raw(b) for b in api.bss_list(iface)]
