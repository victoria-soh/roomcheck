"""Identity probes against fixtures and against small local servers on 127.0.0.1."""

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.fingerprint import probes
from app.fingerprint.probes import ProbeError
from tests.unit.devices import fixture

# --- pure parsers -----------------------------------------------------------------------------


def test_extract_title():
    assert probes.extract_title(fixture("http_camera.html")) == "IP Camera & NVR Login"
    assert probes.extract_title(b"<html>no title</html>") is None
    assert len(probes.extract_title(b"<title>" + b"A" * 5000 + b"</title>")) == 200
    assert probes.extract_title(b"\xff\xfe<title>\xff ok</title>") is not None


def test_parse_rtsp_responses():
    assert probes.parse_rtsp_response(fixture("rtsp_401.txt")) == (401, "Hikvision-Webs")
    assert probes.parse_rtsp_response(fixture("rtsp_200.txt")) == (200, "IP Webcam")
    assert probes.parse_rtsp_response(fixture("rtsp_not_rtsp.txt")) is None
    assert probes.parse_rtsp_response(b"") is None
    assert probes.parse_rtsp_response(b"\x00\x01\x02 junk") is None


def test_rtsp_request_never_carries_credentials():
    req = probes.rtsp_request("192.168.1.64", 554)
    assert req.startswith(b"OPTIONS rtsp://192.168.1.64:554 RTSP/1.0\r\nCSeq: 1\r\n")
    assert b"authorization" not in req.lower()
    assert b"@" not in req.split(b"\r\n")[0]


def test_parse_upnp_description():
    u = probes.parse_upnp_description(fixture("upnp_router.xml"))
    assert u.manufacturer == "TP-Link"
    assert u.model_name == "Deco X20"
    assert u.device_type == "urn:schemas-upnp-org:device:InternetGatewayDevice:1"
    assert probes.parse_upnp_description(b"<root><other/></root>") is None


@pytest.mark.parametrize("name", ["upnp_xxe.xml", "upnp_laughs.xml", "upnp_truncated.xml"])
def test_upnp_rejects_hostile_or_broken_xml(name):
    with pytest.raises(ProbeError):
        probes.parse_upnp_description(fixture(name))


def test_location_must_be_the_device_itself():
    assert probes.location_allowed("http://192.168.1.1:1900/rootDesc.xml", "192.168.1.1")
    assert not probes.location_allowed("http://192.168.1.2:1900/rootDesc.xml", "192.168.1.1")
    assert not probes.location_allowed("http://example.com/desc.xml", "192.168.1.1")
    assert not probes.location_allowed("file:///c:/windows/win.ini", "192.168.1.1")
    assert not probes.location_allowed("http://[::1", "192.168.1.1")


# --- live probes on loopback ---------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    routes: dict = {}
    seen_headers: list = []

    def do_GET(self):  # noqa: N802
        type(self).seen_headers.append(dict(self.headers))
        status, headers, body, delay = self.routes.get(self.path, (404, {}, b"", 0))
        time.sleep(delay)
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        if callable(body):
            body(self.wfile)
        else:
            self.wfile.write(body)

    def version_string(self):
        return "TestCam-httpd/1.0"

    def log_message(self, *args):
        pass


@pytest.fixture
def http_server():
    _Handler.routes = {}
    _Handler.seen_headers = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


@pytest.fixture
def short_timeout(monkeypatch):
    monkeypatch.setattr(probes, "TIMEOUT_SECONDS", 0.5)


def _url(srv, path="/"):
    return f"http://127.0.0.1:{srv.server_address[1]}{path}"


def test_fetch_reads_server_and_title(http_server):
    _Handler.routes["/"] = (200, {}, fixture("http_camera.html"), 0)
    status, headers, body = probes.fetch_capped(_url(http_server))
    assert status == 200
    assert headers["server"] == "TestCam-httpd/1.0"
    assert probes.extract_title(body) == "IP Camera & NVR Login"
    sent = _Handler.seen_headers[0]
    assert "Authorization" not in sent
    assert sent["Accept-Encoding"] == "identity"


