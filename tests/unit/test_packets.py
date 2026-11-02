"""Packet parsers in scannerd, fed packets built with scapy (no network needed)."""

import ipaddress
from datetime import UTC, datetime, timedelta

from scapy.layers.dhcp import BOOTP, DHCP
from scapy.layers.inet import IP, TCP, UDP
from scapy.layers.l2 import ARP, Ether

from scannerd.jobs.arp import observation_from_arp
from scannerd.jobs.listeners import ObservationLog, observation_from_packet

NOW = datetime(2026, 11, 2, tzinfo=UTC)
CAM_MAC = "00:12:34:56:78:9a"


def wire(pkt):
    """Round-trip through bytes, as a sniffed packet would arrive."""
    return Ether(bytes(pkt))


def mac_bytes(mac):
    return bytes.fromhex(mac.replace(":", ""))


def test_arp_reply_and_request_senders_are_observed():
    reply = Ether() / ARP(op=2, psrc="192.168.1.1", hwsrc="00:11:22:33:44:55", pdst="192.168.1.10")
    request = Ether() / ARP(op=1, psrc="192.168.1.20", hwsrc=CAM_MAC, pdst="192.168.1.1")
    a = observation_from_packet(reply, NOW)
    b = observation_from_packet(request, NOW)
    assert (a.source, a.ip, a.mac) == ("arp_passive", "192.168.1.1", "00:11:22:33:44:55")
    assert (b.ip, b.mac) == ("192.168.1.20", CAM_MAC)


def test_arp_probe_from_unconfigured_host_is_ignored():
    probe = Ether() / ARP(op=1, psrc="0.0.0.0", hwsrc=CAM_MAC, pdst="192.168.1.20")
    assert observation_from_arp(probe, "arp_sweep", NOW) is None


def dhcp_request(**opts):
    options = [("message-type", "request"), *opts.items(), "end"]
    return (
        Ether(src=CAM_MAC, dst="ff:ff:ff:ff:ff:ff")
        / IP(src="0.0.0.0", dst="255.255.255.255")
        / UDP(sport=68, dport=67)
        / BOOTP(op=1, chaddr=mac_bytes(CAM_MAC))
        / DHCP(options=options)
    )


def test_dhcp_request_gives_hostname_vendor_class_and_param_list():
    pkt = dhcp_request(
        requested_addr="192.168.1.64",
        hostname=b"IPC-HALL",
        vendor_class_id=b"udhcp 1.24.1",
        param_req_list=[1, 3, 6, 12, 15, 28, 42],
    )
    o = observation_from_packet(wire(pkt), NOW)
    assert o.source == "dhcp"
    assert (o.ip, o.mac, o.hostname) == ("192.168.1.64", CAM_MAC, "IPC-HALL")
    assert o.services[0].detail == {
        "vendor_class": "udhcp 1.24.1",
        "param_req_list": "1,3,6,12,15,28,42",
    }


def test_dhcp_discover_without_options_still_gives_mac():
    pkt = dhcp_request()
    o = observation_from_packet(wire(pkt), NOW)
    assert (o.ip, o.mac, o.hostname, o.services) == (None, CAM_MAC, None, [])


def test_dhcp_ack_gives_assigned_address():
    ack = (
        Ether()
        / IP(src="192.168.1.1", dst="255.255.255.255")
        / UDP(sport=67, dport=68)
        / BOOTP(op=2, yiaddr="192.168.1.64", chaddr=mac_bytes(CAM_MAC))
        / DHCP(options=[("message-type", "ack"), "end"])
    )
    o = observation_from_packet(wire(ack), NOW)
    assert (o.ip, o.mac) == ("192.168.1.64", CAM_MAC)


def test_dhcp_offer_is_not_treated_as_assignment():
    offer = (
        Ether()
        / IP(src="192.168.1.1")
        / UDP(sport=67, dport=68)
        / BOOTP(op=2, yiaddr="192.168.1.64", chaddr=mac_bytes(CAM_MAC))
        / DHCP(options=[("message-type", "offer"), "end"])
    )
    assert observation_from_packet(wire(offer), NOW) is None


def test_tuya_broadcast_detected_without_reading_payload():
    pkt = (
        Ether(src="10:d5:61:00:00:01")
        / IP(src="192.168.1.77", dst="255.255.255.255")
        / UDP(sport=63145, dport=6667)
        / (b"\x00\x00\x55\xaa" + b"\x13" * 100)
    )
    o = observation_from_packet(wire(pkt), NOW)
    assert o.source == "tuya"
    assert (o.ip, o.mac) == ("192.168.1.77", "10:d5:61:00:00:01")
    assert o.services[0].detail == {"port": "6667"}


def test_unrelated_packets_ignored():
    assert observation_from_packet(Ether() / IP() / UDP(dport=53), NOW) is None
    assert observation_from_packet(Ether() / IP() / TCP(dport=80), NOW) is None


def test_observation_log_keeps_first_and_last_and_filters_subnet():
    log = ObservationLog(ipaddress.IPv4Network("192.168.1.0/24"), cap=2)
    pkt = Ether() / ARP(op=1, psrc="192.168.1.20", hwsrc=CAM_MAC)
    for i in range(10):
        log.add(observation_from_packet(pkt, NOW + timedelta(seconds=i)))
    log.add(observation_from_packet(Ether() / ARP(psrc="169.254.1.1", hwsrc=CAM_MAC), NOW))
    obs = log.observations()
    assert [o.seen_at for o in obs] == [NOW, NOW + timedelta(seconds=9)]


def test_observation_log_cap_and_distinct_pairs():
    log = ObservationLog(ipaddress.IPv4Network("192.168.1.0/24"), cap=2)
    for mac in ("00:00:00:00:00:01", "00:00:00:00:00:02", "00:00:00:00:00:03"):
        log.add(observation_from_packet(Ether() / ARP(psrc="192.168.1.1", hwsrc=mac), NOW))
    # Two MACs claiming the gateway are both kept (Layer 3 needs this); the cap holds.
    assert [o.mac for o in log.observations()] == ["00:00:00:00:00:01", "00:00:00:00:00:02"]
