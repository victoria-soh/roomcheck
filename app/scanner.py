"""Start scannerd and ask it to run named jobs over local IPC."""

from __future__ import annotations

import json
import secrets
import subprocess
import sys
import threading
from multiprocessing.connection import Client
from pathlib import Path
from typing import Any, Protocol

from scannerd.protocol import HOST, MAX_RESPONSE_BYTES

ROOT = Path(__file__).resolve().parents[1]


class ScannerError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Scanner(Protocol):
    def run(self, job: str, params: dict[str, Any], timeout: float) -> Any: ...


class ScannerClient:
    def __init__(self, port: int, authkey: bytes) -> None:
        self.port = port
        self._authkey = authkey

    def run(self, job: str, params: dict[str, Any], timeout: float) -> Any:
        try:
            conn = Client((HOST, self.port), authkey=self._authkey)
        except OSError as e:
            raise ScannerError("scanner_unavailable") from e
        with conn:
            conn.send_bytes(json.dumps({"job": job, "params": params}).encode())
            if not conn.poll(timeout):
                raise ScannerError("timeout")
            try:
                reply = json.loads(conn.recv_bytes(maxlength=MAX_RESPONSE_BYTES))
            except (OSError, EOFError, json.JSONDecodeError) as e:
                raise ScannerError("scanner_unavailable") from e
        if not reply.get("ok"):
            raise ScannerError(str(reply.get("error", "internal")))
        return reply.get("result")


class ScannerProcess:
    """Owns the scannerd child process. The child exits when we close its stdin."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self.client: ScannerClient | None = None

    def start(self, timeout: float = 20.0) -> ScannerClient:
        authkey = secrets.token_bytes(32)
        proc = subprocess.Popen(  # noqa: S603 - fixed argument list, no shell
            [sys.executable, "-m", "scannerd"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(authkey.hex() + "\n")
        proc.stdin.flush()

        line: list[str] = []
        reader = threading.Thread(target=lambda: line.append(proc.stdout.readline()), daemon=True)  # type: ignore[union-attr]
        reader.start()
        reader.join(timeout)
        first = line[0].strip() if line else ""
        if not first.startswith("PORT "):
            proc.kill()
            raise ScannerError("scanner_unavailable")

        self._proc = proc
        self.client = ScannerClient(int(first.split()[1]), authkey)
        return self.client

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
            self._proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self._proc.kill()
        self._proc = None
        self.client = None
