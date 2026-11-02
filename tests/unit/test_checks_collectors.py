"""Layer 3 collectors: Wi-Fi encryption, DNS, the DHCP probe job, and the NVD client."""

import json
from pathlib import Path

import httpx
import pytest
from scapy.layers.dhcp import BOOTP, DHCP
from scapy.layers.inet import IP, UDP
from scapy.layers.l2 import Ether

from app.checks import cve, dns, wifi
from app.checks.models import WifiStatus
from scannerd.jobs import dhcp as dhcp_job
from scannerd.server import default_jobs, handle_request

HIK_CPE = "cpe:2.3:o:hikvision:ds-2cd2143g2-i_firmware:-:*:*:*:*:*:*:*"
CHECKS = Path(__file__).resolve().parents[1] / "fixtures" / "checks"


def netsh(name: str) -> str:
    return (CHECKS / name).read_text(encoding="utf-8")


# --- Wi-Fi ------------------------------------------------------------------------------------


def test_wpa2_connection_is_read_and_not_weak():
    s = wifi.status_for_interface(netsh("netsh_wpa2.txt"), "Wi-Fi")
    assert s == WifiStatus(
        interface="Wi-Fi", ssid="HomeNet", authentication="WPA2-Personal", cipher="CCMP"
    )
    assert not wifi.is_weak(s)


def test_open_network_on_second_adapter_block():
    text = netsh("netsh_open_two_adapters.txt")
    s = wifi.status_for_interface(text, "Wi-Fi")
    assert (s.ssid, s.authentication, s.cipher) == ("Hotel Guest", "Open", "None")
    assert wifi.is_weak(s)
    # The disconnected adapter isn't treated as the connection.
    assert wifi.status_for_interface(text, "Wi-Fi 2") is None


def test_wep_is_weak():
    assert wifi.is_weak(wifi.status_for_interface(netsh("netsh_wep.txt"), "wi-fi"))


@pytest.mark.parametrize(("auth", "cipher"), [("WPA3-Personal", "GCMP-256"), ("OWE", "CCMP")])
def test_modern_encryption_not_weak(auth, cipher):
    assert not wifi.is_weak(WifiStatus(interface="w", authentication=auth, cipher=cipher))


def test_wired_connection_is_not_wifi():
    assert wifi.status_for_interface(netsh("netsh_wpa2.txt"), "Ethernet") is None
    assert (
        wifi.status_for_interface("There is no wireless interface on the system.", "Ethernet")
        is None
    )


def test_translated_labels_are_reported_not_guessed():
    with pytest.raises(wifi.WifiCheckError) as e:
        wifi.status_for_interface(netsh("netsh_french.txt"), "Wi-Fi")
    assert e.value.code == "unreadable"


def test_netsh_is_run_by_full_path_with_argument_list(monkeypatch):
    calls = []

    class Done:
        returncode = 0
        stdout = netsh("netsh_wpa2.txt")

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return Done()

    monkeypatch.setattr(wifi.subprocess, "run", fake_run)
    monkeypatch.setattr(wifi.Path, "exists", lambda self: True)
    assert wifi.current_wifi("Wi-Fi").cipher == "CCMP"
    [(args, kwargs)] = calls
    assert args[0].lower().endswith(r"system32\netsh.exe")
    assert args[1:] == ["wlan", "show", "interfaces"]
    assert kwargs.get("shell") is not True


def test_netsh_failure_means_no_wlan(monkeypatch):
    class Failed:
        returncode = 1
        stdout = "The Wireless AutoConfig Service (wlansvc) is not running."

    monkeypatch.setattr(wifi.subprocess, "run", lambda args, **k: Failed())
    monkeypatch.setattr(wifi.Path, "exists", lambda self: True)
    with pytest.raises(wifi.WifiCheckError) as e:
        wifi.current_wifi("Wi-Fi")
    assert e.value.code == "no_wlan"


# --- DNS --------------------------------------------------------------------------------------


def resolver(table):
    def resolve(name):
        if name.startswith("roomcheck-"):
            return table.get("random", ("nxdomain", []))
        return table.get(name, ("ok", ["93.184.215.14"]))

    return resolve


def test_honest_dns():
    r = dns.check_dns(resolver({}))
    assert r.nxdomain is True
    assert r.random_name.startswith("roomcheck-") and r.random_name.endswith(".example.com")
    assert r.checked_domains == list(dns.PUBLIC_DOMAINS)
    assert not dns.is_tampered(r)


def test_nxdomain_hijack_is_tampered():
    r = dns.check_dns(resolver({"random": ("ok", ["198.51.100.7"])}))
    assert r.nxdomain is False
    assert r.random_name_answers == ["198.51.100.7"]
    assert dns.is_tampered(r)


@pytest.mark.parametrize("ip", ["192.168.1.1", "10.0.0.5", "127.0.0.1", "100.64.0.1", "0.0.0.0"])
def test_public_name_to_non_public_address_is_tampered(ip):
    r = dns.check_dns(resolver({"example.com": ("ok", [ip])}))
    assert r.non_public_answers == {"example.com": [ip]}
    assert dns.is_tampered(r)


