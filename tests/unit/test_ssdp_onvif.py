from datetime import UTC, datetime

from app.discovery import onvif, ssdp

NOW = datetime(2026, 11, 2, tzinfo=UTC)

IGD_RESPONSE = (
    b"HTTP/1.1 200 OK\r\n"
    b"CACHE-CONTROL: max-age=1800\r\n"
    b"LOCATION: http://192.168.1.1:1900/rootDesc.xml\r\n"
    b"SERVER: Linux/3.14 UPnP/1.0 MiniUPnPd/2.1\r\n"
    b"ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n"
    b"USN: uuid:abcd::urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n"
    b"\r\n"
)


def test_parse_ssdp_response():
    h = ssdp.parse_ssdp_response(IGD_RESPONSE)
    assert h == {
        "location": "http://192.168.1.1:1900/rootDesc.xml",
        "server": "Linux/3.14 UPnP/1.0 MiniUPnPd/2.1",
        "st": "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
        "usn": "uuid:abcd::urn:schemas-upnp-org:device:InternetGatewayDevice:1",
    }
    o = ssdp.observation_from_response("192.168.1.1", h, NOW)
    assert o.source == "ssdp"
    assert o.services[0].name == "urn:schemas-upnp-org:device:InternetGatewayDevice:1"
    assert o.services[0].detail["location"].endswith("rootDesc.xml")


def test_ssdp_rejects_non_responses_and_caps_values():
    assert ssdp.parse_ssdp_response(b"NOTIFY * HTTP/1.1\r\nNT: x\r\n\r\n") is None
    assert ssdp.parse_ssdp_response(b"HTTP/1.1 200 OK\r\nSERVER: x\r\n\r\n") is None
    assert ssdp.parse_ssdp_response(b"\xff\xfe garbage") is None
    long = b"HTTP/1.1 200 OK\r\nST: upnp:rootdevice\r\nSERVER: " + b"A" * 5000 + b"\r\n\r\n"
    h = ssdp.parse_ssdp_response(long)
    assert h is not None and len(h.get("server", "")) <= 256


def test_ssdp_m_search_is_ssdp_all():
    assert b"ST: ssdp:all" in ssdp.M_SEARCH
    assert b'MAN: "ssdp:discover"' in ssdp.M_SEARCH


PROBE_MATCH = b"""<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
  xmlns:dn="http://www.onvif.org/ver10/network/wsdl"
  xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
 <SOAP-ENV:Header><wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches</wsa:Action></SOAP-ENV:Header>
 <SOAP-ENV:Body><d:ProbeMatches><d:ProbeMatch>
  <wsa:EndpointReference><wsa:Address>urn:uuid:1234</wsa:Address></wsa:EndpointReference>
  <d:Types>dn:NetworkVideoTransmitter tds:Device</d:Types>
  <d:Scopes>onvif://www.onvif.org/type/video_encoder onvif://www.onvif.org/hardware/DS-2CD2143 onvif://www.onvif.org/name/HIKVISION</d:Scopes>
  <d:XAddrs>http://192.168.1.64/onvif/device_service</d:XAddrs>
  <d:MetadataVersion>1</d:MetadataVersion>
 </d:ProbeMatch></d:ProbeMatches></SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""


def test_parse_probe_match():
    [m] = onvif.parse_probe_matches(PROBE_MATCH)
    assert m["types"] == ["NetworkVideoTransmitter", "Device"]
    assert m["xaddrs"] == ["http://192.168.1.64/onvif/device_service"]
    assert "onvif://www.onvif.org/hardware/DS-2CD2143" in m["scopes"]
    o = onvif.observation_from_match("192.168.1.64", m, NOW)
    assert o.services[0].name == "NetworkVideoTransmitter"
    assert "HIKVISION" in o.services[0].detail["scopes"]


def test_probe_rejects_hostile_and_broken_xml():
    xxe = (
        b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///c:/windows/win.ini">]>'
        b"<r><ProbeMatch><Types>&x;</Types></ProbeMatch></r>"
    )
    laughs = (
        b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        b"<l>&b;</l>"
    )
    assert onvif.parse_probe_matches(xxe) == []
    assert onvif.parse_probe_matches(laughs) == []
    assert onvif.parse_probe_matches(b"<not closed") == []
    assert onvif.parse_probe_matches(b"") == []


def test_probe_message_asks_for_video_transmitters():
    msg = onvif.probe_message("abc")
    assert b"dn:NetworkVideoTransmitter" in msg
    assert b"uuid:abc" in msg
    assert onvif.parse_probe_matches(msg) == []  # a Probe is not a ProbeMatch
