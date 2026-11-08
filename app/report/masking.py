"""Mask MAC addresses in the report: the maker plus the last 3 octets (docs/original-plan.md)."""

from __future__ import annotations

import re

from app.discovery.merge import is_random_mac
from app.discovery.netinfo import normalize_mac
from app.fingerprint.oui import lookup_vendor

_MAC = re.compile(r"\b[0-9a-f]{2}([:-])[0-9a-f]{2}(?:\1[0-9a-f]{2}){4}\b", re.IGNORECASE)


def mask_mac(mac: str) -> str:
    """'00:bc:99:aa:bb:cc' -> 'xx:xx:xx:aa:bb:cc (Hangzhou Hikvision ...)'."""
    try:
        norm = normalize_mac(mac)
    except ValueError:
        return "xx:xx:xx:xx:xx:xx"
    last3 = norm[9:]
    if is_random_mac(norm):
        return f"xx:xx:xx:{last3} (private address)"
    return f"xx:xx:xx:{last3} ({lookup_vendor(norm) or 'maker unknown'})"


def mask_text(text: str) -> str:
    """Every MAC address in free text, masked."""
    return _MAC.sub(lambda m: mask_mac(m.group()), text)