def test_cdn_style_different_public_answers_are_fine():
    r = dns.check_dns(resolver({"www.iana.org": ("ok", ["192.0.32.8", "104.18.1.1"])}))
    assert not dns.is_tampered(r)


def test_empty_answer_for_random_name_is_not_a_hijack():
    r = dns.check_dns(resolver({"random": ("ok", [])}))
    assert r.nxdomain is True


def test_unclear_dns_is_not_tampered():
    r = dns.check_dns(lambda name: ("unclear", []))
    assert r.nxdomain is None and r.checked_domains == []
    assert not dns.is_tampered(r)


# --- DHCP probe job ---------------------------------------------------------------------------

OWN_MAC = "c4:0f:08:11:22:33"


def offer(server_id, server_mac, xid, yiaddr="192.168.68.60", msg="offer"):
    pkt = (
        Ether(src=server_mac, dst="ff:ff:ff:ff:ff:ff")
        / IP(src=server_id, dst="255.255.255.255")
        / UDP(sport=67, dport=68)
        / BOOTP(op=2, xid=xid, yiaddr=yiaddr, chaddr=bytes.fromhex(OWN_MAC.replace(":", "")))
        / DHCP(options=[("message-type", msg), ("server_id", server_id), "end"])
    )
    return Ether(bytes(pkt))


def test_discover_packet_is_a_plain_discover_from_own_mac():
    pkt = Ether(bytes(dhcp_job.discover_packet(OWN_MAC, 0x1234)))
    assert pkt[Ether].src == OWN_MAC
    assert pkt[BOOTP].xid == 0x1234 and pkt[BOOTP].op == 1
    opts = dict(o for o in pkt[DHCP].options if isinstance(o, tuple))
    assert opts["message-type"] == 1  # DISCOVER, never REQUEST
    assert opts["client_id"] == bytes.fromhex("01" + OWN_MAC.replace(":", ""))
    assert "requested_addr" not in opts


def test_parse_offers_counts_distinct_servers():
    xid = 42
    offers = dhcp_job.parse_offers(
        [
            offer("192.168.68.1", "cc:ba:bd:ac:94:d8", xid),
            offer("192.168.68.1", "cc:ba:bd:ac:94:d8", xid),  # duplicate
            offer("192.168.68.250", "02:00:00:00:00:66", xid),
            offer("10.9.9.9", "02:00:00:00:00:77", xid + 1),  # another transaction
            offer("192.168.68.1", "cc:ba:bd:ac:94:d8", xid, msg="ack"),  # not an offer
        ],
        xid,
    )
    assert [(o["server_id"], o["server_mac"]) for o in offers] == [
        ("192.168.68.1", "cc:ba:bd:ac:94:d8"),
        ("192.168.68.250", "02:00:00:00:00:66"),
    ]


def test_dhcp_job_is_allowlisted_and_takes_no_parameters():
    jobs = default_jobs()
    assert "dhcp_probe" in jobs
    reply = handle_request(
        json.dumps({"job": "dhcp_probe", "params": {"server": "10.0.0.1"}}).encode(), jobs
    )
    assert reply == {"ok": False, "error": "bad_params"}


# --- NVD --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("maker", "word"),
    [
        ("Hangzhou Hikvision Digital Technology Co.,Ltd.", "hikvision"),
        ("TP-Link Systems Inc.", "tp-link"),
        ("Zhejiang Dahua Technology Co., Ltd.", "dahua"),
        ("Sonos, Inc.", "sonos"),
        ("Co., Ltd.", None),
    ],
)
def test_maker_word(maker, word):
    assert cve.maker_word(maker) == word


def test_pick_products_prefers_firmware_and_matches_model():
    names = [
        r"cpe:2.3:h:hikvision:ds-2cd2143g2-i\(s\):-:*:*:*:*:*:*:*",
        r"cpe:2.3:o:hikvision:ds-2cd2143g2-i\(s\)_firmware:-:*:*:*:*:*:*:*",
        "cpe:2.3:o:hikvision:ds-2cd2143g2-iu_firmware:-:*:*:*:*:*:*:*",
        "cpe:2.3:o:otherco:ds-2cd2143g2-i_firmware:-:*:*:*:*:*:*:*",
        "cpe:2.3:a:hikvision:ivms-4200:-:*:*:*:*:*:*:*",
    ]
    picked = cve.pick_products(names, "hikvision", "DS-2CD2143G2-I")
    assert picked[0] == r"cpe:2.3:o:hikvision:ds-2cd2143g2-i\(s\)_firmware"
    assert all(":otherco:" not in p and ":a:" not in p for p in picked)
    assert len(picked) <= cve.MAX_PRODUCTS_PER_MODEL


