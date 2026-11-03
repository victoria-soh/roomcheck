"""Salted hashes for nearby BSSIDs and Bluetooth addresses.

Nothing outside this process ever sees a raw address. Flagged items are referred to by
`wifi:<hash>` or `bluetooth:<hash>`; the locator hashes each live reading the same way to find
the item again. The salt is random per process, so hashes can't be matched across sessions or
against a list of known addresses. (Layer 6 will keep a per-install salt, DPAPI-encrypted,
so a re-scan can be compared with the move-in baseline.)
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

SESSION_SALT = secrets.token_bytes(16)


def _normalise(address: str) -> str:
    return "".join(c for c in address.lower() if c in "0123456789abcdef")


def hash_address(address: str, salt: bytes = SESSION_SALT) -> str:
    return hmac.new(salt, _normalise(address).encode(), hashlib.sha256).hexdigest()[:20]


def wifi_ref(bssid: str, salt: bytes = SESSION_SALT) -> str:
    return f"wifi:{hash_address(bssid, salt)}"


def ble_ref(address: str, salt: bytes = SESSION_SALT) -> str:
    return f"bluetooth:{hash_address(address, salt)}"
