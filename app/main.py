"""FastAPI core. Runs as a normal user and is only ever bound to 127.0.0.1."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.discovery.messages import message_for
from app.discovery.models import DiscoveryResult
from app.scan import run_scan
from app.scanner import ScannerError, ScannerProcess
from app.wireless.locator import LocatorTarget, locate, source_for
from app.wireless.models import NearbyItem
from app.wireless.survey import NearbyResult, run_nearby_check
from app.wireless.wlanapi import WirelessError

HOST = "127.0.0.1"
PORT = 8765
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
WS_UNKNOWN_ITEM = 4404
WS_BAD_ORIGIN = 4403

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.locator_targets = {}
    proc = ScannerProcess()
    try:
        app.state.scanner = proc.start()
    except (ScannerError, OSError):
        log.warning("scanner worker did not start; raw-packet checks will be reported as failed")
        app.state.scanner = None
    try:
        yield
    finally:
        app.state.locator_targets = {}
        proc.stop()


app = FastAPI(title="RoomCheck", lifespan=lifespan)
app.state.locator_targets = {}
locator_source = source_for  # where readings come from; replaced in tests


class DiscoveryRequest(BaseModel):
    # True only when the user says this is their network or they have permission to test it.
    consent: bool = False
    duration_seconds: int = Field(default=60, ge=10, le=120)
    # Allow the optional NVD lookup (product names only). False keeps everything offline.
    online: bool = True
    # The nearby Wi-Fi and Bluetooth check (public broadcasts only; never connects).
    nearby: bool = True
    # The room's Wi-Fi name, if you're not connected to it. An SSID is at most 32 bytes.
    room_network: str | None = Field(default=None, max_length=32)


class NearbyRequest(BaseModel):
    room_network: str | None = Field(default=None, max_length=32)


def _remember_targets(request: Request, items: Iterable[NearbyItem]) -> None:
    """Only the latest check's flagged items can be located. Replaced on every check."""
    request.app.state.locator_targets = {
        i.ref: LocatorTarget(ref=i.ref, kind=i.kind, label=i.label) for i in items
    }


@app.get("/api/health")
def health(request: Request) -> dict[str, bool]:
    return {"ok": True, "scanner": getattr(request.app.state, "scanner", None) is not None}


@app.post("/api/discovery")
def discovery(body: DiscoveryRequest, request: Request) -> DiscoveryResult:
    scanner = getattr(request.app.state, "scanner", None)
    result = run_scan(
        body.consent,
        scanner,
        body.duration_seconds,
        online=body.online,
        include_nearby=body.nearby,
        typed_room=body.room_network,
    )
    _remember_targets(request, result.nearby_items)
    return result


@app.post("/api/nearby")
def nearby_check(body: NearbyRequest, request: Request) -> NearbyResult:
    result = run_nearby_check(typed_room=body.room_network)
    _remember_targets(request, result.items)
    return result


def _origin_allowed(origin: str | None) -> bool:
    """Browsers let any web page open a WebSocket to 127.0.0.1, so only accept our own pages.
    No Origin header means a non-browser client on this laptop (e.g. a script)."""
    if origin is None:
        return True
    return urlparse(origin).hostname in _LOCAL_HOSTS


@app.websocket("/api/nearby/locate/{ref}")
async def locate_ws(websocket: WebSocket, ref: str) -> None:
    """Stream smoothed signal readings for one flagged item: Bluetooth several times a second,
    Wi-Fi once per scan. Nothing is stored; the stream ends when the page closes it."""
    if not _origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=WS_BAD_ORIGIN)
        return
    await websocket.accept()
    target = websocket.app.state.locator_targets.get(ref)
    if target is None:
        await websocket.send_json({"error": message_for("locator_unknown_item")})
        await websocket.close(code=WS_UNKNOWN_ITEM)
        return
    source = locator_source(target)
    try:
        async for reading in locate(target, source):
            await websocket.send_json(reading.model_dump())
    except WebSocketDisconnect:
        pass
    except WirelessError as e:
        await websocket.send_json({"error": message_for(e.code)})
        await websocket.close()
    finally:
        await source.aclose()  # type: ignore[attr-defined]