def test_summarise_cves_flags_exploited():
    body = {
        "totalResults": 2,
        "vulnerabilities": [
            {"cve": {"id": "CVE-2017-7921", "published": "2017-05-06"}},
            {
                "cve": {
                    "id": "CVE-2021-36260",
                    "published": "2021-09-22",
                    "cisaExploitAdd": "2022-01-10",
                }
            },
        ],
    }
    assert cve.summarise_cves(body) == (2, ["CVE-2021-36260", "CVE-2017-7921"], ["CVE-2021-36260"])


def test_cache_round_trip_and_expiry(tmp_path):
    now = [1000.0]
    cache = cve.CveCache(tmp_path / "c.sqlite3", ttl=60, clock=lambda: now[0])
    cache.put("k", [1, ["a"], []])
    assert cache.get("k") == [1, ["a"], []]
    now[0] += 61
    assert cache.get("k") is None
    cache.close()


def test_rate_limiter_waits_within_budget_and_refuses_beyond():
    now = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        now[0] += s

    lim = cve.RateLimiter(2, window=30, clock=lambda: now[0], sleep=sleep)
    assert lim.acquire(deadline=100) and lim.acquire(deadline=100)
    assert lim.acquire(deadline=100)  # waits for the window to pass
    assert slept == [30]
    assert lim.acquire(deadline=100)
    assert not lim.acquire(deadline=now[0] + 5)  # would need to wait past the deadline


def nvd_transport(calls, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if status != 200:
            return httpx.Response(status)
        if "cpes" in request.url.path:
            return httpx.Response(
                200,
                json={"products": [{"cpe": {"cpeName": HIK_CPE}}]},
            )
        return httpx.Response(
            200,
            json={
                "totalResults": 1,
                "vulnerabilities": [
                    {"cve": {"id": "CVE-2021-36260", "cisaExploitAdd": "2022-01-10"}}
                ],
            },
        )

    return httpx.MockTransport(handler)


def make_client(tmp_path, calls, status=200, api_key=None):
    return cve.NvdClient(
        cache=cve.CveCache(tmp_path / "nvd.sqlite3"),
        limiter=cve.RateLimiter(5, clock=lambda: 0.0, sleep=lambda s: None),
        api_key=api_key,
        transport=nvd_transport(calls, status),
    )


def test_lookup_sends_only_product_names_and_uses_cache(tmp_path):
    calls = []
    client = make_client(tmp_path, calls, api_key="secret-key")
    [m] = client.lookup("hikvision", "DS-2CD2143G2-I", deadline=1e9)
    assert (m.total, m.cve_ids, m.exploited) == (1, ["CVE-2021-36260"], ["CVE-2021-36260"])
    assert m.cpe == "cpe:2.3:o:hikvision:ds-2cd2143g2-i_firmware"
    assert [c.url.params.get("keywordSearch") for c in calls[:1]] == ["hikvision DS-2CD2143G2-I"]
    assert calls[1].url.params["virtualMatchString"] == m.cpe
    assert all(c.headers["apiKey"] == "secret-key" for c in calls)
    # Second lookup is served from the SQLite cache: no new requests.
    client.lookup("hikvision", "DS-2CD2143G2-I", deadline=1e9)
    assert len(calls) == 2
    client.cache.close()


@pytest.mark.parametrize("status", [403, 503])
def test_rate_limited_nvd_raises_unavailable(tmp_path, status):
    client = make_client(tmp_path, [], status=status)
    with pytest.raises(cve.NvdUnavailable):
        client.lookup("hikvision", "DS-2CD2143G2-I", deadline=1e9)
    client.cache.close()


def test_no_api_key_means_low_rate_limit(monkeypatch, tmp_path):
    monkeypatch.delenv("NVD_API_KEY", raising=False)
    c = cve.make_client(tmp_path / "a.sqlite3")
    assert c.limiter.limit == 5 and c.api_key is None
    c.cache.close()
    monkeypatch.setenv("NVD_API_KEY", "k")
    c = cve.make_client(tmp_path / "b.sqlite3")
    assert c.limiter.limit == 50
    c.cache.close()


def test_lookup_stops_after_first_product_with_results(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if "cpes" in request.url.path:
            names = [
                "cpe:2.3:h:tp-link:tapo_tc70:3.0:*:*:*:*:*:*:*",
                "cpe:2.3:o:tp-link:tapo_tc70_firmware:1.3.9:*:*:*:*:*:*:*",
            ]
            return httpx.Response(200, json={"products": [{"cpe": {"cpeName": n}} for n in names]})
        return httpx.Response(
            200, json={"totalResults": 1, "vulnerabilities": [{"cve": {"id": "CVE-2023-49515"}}]}
        )

    client = cve.NvdClient(
        cache=cve.CveCache(tmp_path / "n.sqlite3"),
        limiter=cve.RateLimiter(5, clock=lambda: 0.0, sleep=lambda s: None),
        transport=httpx.MockTransport(handler),
    )
    [m] = client.lookup("tp-link", "TC70", deadline=1e9)
    assert m.cpe == "cpe:2.3:o:tp-link:tapo_tc70_firmware"
    assert len(calls) == 2  # one CPE search, one CVE query: the hardware entry isn't queried
    client.cache.close()
