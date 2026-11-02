"""FastAPI core. Runs as a normal user and is only ever bound to 127.0.0.1."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from app.discovery.models import DiscoveryResult
from app.scan import run_scan
from app.scanner import ScannerError, ScannerProcess

HOST = "127.0.0.1"
PORT = 8765

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    proc = ScannerProcess()
    try:
        app.state.scanner = proc.start()
    except (ScannerError, OSError):
        log.warning("scanner worker did not start; raw-packet checks will be reported as failed")
        app.state.scanner = None
    try:
        yield
    finally:
        proc.stop()


app = FastAPI(title="RoomCheck", lifespan=lifespan)


class DiscoveryRequest(BaseModel):
    # True only when the user says this is their network or they have permission to test it.
    consent: bool = False
    duration_seconds: int = Field(default=60, ge=10, le=120)


@app.get("/api/health")
def health(request: Request) -> dict[str, bool]:
    return {"ok": True, "scanner": getattr(request.app.state, "scanner", None) is not None}


@app.post("/api/discovery")
def discovery(body: DiscoveryRequest, request: Request) -> DiscoveryResult:
    scanner = getattr(request.app.state, "scanner", None)
    return run_scan(body.consent, scanner, body.duration_seconds)
