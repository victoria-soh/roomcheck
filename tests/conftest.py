"""Test-wide guard: no test may use the real .env or reach the Anthropic API.

Every test sees settings with no API keys, the app's background warm-up is a no-op, and
building a real Anthropic client fails loudly. Tests that need a key pass their own Settings
and a fake client.
"""

import pytest

import app.checks.cve as cve
import app.cli as cli
import app.config as config
import app.explain.service as service
from app.config import Settings
from app.explain import ai


@pytest.fixture(autouse=True)
def no_real_keys_or_api_calls(monkeypatch):
    def no_settings():
        return Settings()

    def no_real_client(api_key):
        raise AssertionError("a test tried to build a real Anthropic client")

    for module in (config, service, cli, cve):
        monkeypatch.setattr(module, "get_settings", no_settings)
    monkeypatch.setattr(ai, "start_warm_up", lambda settings: None)
    monkeypatch.setattr(ai, "_build_client", no_real_client)
    ai.reset_shared_client()
    yield
    ai.reset_shared_client()


class FakeProtector:
    """Stands in for Windows DPAPI in tests: reversible, tied to one "account" key, and
    failing like DPAPI when the blob belongs to another account or is damaged."""

    def __init__(self, account: bytes = b"this-account") -> None:
        self.account = account

    def protect(self, data: bytes) -> bytes:
        return b"FAKEDPAPI:" + self.account + b":" + bytes(b ^ 0x5A for b in data)

    def unprotect(self, blob: bytes) -> bytes:
        from app.baseline.store import BaselineUnreadable

        prefix = b"FAKEDPAPI:" + self.account + b":"
        if not blob.startswith(prefix):
            raise BaselineUnreadable
        return bytes(b ^ 0x5A for b in blob[len(prefix) :])


@pytest.fixture(autouse=True)
def no_real_baseline_store(monkeypatch, tmp_path):
    """No test reads or writes the real move-in store (the RoomCheck folder in %LOCALAPPDATA%)."""
    import app.main as main
    from app.baseline.store import BaselineStore

    path = tmp_path / "roomcheck-store" / "baseline.db"
    monkeypatch.setattr(main, "baseline_store", lambda: BaselineStore(path, FakeProtector()))
    main.app.state.handover = None
    yield path
    main.app.state.handover = None
