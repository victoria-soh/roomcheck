"""Identity checks on consented devices: HTTP Server header and title, RTSP OPTIONS, and the
UPnP description XML. Read-only, no credentials ever, 3 s timeout and 64 KB cap on each.

Every device response is untrusted input: sizes are capped, strings truncated, and XML is
parsed with defusedxml.
"""

from __future__ import annotations

import html
import ipaddress
import re
import socket
import ssl
import time
from urllib.parse import urlsplit

import httpx
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from app.fingerprint.models import HttpIdentity, RtspIdentity, UpnpIdentity

TIMEOUT_SECONDS = 3.0
MAX_BODY = 64 * 1024
MAX_RTSP_REPLY = 4096
MAX_FIELD = 200
USER_AGENT = "RoomCheck/0.1 (move-in check; read-only)"

HTTP_PORTS = {80: "http", 8000: "http", 8080: "http", 443: "https", 8443: "https"}
RTSP_PORTS = (554, 8554)

_TITLE_RE = re.compile(rb"<title[^>]*>(.*?)</title\s*>", re.IGNORECASE | re.DOTALL)
_RTSP_STATUS_RE = re.compile(r"^RTSP/1\.\d\s+(\d{3})")


class ProbeError(Exception):
    """A device didn't answer in time or answered with junk. Message is plain language."""


TLS_MISMATCH_NOTE = (
    "Its secure web page uses encryption we couldn't agree on, which often means outdated firmware."
)


class TlsMismatchError(ProbeError):
    """The device answered but no TLS settings could be agreed. TLS is never loosened to retry.

    This is an observation about the device, not a failure to identify it.
    """

    def __init__(self) -> None:
        super().__init__(TLS_MISMATCH_NOTE)


def _is_tls_error(exc: BaseException) -> bool:
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, ssl.SSLError):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def _clip(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())[:MAX_FIELD]
    return value or None


def extract_title(body: bytes) -> str | None:
    m = _TITLE_RE.search(body[:MAX_BODY])
    if not m:
        return None
    return _clip(html.unescape(m.group(1).decode("utf-8", errors="replace")))


def _http_client() -> httpx.Client:
    # No redirects (they could point anywhere), no system proxy, no auth, no cookies kept.
    # Certificates aren't checked: devices use self-signed ones and we send nothing secret.
    return httpx.Client(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=False,
        trust_env=False,
        verify=False,  # noqa: S501
        # identity: raw bytes are what we cap, so a compressed reply can't expand past 64 KB.
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
    )


def fetch_capped(url: str, client: httpx.Client | None = None) -> tuple[int, httpx.Headers, bytes]:
    """GET a URL, reading at most MAX_BODY bytes within TIMEOUT_SECONDS overall."""
    own = client is None
    client = client or _http_client()
    deadline = time.monotonic() + TIMEOUT_SECONDS
    body = bytearray()
    try:
        with client.stream("GET", url) as resp:
            for chunk in resp.iter_raw():
                body += chunk
                if len(body) >= MAX_BODY or time.monotonic() > deadline:
                    break
            return resp.status_code, resp.headers, bytes(body[:MAX_BODY])
    except httpx.TimeoutException as e:
        raise ProbeError("didn't answer in time") from e
    except httpx.ConnectError as e:
        if _is_tls_error(e):
            raise TlsMismatchError() from e
        raise ProbeError("refused the connection") from e
    except (httpx.HTTPError, ValueError) as e:
        raise ProbeError("sent a reply we couldn't read") from e
    finally:
        if own:
            client.close()


def http_identity(ip: str, port: int, client: httpx.Client | None = None) -> HttpIdentity:
    scheme = HTTP_PORTS[port]
    status, headers, body = fetch_capped(f"{scheme}://{ip}:{port}/", client)
    return HttpIdentity(
        port=port,
        scheme="https" if scheme == "https" else "http",
        status=status,
        server=_clip(headers.get("server")),
        title=extract_title(body),
    )


def rtsp_request(ip: str, port: int) -> bytes:
    lines = [f"OPTIONS rtsp://{ip}:{port} RTSP/1.0", "CSeq: 1", f"User-Agent: {USER_AGENT}"]
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


def parse_rtsp_response(data: bytes) -> tuple[int, str | None] | None:
    """(status, Server header) from an RTSP reply, or None if it isn't RTSP."""
    text = data[:MAX_RTSP_REPLY].decode("utf-8", errors="replace")
    lines = text.splitlines()
    if not lines:
        return None
    m = _RTSP_STATUS_RE.match(lines[0])
    if not m:
        return None
    server = None
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        if sep and name.strip().lower() == "server":
            server = _clip(value)
            break
    return int(m.group(1)), server


def rtsp_identity(ip: str, port: int) -> RtspIdentity | None:
    """Send one OPTIONS request with no credentials. None if the reply isn't 200 or 401."""
    deadline = time.monotonic() + TIMEOUT_SECONDS
    data = b""
    try:
        with socket.create_connection((ip, port), timeout=TIMEOUT_SECONDS) as sock:
            sock.sendall(rtsp_request(ip, port))
            while b"\r\n\r\n" not in data and len(data) < MAX_RTSP_REPLY:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                sock.settimeout(remaining)
                chunk = sock.recv(MAX_RTSP_REPLY - len(data))
                if not chunk:
                    break
                data += chunk
    except TimeoutError as e:
        if not data:
            raise ProbeError("didn't answer in time") from e
    except OSError as e:
        raise ProbeError("refused the connection") from e
    parsed = parse_rtsp_response(data)
    if parsed is None:
        if data:
            raise ProbeError("sent a reply we couldn't read")
        raise ProbeError("didn't answer in time")
    status, server = parsed
    # 200 or 401 (asks for a login we never give) both confirm an RTSP video server.
    return RtspIdentity(port=port, status=status, server=server) if status in (200, 401) else None


def location_allowed(location: str, device_ip: str) -> bool:
    """Only fetch a description hosted by the device itself, over plain HTTP(S)."""
    try:
        parts = urlsplit(location)
        host = parts.hostname
        if parts.scheme not in ("http", "https") or host is None:
            return False
        return ipaddress.ip_address(host) == ipaddress.ip_address(device_ip)
    except ValueError:
        return False


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_upnp_description(body: bytes) -> UpnpIdentity | None:
    try:
        root = ElementTree.fromstring(body[:MAX_BODY])
    except (ElementTree.ParseError, DefusedXmlException, ValueError) as e:
        raise ProbeError("sent a description we couldn't read") from e
    device = next((el for el in root.iter() if _local(el.tag) == "device"), None)
    if device is None:
        return None
    fields: dict[str, str | None] = {}
    for child in device:
        name = _local(child.tag)
        if name in ("manufacturer", "modelName", "deviceType") and name not in fields:
            fields[name] = _clip(child.text)
    return UpnpIdentity(
        manufacturer=fields.get("manufacturer"),
        model_name=fields.get("modelName"),
        device_type=fields.get("deviceType"),
    )


def upnp_identity(
    location: str, device_ip: str, client: httpx.Client | None = None
) -> UpnpIdentity | None:
    if not location_allowed(location, device_ip):
        return None
    status, _, body = fetch_capped(location, client)
    if status != 200:
        raise ProbeError("didn't share its description")
    return parse_upnp_description(body)
