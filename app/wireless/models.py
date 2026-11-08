"""Layer 4 data model.

Two kinds of model live here:
- In-memory survey models (AccessPoint, BleDevice, NearbySurvey) hold raw BSSIDs and Bluetooth
  addresses. They exist only while one check runs, feed the rules engine, and are never returned
  by the API, printed or saved.
- Kept models (NearbyItem, HeardCounts) hold only flagged items, referenced by salted hashes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SecurityKind = Literal["open", "owe", "wep", "wpa", "wpa2", "wpa3", "wpa2/wpa3", "unknown"]
BleCategory = Literal["tracker", "audio", "lock", "camera", "phone_computer", "other"]


class WifiSecurity(BaseModel):
    kind: SecurityKind
    enterprise: bool = False
    pairwise: list[str] = Field(default_factory=list)
    # How hard the network is to impersonate or read: 0 open, 1 OWE or WEP, 2 WPA or TKIP only,
    # 3 WPA2 or WPA3 with modern encryption. None: couldn't tell, so never compared.
    tier: int | None
    label: str


class WpsInfo(BaseModel):
    """Wi-Fi Protected Setup details an access point puts in its beacon."""

    state: Literal["configured", "not_configured"] | None = None
    ap_setup_locked: bool | None = None
    config_methods: int | None = None
    device_name: str | None = None
    manufacturer: str | None = None
    model_name: str | None = None
    device_category: int | None = None  # WSC primary device type category; 4 = camera


class BssReading(BaseModel):
    """One access point in one scan, from either the WLAN API or netsh."""

    bssid: str
    ssid: str | None  # None: hidden
    rssi_dbm: int
    frequency_mhz: int | None = None
    channel: int | None = None
    security: WifiSecurity
    wps: WpsInfo | None = None
    wps_known: bool = True  # False when the source (netsh) can't show WPS at all
    host_timestamp: int | None = None  # changes when Windows hears the AP again


class AccessPoint(BaseModel):
    """An access point seen in at least two scans. In memory only."""

    ref: str
    bssid: str
    ssid: str | None
    rssi_dbm: int  # median over the scans it was heard in
    frequency_mhz: int | None = None
    channel: int | None = None
    security: WifiSecurity
    wps: WpsInfo | None = None
    wps_known: bool = True
    vendor: str | None = None  # None for randomised BSSIDs: "maker unknown", never a match
    bssid_random: bool = False
    sightings: int

    @property
    def hidden(self) -> bool:
        return self.ssid is None

    @property
    def band(self) -> str | None:
        f = self.frequency_mhz
        if f is None:
            return None
        if f < 3000:
            return "2.4 GHz"
        return "5 GHz" if f < 5925 else "6 GHz"


class BleAdvert(BaseModel):
    """One Bluetooth advertisement, as bleak reports it."""

    address: str
    name: str | None = None
    rssi_dbm: int
    manufacturer_data: dict[int, bytes] = Field(default_factory=dict)
    service_uuids: list[str] = Field(default_factory=list)
    service_data: dict[str, bytes] = Field(default_factory=dict)


class BleClass(BaseModel):
    kind: str
    label: str
    category: BleCategory
    # Trackers only: True if its format says it's away from its owner, False if it says its
    # owner is near, None if the format doesn't say.
    separated: bool | None = None


class BleDevice(BaseModel):
    """One Bluetooth address across the scan rounds. In memory only."""

    ref: str
    address: str
    name: str | None = None
    cls: BleClass
    round_rssi: dict[int, int]  # strongest reading in each round it was heard in

    @property
    def max_rssi(self) -> int:
        return max(self.round_rssi.values())


class RoomNetwork(BaseModel):
    """The Wi-Fi network the user joined (or typed in), used as the genuine one."""

    ssid: str
    bssid: str | None = None
    security: WifiSecurity | None = None
    source: Literal["connected", "typed"]


class NearbySurvey(BaseModel):
    """Everything heard in one nearby check. Input to the rules engine; discarded afterwards."""

    room: RoomNetwork | None = None
    access_points: list[AccessPoint] | None = None  # None: the Wi-Fi survey didn't run
    wifi_method: Literal["wlanapi", "netsh"] | None = None
    ble_devices: list[BleDevice] | None = None  # None: the Bluetooth scan didn't run
    ble_rounds: int = 0


# --- kept after the scan: flagged items only ---------------------------------------------------


class NearbyItem(BaseModel):
    """A flagged nearby item. No BSSID or Bluetooth address: `ref` is a salted hash."""

    ref: str
    kind: Literal["wifi", "bluetooth"]
    label: str
    ssid: str | None = None
    maker: str | None = None
    security: str | None = None
    band: str | None = None
    signal_dbm: int
    rule_ids: list[str]
    connected: bool = False  # Wi-Fi only: the access point the laptop is connected to
    # Layer 6: a salted hash of the BSSID or address with the baseline's fixed salt, so a later
    # scan can be compared with the move-in scan. Not an address.
    match_key: str | None = None


class HeardCounts(BaseModel):
    """How much was heard and then discarded. Counts only, nothing that identifies a device."""

    wifi_access_points: int = 0
    bluetooth_devices: int = 0
    bluetooth_by_category: dict[str, int] = Field(default_factory=dict)
