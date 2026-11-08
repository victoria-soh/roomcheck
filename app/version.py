"""Which RoomCheck is running, so an outdated server is easy to spot.

The startup log line names the version, when its code was last changed and when the dashboard
was built. GET /api/health repeats them and says whether the code on disk has changed since the
server started ("stale"): the server then runs old code while serving a newer dashboard, which
is how a mismatched page and backend happen. Restarting RoomCheck fixes it.
"""

from __future__ import annotations

import tomllib
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE_DIRS = ("app", "scannerd")
DASHBOARD = ROOT / "web" / "dist" / "index.html"


def version() -> str:
    try:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        return str(data["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"


def code_time() -> datetime | None:
    """When the newest Python or rules file was last changed."""
    newest = 0.0
    for folder in CODE_DIRS:
        for path in (ROOT / folder).rglob("*"):
            if path.suffix in (".py", ".yaml") and "__pycache__" not in path.parts:
                newest = max(newest, path.stat().st_mtime)
    return datetime.fromtimestamp(newest, UTC) if newest else None


def dashboard_time() -> datetime | None:
    try:
        return datetime.fromtimestamp(DASHBOARD.stat().st_mtime, UTC)
    except OSError:
        return None


def _when(t: datetime | None) -> str:
    return t.astimezone().strftime("%d %b %Y %H:%M:%S") if t else "not built"


def startup_line(started_code: datetime | None) -> str:
    return (
        f"RoomCheck {version()} | code from {_when(started_code)} | "
        f"dashboard built {_when(dashboard_time())}"
    )