def test_fetch_caps_body_at_64kb(http_server):
    def endless(w):
        for _ in range(64):
            w.write(b"x" * 16384)

    _Handler.routes["/"] = (200, {}, endless, 0)
    _, _, body = probes.fetch_capped(_url(http_server))
    assert len(body) == probes.MAX_BODY


def test_fetch_does_not_follow_redirects(http_server):
    _Handler.routes["/"] = (302, {"Location": "http://example.com/"}, b"", 0)
    status, _, _ = probes.fetch_capped(_url(http_server))
    assert status == 302


def test_fetch_times_out(http_server, short_timeout):
    _Handler.routes["/"] = (200, {}, b"late", 2)
    with pytest.raises(ProbeError, match="didn't answer in time"):
        probes.fetch_capped(_url(http_server))


def test_upnp_identity_end_to_end(http_server):
    _Handler.routes["/rootDesc.xml"] = (200, {}, fixture("upnp_router.xml"), 0)
    u = probes.upnp_identity(_url(http_server, "/rootDesc.xml"), "127.0.0.1")
    assert u.model_name == "Deco X20"
    assert probes.upnp_identity("http://10.9.9.9/rootDesc.xml", "127.0.0.1") is None


def _tcp_server(reply: bytes | None, delay: float = 0.0):
    """One-shot TCP server; returns (port, list that receives the request bytes)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    received: list[bytes] = []

    def serve():
        conn, _ = sock.accept()
        with conn:
            received.append(conn.recv(4096))
            time.sleep(delay)
            if reply is not None:
                conn.sendall(reply)
            time.sleep(1)
        sock.close()

    threading.Thread(target=serve, daemon=True).start()
    return sock.getsockname()[1], received


def test_rtsp_identity_401_confirms_server_without_login():
    port, received = _tcp_server(fixture("rtsp_401.txt"))
    r = probes.rtsp_identity("127.0.0.1", port)
    assert (r.status, r.server) == (401, "Hikvision-Webs")
    assert b"authorization" not in received[0].lower()


def test_rtsp_identity_other_status_is_not_a_confirmation():
    port, _ = _tcp_server(b"RTSP/1.0 404 Not Found\r\nCSeq: 1\r\n\r\n")
    assert probes.rtsp_identity("127.0.0.1", port) is None


def test_rtsp_identity_junk_reply(short_timeout):
    port, _ = _tcp_server(fixture("rtsp_not_rtsp.txt"))
    with pytest.raises(ProbeError, match="couldn't read"):
        probes.rtsp_identity("127.0.0.1", port)


def test_rtsp_identity_silent_device_times_out(short_timeout):
    port, _ = _tcp_server(None)
    with pytest.raises(ProbeError, match="in time"):
        probes.rtsp_identity("127.0.0.1", port)


def test_rtsp_identity_refused():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(ProbeError):
        probes.rtsp_identity("127.0.0.1", port)


def test_tls_mismatch_note_wording():
    assert probes.TLS_MISMATCH_NOTE == (
        "Its secure web page uses encryption we couldn't agree on, "
        "which often means outdated firmware."
    )


def test_tls_handshake_failure_becomes_mismatch_note():
    # A server that answers TLS with junk fails the handshake, like a device with old ciphers.
    port, _ = _tcp_server(b"HTTP/1.0 400 not TLS\r\n\r\n" * 20)
    with pytest.raises(probes.TlsMismatchError) as e:
        probes.fetch_capped(f"https://127.0.0.1:{port}/")
    assert str(e.value) == probes.TLS_MISMATCH_NOTE


def test_refused_connection_is_not_a_tls_note():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(ProbeError) as e:
        probes.fetch_capped(f"https://127.0.0.1:{port}/")
    assert not isinstance(e.value, probes.TlsMismatchError)
