"""Terminal logging for the app process.

scannerd configures its own logging ("scannerd: ..."); uvicorn configures only its own
`uvicorn.*` loggers. Without this, INFO lines from `app.*` (such as "report: PDF in ... s")
are dropped. They go to stderr in the same shape as the worker's: "app: <message>".

On Windows, asyncio's Proactor transport logs a full traceback when a page's WebSocket drops
abruptly (ConnectionResetError, WinError 10054, e.g. the laptop slept). It is harmless, so
that one record is lowered to DEBUG with no traceback.
"""

from __future__ import annotations

import logging
import sys

APP_FORMAT = "app: %(message)s"
WINERROR_CONNECTION_RESET = 10054
_HANDLER_NAME = "roomcheck-app"


def is_connection_reset(record: logging.LogRecord) -> bool:
    """A record about a connection the other side reset (WinError 10054)."""
    exc = record.exc_info[1] if record.exc_info else None
    if exc is None:
        return False
    return isinstance(exc, ConnectionResetError) and (
        getattr(exc, "winerror", None) == WINERROR_CONNECTION_RESET
        or exc.errno in (WINERROR_CONNECTION_RESET, 104)  # 104: ECONNRESET elsewhere
    )


class QuietConnectionReset(logging.Filter):
    """Lower asyncio's connection-reset traceback to a one-line DEBUG record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not is_connection_reset(record):
            return True
        record.levelno = logging.DEBUG
        record.levelname = "DEBUG"
        record.exc_info = None
        record.exc_text = None
        record.msg = "asyncio: a connection was reset by the other side (WinError 10054)"
        record.args = None
        return logging.getLogger(record.name).isEnabledFor(logging.DEBUG)


def configure_logging(level: int = logging.INFO) -> None:
    """Idempotent: safe to call from `python -m app` and again at server startup."""
    app_log = logging.getLogger("app")
    if not any(h.get_name() == _HANDLER_NAME for h in app_log.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(logging.Formatter(APP_FORMAT))
        app_log.addHandler(handler)
    app_log.setLevel(level)
    # Propagation stays on: uvicorn adds no root handler, so nothing prints twice, and test
    # log capture (on the root logger) keeps working.
    asyncio_log = logging.getLogger("asyncio")
    if not any(isinstance(f, QuietConnectionReset) for f in asyncio_log.filters):
        asyncio_log.addFilter(QuietConnectionReset())
