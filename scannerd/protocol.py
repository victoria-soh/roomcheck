"""Wire format between the app and scannerd: one JSON request and one JSON reply per connection.

JSON over send_bytes/recv_bytes, never pickle, so neither side unpickles data from the other.
"""

from __future__ import annotations

MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
HOST = "127.0.0.1"


class JobError(Exception):
    """A job failed in a way the user should hear about. `code` maps to a plain message."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def require_pcap() -> None:
    """Raise npcap_missing if scapy has no packet-capture driver to use."""
    from scapy.config import conf

    if not conf.use_pcap:
        raise JobError("npcap_missing")
