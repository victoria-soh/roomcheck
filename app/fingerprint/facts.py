"""Flatten a Device (Layer 1 sightings plus Layer 2 identity) into the facts the scorer reads."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.discovery.models import Device

# mDNS TXT keys that carry a model or product name.
_MODEL_TXT_KEYS = {"md", "model", "mdl", "ty", "fn", "am", "product", "mn", "usbmdl"}


@dataclass
class Facts:
    makers: list[tuple[str, str]] = field(default_factory=list)  # (where from, maker)
    names: list[str] = field(default_factory=list)
    servers: list[str] = field(default_factory=list)
    open_ports: set[int] = field(default_factory=set)
    rtsp_ports: list[int] = field(default_factory=list)
    onvif_types: set[str] = field(default_factory=set)
    mdns_types: set[str] = field(default_factory=set)
    ssdp_types: list[str] = field(default_factory=list)
    hap_categories: set[int] = field(default_factory=set)
    dhcp_vendors: list[str] = field(default_factory=list)
    gateway: bool = False
    random_mac: bool = False
    tuya: bool = False
    notes: list[str] = field(default_factory=list)


def _add(items: list[str], value: str | None) -> None:
    if value and value not in items:
        items.append(value)


def device_facts(device: Device) -> Facts:
    f = Facts(gateway=device.is_gateway, random_mac=device.mac_is_random)
    if device.vendor:
        f.makers.append(("MAC address maker", device.vendor))
    for hostname in device.hostnames:
        _add(f.names, hostname)

    for s in device.services:
        if s.kind == "mdns":
            f.mdns_types.add(s.name)
            _add(f.names, s.detail.get("instance"))
            for key, value in s.detail.items():
                if key.startswith("txt.") and key[4:].lower() in _MODEL_TXT_KEYS:
                    _add(f.names, value)
            if s.name == "_hap._tcp" and s.detail.get("txt.ci", "").isdigit():
                f.hap_categories.add(int(s.detail["txt.ci"]))
        elif s.kind == "ssdp":
            _add(f.ssdp_types, s.name)
            _add(f.servers, s.detail.get("server"))
        elif s.kind == "onvif":
            f.onvif_types.update(s.detail.get("types", "").split() or [s.name])
        elif s.kind == "tuya":
            f.tuya = True
        elif s.kind == "dhcp":
            _add(f.dhcp_vendors, s.detail.get("vendor_class"))

    ident = device.identity
    if ident is not None:
        f.open_ports = set(ident.open_ports or [])
        f.notes = list(ident.notes)
        for web in ident.http:
            _add(f.servers, web.server)
            _add(f.names, web.title)
        for stream in ident.rtsp:
            f.rtsp_ports.append(stream.port)
            _add(f.servers, stream.server)
        if ident.upnp is not None:
            if ident.upnp.manufacturer:
                f.makers.append(("maker in its description", ident.upnp.manufacturer))
            _add(f.names, ident.upnp.model_name)
            _add(f.ssdp_types, ident.upnp.device_type)
    return f
