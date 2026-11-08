"""Start scannerd and ask it to run named jobs over local IPC."""

from __future__ import annotations

import json
import os
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
        # True once we stopped waiting for a job the worker may still be running. The worker
        # carries on with it, so the next check restarts the worker first (app.main).
        self.abandoned = False

    def run(self, job: str, params: dict[str, Any], timeout: float) -> Any:
        try:
            conn = Client((HOST, self.port), authkey=self._authkey)
        except OSError as e:
            raise ScannerError("scanner_unavailable") from e
        with conn:
            conn.send_bytes(json.dumps({"job": job, "params": params}).encode())
            if not conn.poll(timeout):
                self.abandoned = True
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

    def alive(self) -> bool:
        """The worker process is running (it may still be busy)."""
        return self._proc is not None and self._proc.poll() is None

    def kill(self) -> None:
        """Stop the worker at once, with any job it's running and that job's own children
        (e.g. nmap). Its in-flight jobs then fail with scanner_unavailable."""
        if self._proc is None:
            return
        if os.name == "nt":
            # /T also ends the worker's child processes. Fixed argument list, no shell, and
            # the full system path, so nothing earlier on PATH can stand in for taskkill.
            system = Path(os.environ.get("SystemRoot", r"C:\Windows"))
            taskkill = system / "System32" / "taskkill.exe"
            subprocess.run(  # noqa: S603
                [str(taskkill), "/PID", str(self._proc.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            self._proc.kill()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._proc = None
        self.client = None

    def restart(self) -> ScannerClient:
        """Kill the worker (cancelling its jobs) and start a fresh one with a new key."""
        self.kill()
        return self.start()

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
