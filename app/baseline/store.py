"""The encrypted local store: the move-in baseline, the fixed salt for matching keys, the
recognition answers and the handover task states.

It's one SQLite file in %LOCALAPPDATA%\\RoomCheck, and every value in it is encrypted with
Windows DPAPI for the current Windows account, so other accounts on the laptop (and a copy of
the file on another machine) can't read it. Only the row names ("salt", "baseline", ...) are
plain. Nothing here ever leaves the laptop. Handover data (answers, names, notes, tasks) is
saved here whether or not a move-in scan exists; "Delete move-in scan" removes only the move-in
scan.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Protocol

from app.discovery.messages import message_for

STORE_NAME = "baseline.db"
# Extra DPAPI entropy: another program running as the same user can't decrypt RoomCheck's
# values without also knowing this.
ENTROPY = b"RoomCheck move-in baseline v1"


class BaselineUnreadable(Exception):
    """The store can't be decrypted: it belongs to another Windows account or install."""

    def __init__(self) -> None:
        super().__init__(message_for("baseline_unreadable"))


class Protector(Protocol):
    def protect(self, data: bytes) -> bytes: ...
    def unprotect(self, blob: bytes) -> bytes: ...  # raises BaselineUnreadable


class DpapiProtector:
    """Windows DPAPI through pywin32, scoped to the current user."""

    def protect(self, data: bytes) -> bytes:
        import win32crypt

        blob: bytes = win32crypt.CryptProtectData(data, None, ENTROPY, None, None, 0)
        return blob

    def unprotect(self, blob: bytes) -> bytes:
        import pywintypes
        import win32crypt

        try:
            _, data = win32crypt.CryptUnprotectData(blob, ENTROPY, None, None, 0)
        except pywintypes.error as e:  # another account, another install, or a damaged file
            raise BaselineUnreadable from e
        return bytes(data)


def default_store_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "RoomCheck" / STORE_NAME


class BaselineStore:
    def __init__(self, path: Path, protector: Protector) -> None:
        self.path = path
        self._protector = protector

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.execute("CREATE TABLE IF NOT EXISTS store (key TEXT PRIMARY KEY, value BLOB NOT NULL)")
        return conn

    def exists(self) -> bool:
        return self.path.is_file()

    def write(self, values: dict[str, Any]) -> None:
        """Encrypt and save each value (as JSON). One transaction."""
        rows = [(k, self._protector.protect(json.dumps(v).encode())) for k, v in values.items()]
        with self._connect() as conn:
            conn.executemany("INSERT OR REPLACE INTO store (key, value) VALUES (?, ?)", rows)
        conn.close()

    def read(self, key: str) -> Any | None:
        """The decrypted value, or None if it isn't there. Raises BaselineUnreadable."""
        if not self.exists():
            return None
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT value FROM store WHERE key = ?", (key,)).fetchone()
            conn.close()
        except sqlite3.DatabaseError as e:  # not a database any more: damaged or replaced
            raise BaselineUnreadable from e
        if row is None:
            return None
        try:
            return json.loads(self._protector.unprotect(row[0]))
        except (ValueError, UnicodeDecodeError) as e:
            raise BaselineUnreadable from e

    def remove(self, key: str) -> None:
        """Delete one row, e.g. the move-in scan, and keep the rest."""
        if not self.exists():
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM store WHERE key = ?", (key,))
        conn.close()

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)
