"""Vendor lookup from the bundled IEEE OUI list. Works offline."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.discovery.merge import is_random_mac
from app.discovery.netinfo import normalize_mac

OUI_FILE = Path(__file__).resolve().parent / "data" / "oui.tsv"


@lru_cache(maxsize=1)
def load_oui(path: Path = OUI_FILE) -> dict[str, str]:
    table: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            prefix, _, name = line.rstrip("\n").partition("\t")
            if len(prefix) == 6 and name:
                table[prefix] = name
    return table


def lookup_vendor(mac: str | None, table: dict[str, str] | None = None) -> str | None:
    """Organisation registered for the MAC's prefix. None for private (randomised) MACs."""
    if not mac:
        return None
    try:
        mac = normalize_mac(mac)
    except ValueError:
        return None
    if is_random_mac(mac):
        return None  # locally administered: the prefix belongs to nobody
    prefix = mac.replace(":", "")[:6].upper()
    return (table if table is not None else load_oui()).get(prefix)
