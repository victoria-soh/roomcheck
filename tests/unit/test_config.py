"""Configuration: .env parsing, defaults, and that API keys never show up in logs, printed
output, API responses or error messages. Uses temporary files only, never the real .env."""

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.cli as cli
import app.config as config
import app.main as main
from app.config import DEFAULT_ANTHROPIC_MODEL, DEFAULT_TSA_URL, KEYS, load_settings, parse_env
from app.wireless.models import HeardCounts
from app.wireless.survey import NearbyResult

ROOT = Path(__file__).resolve().parents[2]
SENTINEL = "sk-ant-api03-TEST-SENTINEL-do-not-leak-1234567890"


def env_file(tmp_path, text):
    p = tmp_path / ".env"
    p.write_text(text, encoding="utf-8")
    return p


# --- parsing and defaults ------------------------------------------------------------------


def test_empty_values_fall_back_to_defaults(tmp_path):
    s = load_settings(env_file(tmp_path, (ROOT / ".env.example").read_text("utf-8")), environ={})
    assert s.anthropic_api_key is None and s.nvd_api_key is None
    assert s.anthropic_model == DEFAULT_ANTHROPIC_MODEL == "claude-haiku-5-5"
    assert s.tsa_url == DEFAULT_TSA_URL == "https://freetsa.org/tsr"


def test_values_quotes_comments_and_export(tmp_path):
    p = env_file(
        tmp_path,
        "# comment\n\nexport ANTHROPIC_MODEL='claude-sonnet-5-5'\nNVD_API_KEY=\"abc\"\n"
        "UNRELATED_SECRET=zzz\n",
    )
    s = load_settings(p, environ={})
    assert s.anthropic_model == "claude-sonnet-5-5"
    assert s.nvd_api_key is not None and s.nvd_api_key.get_secret_value() == "abc"
    assert "UNRELATED_SECRET" not in parse_env(p.read_text("utf-8"))


def test_environment_overrides_the_file(tmp_path):
    p = env_file(tmp_path, "ANTHROPIC_MODEL=from-file\n")
    assert load_settings(p, {"ANTHROPIC_MODEL": "from-env"}).anthropic_model == "from-env"
    assert load_settings(p, {"ANTHROPIC_MODEL": ""}).anthropic_model == "from-file"


def test_missing_file_is_fine(tmp_path):
    assert load_settings(tmp_path / "nope.env", environ={}).anthropic_api_key is None


# --- the env files themselves --------------------------------------------------------------


def test_env_is_git_ignored():
    lines = (ROOT / ".gitignore").read_text("utf-8").splitlines()
    assert ".env" in [line.strip() for line in lines]


def test_env_example_has_every_key_and_no_real_secrets():
    values = parse_env((ROOT / ".env.example").read_text("utf-8"))
    assert set(values) == set(KEYS)
    assert values["ANTHROPIC_API_KEY"] == "" and values["NVD_API_KEY"] == ""
    assert values["ANTHROPIC_MODEL"] == ""  # the default lives in app/config.py
    assert values["TSA_URL"] == "https://freetsa.org/tsr"


def test_every_key_has_a_comment_saying_what_it_is_for():
    lines = (ROOT / ".env.example").read_text("utf-8").splitlines()
    for key in KEYS:
        i = next(n for n, line in enumerate(lines) if line.startswith(f"{key}="))
        assert lines[i - 1].startswith("# "), key


# --- ANTHROPIC_API_KEY never leaks ---------------------------------------------------------


@pytest.fixture
def secret_settings(tmp_path, monkeypatch):
    """The sentinel key in a temporary .env and in the process environment."""
    s = load_settings(env_file(tmp_path, f"ANTHROPIC_API_KEY={SENTINEL}\n"), environ={})
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL)
    monkeypatch.setattr(config, "get_settings", lambda: s)
    return s


def test_key_is_loaded_but_hidden_in_every_representation(secret_settings):
    s = secret_settings
    assert s.anthropic_api_key is not None
    assert s.anthropic_api_key.get_secret_value() == SENTINEL  # usable where it is sent
    shown = [repr(s), str(s), f"{s}", s.model_dump_json(), json.dumps(s.model_dump(), default=str)]
    for text in shown:
        assert SENTINEL not in text
    assert "**********" in s.model_dump_json()


def test_key_never_appears_in_logs_even_for_a_bad_env_file(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    bad = env_file(
        tmp_path,
        f"ANTHROPIC_API_KEY {SENTINEL}\n{SENTINEL}\nANTHROPIC_API_KEY={SENTINEL}\n",
    )
    s = load_settings(bad, environ={})
    assert s.anthropic_api_key is not None  # the good line still counts
    assert "line 1" in caplog.text and "line 2" in caplog.text
    assert SENTINEL not in caplog.text


def test_unreadable_env_file_message_has_no_contents(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    p = tmp_path / ".env"
    p.write_bytes(b"ANTHROPIC_API_KEY=" + SENTINEL.encode() + b"\xff\xfe\n")
    s = load_settings(p, environ={})
    assert s.anthropic_api_key is None
    assert "Couldn't read .env" in caplog.text
    assert SENTINEL not in caplog.text


def _nearby(**_):
    now = datetime(2026, 11, 3, tzinfo=UTC)
    return NearbyResult(
        started_at=now,
        finished_at=now,
        room_network=None,
        wifi_method=None,
        checks=[],
        heard=HeardCounts(),
    )


def test_api_responses_and_errors_never_contain_the_key(secret_settings, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(main, "run_nearby_check", _nearby)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        bodies = [
            client.get("/api/health").text,
            client.get("/openapi.json").text,
            client.post("/api/nearby", json={}).text,
        ]

        def boom(**_):
            raise RuntimeError("nearby check failed")

        monkeypatch.setattr(main, "run_nearby_check", boom)
        error = client.post("/api/nearby", json={})
        bodies.append(error.text)
    assert error.status_code == 500
    for body in bodies:
        assert SENTINEL not in body
    assert SENTINEL not in caplog.text


def test_cli_output_never_contains_the_key(secret_settings, monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_nearby_check", _nearby)
    cli.main(["nearby"])
    cli.main(["nearby", "--json"])
    out = capsys.readouterr()
    assert SENTINEL not in out.out + out.err


def test_no_code_logs_or_prints_a_secret_value():
    """Raw keys are only taken with get_secret_value(), and never inside log or print calls."""
    for path in (ROOT / "app").rglob("*.py"):
        for n, line in enumerate(path.read_text("utf-8").splitlines(), 1):
            if "get_secret_value()" in line:
                assert not re.search(r"\b(log\.\w+|print|logging\.\w+)\(", line), f"{path}:{n}"
                assert "raise" not in line and 'f"' not in line, f"{path}:{n}"
