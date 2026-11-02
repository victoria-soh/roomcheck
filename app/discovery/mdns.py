"""Step 3: mDNS / Bonjour browse with zeroconf. Standard queries only, on the joined network."""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from app.discovery.models import NetworkInfo, Observation, Service

MAX_SERVICES = 64
_MAX_TXT_ENTRIES = 20
_MAX_TXT_LEN = 100
_RESOLVE_TIMEOUT_MS = 1000


def _decode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def observation_from_service(
    service_type: str,
    instance_name: str,
    addresses: list[str],
    server: str | None,
    properties: Mapping[Any, Any],  # zeroconf TXT records: bytes or str keys and values
    now: datetime,
) -> list[Observation]:
    """One Observation per IPv4 address the service resolved to."""
    txt: dict[str, str] = {}
    for k, v in list(properties.items())[:_MAX_TXT_ENTRIES]:
        key = _decode(k)[:_MAX_TXT_LEN]
        if key:
            txt[key] = _decode(v)[:_MAX_TXT_LEN]
    instance = instance_name.removesuffix("." + service_type).removesuffix(service_type)
    detail = {"instance": instance[:_MAX_TXT_LEN], **{f"txt.{k}": v for k, v in txt.items()}}
    hostname = server.rstrip(".") if server else None
    service = Service(kind="mdns", name=service_type.removesuffix(".local."), detail=detail)
    return [
        Observation(source="mdns", seen_at=now, ip=ip, hostname=hostname, services=[service])
        for ip in addresses
        if ":" not in ip
    ]


def browse(net: NetworkInfo, browse_seconds: float = 10.0) -> list[Observation]:
    from zeroconf import IPVersion, ServiceBrowser, ServiceStateChange, Zeroconf
    from zeroconf import ZeroconfServiceTypes as Types

    zc = Zeroconf(interfaces=[net.own_ip], ip_version=IPVersion.V4Only)
    try:
        types = Types.find(zc=zc, timeout=min(3.0, browse_seconds / 2))
        found: set[tuple[str, str]] = set()
        lock = threading.Lock()

        def on_change(
            zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange
        ) -> None:
            if state_change is ServiceStateChange.Added:
                with lock:
                    if len(found) < MAX_SERVICES:
                        found.add((service_type, name))

        browsers = [ServiceBrowser(zc, t, handlers=[on_change]) for t in types]
        time.sleep(max(0.0, browse_seconds - min(3.0, browse_seconds / 2)))
        for b in browsers:
            b.cancel()

        def resolve(item: tuple[str, str]) -> list[Observation]:
            service_type, name = item
            info = zc.get_service_info(service_type, name, timeout=_RESOLVE_TIMEOUT_MS)
            if info is None:
                return []
            return observation_from_service(
                service_type,
                name,
                info.parsed_addresses(),
                info.server,
                info.properties,
                datetime.now(UTC),
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            return [o for batch in pool.map(resolve, sorted(found)) for o in batch]
    finally:
        zc.close()
