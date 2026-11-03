"""Small radio helpers: channels, frequencies and signal wording."""

from __future__ import annotations


def channel_from_mhz(mhz: int) -> int | None:
    if mhz == 2484:
        return 14
    if 2412 <= mhz <= 2472:
        return (mhz - 2407) // 5
    if 5955 <= mhz <= 7115:
        return (mhz - 5950) // 5
    if 5000 <= mhz < 5925:
        return (mhz - 5000) // 5
    return None


def mhz_from_channel(channel: int, band: str | None = None) -> int | None:
    """Centre frequency for a channel. Without a band, channels 1-14 are 2.4 GHz, others 5 GHz."""
    b = (band or "").replace(" ", "").lower()
    if b.startswith("6"):
        return 5950 + 5 * channel if 1 <= channel <= 233 else None
    if b.startswith("2.4") or (not b and 1 <= channel <= 14):
        if channel == 14:
            return 2484
        return 2407 + 5 * channel if 1 <= channel <= 13 else None
    return 5000 + 5 * channel if 32 <= channel <= 177 else None


def percent_to_dbm(percent: int) -> int:
    """netsh shows signal as 0-100%; Windows maps -100 dBm to 0% and -50 dBm to 100%."""
    return max(-100, min(-50, percent // 2 - 100))


def strength(rssi_dbm: int | float) -> str:
    if rssi_dbm >= -50:
        return "very strong"
    if rssi_dbm >= -60:
        return "strong"
    if rssi_dbm >= -70:
        return "medium"
    return "weak"
