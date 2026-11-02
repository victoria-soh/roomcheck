"""scannerd: the only process that sends or captures raw packets.

It listens on 127.0.0.1 with a per-session auth key and runs only jobs named in an allowlist.
Each job has a strict parameter model; nothing the caller sends becomes a target or a
command-line argument.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from multiprocessing.connection import Connection, Listener
from typing import Any

from pydantic import BaseModel, ValidationError

from scannerd.protocol import HOST, MAX_REQUEST_BYTES, JobError

log = logging.getLogger("scannerd")


@dataclass(frozen=True)
class Job:
    params: type[BaseModel]
    run: Callable[[Any], Any]


def default_jobs() -> dict[str, Job]:
    from scannerd.jobs.arp import ArpSweepParams, arp_sweep
    from scannerd.jobs.listeners import PassiveListenParams, passive_listen
    from scannerd.jobs.ports import PortScanParams, port_scan

    return {
        "arp_sweep": Job(ArpSweepParams, arp_sweep),
        "passive_listen": Job(PassiveListenParams, passive_listen),
        "port_scan": Job(PortScanParams, port_scan),
    }


def _error(code: str) -> dict[str, Any]:
    return {"ok": False, "error": code}


def handle_request(raw: bytes, jobs: Mapping[str, Job]) -> dict[str, Any]:
    try:
        req = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error("bad_request")
    if not isinstance(req, dict) or not set(req) <= {"job", "params"}:
        return _error("bad_request")
    name = req.get("job")
    job = jobs.get(name) if isinstance(name, str) else None
    if job is None:
        return _error("unknown_job")
    try:
        params = job.params.model_validate(req.get("params") or {})
    except ValidationError:
        return _error("bad_params")
    try:
        return {"ok": True, "result": job.run(params)}
    except JobError as e:
        return _error(e.code)
    except PermissionError:
        return _error("permission")
    except Exception:
        log.exception("job %s failed", name)
        return _error("internal")


class Server:
    def __init__(self, authkey: bytes, jobs: Mapping[str, Job] | None = None) -> None:
        self.jobs = dict(jobs) if jobs is not None else default_jobs()
        self._listener = Listener((HOST, 0), authkey=authkey)
        self._closed = threading.Event()

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._listener.address
        return host, port

    def serve_forever(self) -> None:
        while not self._closed.is_set():
            try:
                conn = self._listener.accept()
            except Exception:  # wrong auth key, client hung up, or listener closed
                log.debug("rejected connection", exc_info=True)
                continue
            threading.Thread(target=self._serve_conn, args=(conn,), daemon=True).start()

    def _serve_conn(self, conn: Connection) -> None:
        with conn:
            try:
                raw = conn.recv_bytes(maxlength=MAX_REQUEST_BYTES)
            except (OSError, EOFError):
                return
            reply = handle_request(raw, self.jobs)
            try:
                conn.send_bytes(json.dumps(reply).encode())
            except (OSError, EOFError):
                pass

    def stop(self) -> None:
        self._closed.set()
        self._listener.close()
