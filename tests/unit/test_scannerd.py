"""scannerd IPC: auth key, job allowlist and parameter validation, over a real loopback socket."""

import json
import secrets
import threading
from multiprocessing.connection import Client

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.scanner import ScannerClient, ScannerError, ScannerProcess
from scannerd.protocol import JobError
from scannerd.server import Job, Server, default_jobs, handle_request


class EchoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: int = Field(default=1, ge=1, le=3)


def echo(p: EchoParams):
    return [{"n": p.n}]


def fail_npcap(p: EchoParams):
    raise JobError("npcap_missing")


def fail_perm(p: EchoParams):
    raise PermissionError("denied")


def boom(p: EchoParams):
    raise RuntimeError("unexpected")


JOBS = {
    "echo": Job(EchoParams, echo),
    "npcap": Job(EchoParams, fail_npcap),
    "perm": Job(EchoParams, fail_perm),
    "boom": Job(EchoParams, boom),
}


def req(**body):
    return json.dumps(body).encode()


def test_allowlist_and_params():
    assert handle_request(req(job="echo", params={"n": 2}), JOBS) == {
        "ok": True,
        "result": [{"n": 2}],
    }
    assert handle_request(req(job="echo"), JOBS)["result"] == [{"n": 1}]
    assert handle_request(req(job="nmap", params={"args": "-sS"}), JOBS)["error"] == "unknown_job"
    assert handle_request(req(job="echo", params={"n": 99}), JOBS)["error"] == "bad_params"
    # Unknown parameters (e.g. a target) are refused, not ignored.
    assert (
        handle_request(req(job="echo", params={"target": "8.8.8.8"}), JOBS)["error"] == "bad_params"
    )
    assert handle_request(req(job="echo", extra=1), JOBS)["error"] == "bad_request"
    assert handle_request(b"\xff not json", JOBS)["error"] == "bad_request"
    assert handle_request(req(job=["echo"]), JOBS)["error"] == "unknown_job"


def test_job_errors_map_to_codes():
    assert handle_request(req(job="npcap"), JOBS)["error"] == "npcap_missing"
    assert handle_request(req(job="perm"), JOBS)["error"] == "permission"
    assert handle_request(req(job="boom"), JOBS)["error"] == "internal"


def test_default_jobs_are_only_the_allowlisted_jobs():
    assert set(default_jobs()) == {"arp_sweep", "passive_listen", "port_scan", "dhcp_probe"}
    arp = default_jobs()["arp_sweep"].params
    with pytest.raises(ValueError):
        arp.model_validate({"cidr": "10.0.0.0/8"})
    with pytest.raises(ValueError):
        arp.model_validate({"passes": 50})


@pytest.fixture
def server():
    key = secrets.token_bytes(32)
    srv = Server(key, JOBS)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, key
    srv.stop()


def test_server_binds_loopback_only(server):
    srv, _ = server
    assert srv.address[0] == "127.0.0.1"


def test_client_round_trip(server):
    srv, key = server
    client = ScannerClient(srv.address[1], key)
    assert client.run("echo", {"n": 3}, timeout=5) == [{"n": 3}]
    with pytest.raises(ScannerError) as e:
        client.run("npcap", {}, timeout=5)
    assert e.value.code == "npcap_missing"


def test_wrong_auth_key_is_rejected(server):
    srv, _ = server
    with pytest.raises(Exception):  # noqa: B017 - AuthenticationError or a reset connection
        conn = Client(("127.0.0.1", srv.address[1]), authkey=b"x" * 32)
        conn.send_bytes(req(job="echo"))
        conn.recv_bytes()
    # The server keeps serving correct clients afterwards.
    assert ScannerClient(srv.address[1], server[1]).run("echo", {}, timeout=5) == [{"n": 1}]


def test_unreachable_scanner_reports_unavailable():
    with pytest.raises(ScannerError) as e:
        ScannerClient(1, secrets.token_bytes(32)).run("echo", {}, timeout=1)
    assert e.value.code == "scanner_unavailable"


def test_scanner_process_starts_and_refuses_unknown_jobs():
    proc = ScannerProcess()
    client = proc.start()
    try:
        with pytest.raises(ScannerError) as e:
            client.run("nmap_raw", {"args": "-sS 192.168.1.1"}, timeout=10)
        assert e.value.code == "unknown_job"
    finally:
        proc.stop()
