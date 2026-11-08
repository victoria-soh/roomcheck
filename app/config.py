"""Configuration from `.env` (in the project folder) and the environment.

Real environment variables win over `.env`. Only the keys below are read; anything else in the
file is ignored. API keys are SecretStr: they show as '**********' in repr, str, logs and
JSON, and the raw value is only taken with .get_secret_value() where it is sent. Messages
about a bad `.env` give a line number, never the line itself.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, SecretStr

log = logging.getLogger(__name__)

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
# Fast is enough for explanations (docs/original-plan.md).
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-5-5"
DEFAULT_TSA_URL = "https://freetsa.org/tsr"
KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "NVD_API_KEY", "TSA_URL")


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = DEFAULT_ANTHROPIC_MODEL
    nvd_api_key: SecretStr | None = None
    tsa_url: str = DEFAULT_TSA_URL


def parse_env(text: str) -> dict[str, str]:
    """KEY=value lines; blank lines and # comments skipped; optional matching quotes removed."""
    values: dict[str, str] = {}
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if not sep or not key:
            log.warning("Ignoring line %d of .env: expected KEY=value", n)
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key in KEYS:
            values[key] = value
    return values


def load_settings(env_file: Path = ENV_FILE, environ: Mapping[str, str] = os.environ) -> Settings:
    values: dict[str, str] = {}
    try:
        if env_file.is_file():
            values = parse_env(env_file.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError):
        log.warning("Couldn't read .env, so the defaults are used")
    for key in KEYS:
        if environ.get(key):
            values[key] = environ[key]

    def get(key: str) -> str | None:
        return values.get(key) or None

    anthropic_key = get("ANTHROPIC_API_KEY")
    nvd_key = get("NVD_API_KEY")
    return Settings(
        anthropic_api_key=SecretStr(anthropic_key) if anthropic_key else None,
        anthropic_model=get("ANTHROPIC_MODEL") or DEFAULT_ANTHROPIC_MODEL,
        nvd_api_key=SecretStr(nvd_key) if nvd_key else None,
        tsa_url=get("TSA_URL") or DEFAULT_TSA_URL,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
