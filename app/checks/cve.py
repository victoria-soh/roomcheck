"""R-CVE input: known issues NVD lists for models a device reported about itself.

Optional outside call (PLAN.md): only a maker word and a model name are sent, never IPs, MACs
or network names. Two steps per model, both cached in SQLite:
  1. CPE API keyword search "<maker> <model>" to find NVD's product name for it.
  2. CVE API with virtualMatchString=cpe:2.3:<part>:<vendor>:<product>, so any firmware
     version matches. The exact version is usually unconfirmed, so results are phrased as
     "known issues reported for this model".
Rate limits: 5 requests per 30 s, or 50 with NVD_API_KEY. A 403/503 skips the lookup.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx

from app.checks.models import CveMatch
from app.discovery.models import Device

CPE_URL = "https://services.nvd.nist.gov/rest/json/cpes/2.0"
CVE_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
WINDOW_SECONDS = 30.0
LIMIT_WITHOUT_KEY = 5
LIMIT_WITH_KEY = 50
CACHE_TTL_SECONDS = 7 * 24 * 3600
REQUEST_TIMEOUT_SECONDS = 15.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_PRODUCTS_PER_MODEL = 2
MAX_CVE_IDS = 5

_CORP_WORDS = re.compile(
    r"\b(co|ltd|inc|corp|corporation|company|limited|llc|gmbh|technologies|technology|"
    r"systems|digital|electronics|international)\b\.?",
    re.IGNORECASE,
)
_CHINA_CITY = re.compile(r"^(hangzhou|zhejiang|shenzhen|beijing|shanghai)\s+", re.IGNORECASE)


class NvdUnavailable(Exception):
    """Rate-limited, refused or unreachable. The lookup is skipped, not failed."""


def default_cache_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "RoomCheck" / "nvd_cache.sqlite3"


class CveCache:
    def __init__(
        self, path: Path, ttl: float = CACHE_TTL_SECONDS, clock: Callable[[], float] = time.time
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, fetched REAL, body TEXT)"
        )
        self._ttl = ttl
        self._clock = clock

    def get(self, key: str) -> Any | None:
        row = self._db.execute(
            "SELECT fetched, body FROM responses WHERE key = ?", (key,)
        ).fetchone()
        if row is None or self._clock() - row[0] > self._ttl:
            return None
        return json.loads(row[1])

    def put(self, key: str, value: Any) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO responses VALUES (?, ?, ?)",
            (key, self._clock(), json.dumps(value)),
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()


class RateLimiter:
    """At most `limit` requests in any `window` seconds. Never waits past `deadline`."""

    def __init__(
        self,
        limit: int,
        window: float = WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.limit, self.window = limit, window
        self._clock, self._sleep = clock, sleep
        self._sent: deque[float] = deque()

    def acquire(self, deadline: float) -> bool:
        now = self._clock()
        while self._sent and now - self._sent[0] >= self.window:
            self._sent.popleft()
        if len(self._sent) >= self.limit:
            wait = self.window - (now - self._sent[0])
            if now + wait > deadline:
                return False
            self._sleep(wait)
            self._sent.popleft()
        self._sent.append(self._clock())
        return True


def maker_word(maker: str) -> str | None:
    """'Hangzhou Hikvision Digital Technology Co.,Ltd.' -> 'hikvision'; 'TP-Link' -> 'tp-link'."""
    text = _CHINA_CITY.sub("", maker.replace(",", " "))
    text = _CORP_WORDS.sub(" ", text)
    words = [w.strip(".").lower() for w in text.split() if w.strip(".")]
    return words[0] if words else None


def _cpe_unescape(s: str) -> str:
    return s.replace("\\", "")


def _strip_maker(word: str, model: str) -> str:
    """'Sonos Arc' with maker 'sonos' -> 'Arc', so the maker isn't searched twice."""
    model = " ".join(model.split())
    if model.lower().startswith(word + " "):
        return model[len(word) + 1 :]
    return model


def _scope_value(scopes: list[str], kind: str) -> str | None:
    """ONVIF scope values are URL-encoded: 'onvif://www.onvif.org/name/tapo%20tc70'."""
    raw = next((x.rsplit("/", 1)[-1] for x in scopes if f"/{kind}/" in x), None)
    if raw is None:
        return None
    return " ".join(unquote(raw).split()) or None


def model_queries(device: Device) -> list[tuple[str, str]]:
    """(maker word, model) pairs the device itself reported: UPnP description or ONVIF scopes."""
    out: list[tuple[str, str]] = []
    ident = device.identity
    if ident and ident.upnp and ident.upnp.manufacturer and ident.upnp.model_name:
        word = maker_word(ident.upnp.manufacturer)
        if word:
            out.append((word, _strip_maker(word, ident.upnp.model_name)))
    for s in device.services:
        if s.kind != "onvif":
            continue
        scopes = s.detail.get("scopes", "").split()
        hardware = _scope_value(scopes, "hardware")
        # The ONVIF "name" is often a product line ("tapo tc70"), so prefer the registered
        # MAC maker and fall back to the name only for private or unknown MACs.
        maker = device.vendor or _scope_value(scopes, "name")
        word = maker_word(maker) if maker else None
        if word and hardware:
            out.append((word, _strip_maker(word, hardware)))
    unique: list[tuple[str, str]] = []
    for q in out:
        if q not in unique:
            unique.append(q)
    return unique


def pick_products(cpe_names: list[str], word: str, model: str) -> list[str]:
    """NVD products from a keyword search that match the maker and contain the model.

    Returns "cpe:2.3:<part>:<vendor>:<product>" prefixes, firmware ('o') first.
    """
    model_token = re.sub(r"\s+", "_", model.strip().lower())
    found: list[tuple[int, str]] = []
    for name in cpe_names:
        parts = re.split(r"(?<!\\):", name)
        if len(parts) < 5 or parts[2] not in ("o", "h"):
            continue
        vendor, product = parts[3], parts[4]
        if word.replace("-", "") not in vendor.replace("-", "").replace("_", ""):
            continue
        if model_token not in _cpe_unescape(product):
            continue
        prefix = ":".join(parts[:5])
        if all(prefix != p for _, p in found):
            found.append((0 if parts[2] == "o" else 1, prefix))
    return [p for _, p in sorted(found)][:MAX_PRODUCTS_PER_MODEL]


def cpe_names(body: dict[str, Any]) -> list[str]:
    return [
        str(p.get("cpe", {}).get("cpeName", ""))
        for p in body.get("products") or []
        if isinstance(p, dict) and isinstance(p.get("cpe"), dict)
    ]


def summarise_cves(body: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    vulns = body.get("vulnerabilities") or []
    items = [v.get("cve", {}) for v in vulns if isinstance(v, dict)]
    items.sort(key=lambda c: str(c.get("published", "")), reverse=True)
    ids = [str(c["id"]) for c in items if "id" in c]
    exploited = [str(c["id"]) for c in items if "id" in c and "cisaExploitAdd" in c]
    return int(body.get("totalResults") or len(ids)), ids[:MAX_CVE_IDS], exploited[:MAX_CVE_IDS]


@dataclass
class NvdClient:
    cache: CveCache
    limiter: RateLimiter
    api_key: str | None = None
    transport: httpx.BaseTransport | None = None
    clock: Callable[[], float] = time.monotonic

    def _get(
        self,
        url: str,
        params: dict[str, str | int],
        deadline: float,
        reduce: Callable[[dict[str, Any]], Any],
    ) -> Any:
        """GET from NVD, or from the cache. Only `reduce(body)` is cached, not whole replies."""
        key = url + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        if not self.limiter.acquire(deadline):
            raise NvdUnavailable("rate limit")
        headers = {"User-Agent": "RoomCheck/0.1"}
        if self.api_key:
            headers["apiKey"] = self.api_key
        try:
            with httpx.Client(
                timeout=REQUEST_TIMEOUT_SECONDS, transport=self.transport, trust_env=True
            ) as client:
                resp = client.get(url, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise NvdUnavailable("unreachable") from e
        if resp.status_code in (403, 429, 503) or resp.status_code >= 500:
            raise NvdUnavailable(f"HTTP {resp.status_code}")
        if resp.status_code != 200 or len(resp.content) > MAX_RESPONSE_BYTES:
            raise NvdUnavailable(f"HTTP {resp.status_code}")
        try:
            body = resp.json()
        except ValueError as e:
            raise NvdUnavailable("unreadable reply") from e
        if not isinstance(body, dict):
            raise NvdUnavailable("unreadable reply")
        value = reduce(body)
        self.cache.put(key, value)
        return value

    def lookup(self, word: str, model: str, deadline: float) -> list[CveMatch]:
        names = self._get(
            CPE_URL,
            {"keywordSearch": f"{word} {model}", "resultsPerPage": 50},
            deadline,
            cpe_names,
        )
        matches = []
        # Firmware product first; the hardware entry usually lists the same CVEs, so stop at
        # the first product with any results.
        for prefix in pick_products(names, word, model):
            total, ids, exploited = self._get(
                CVE_URL,
                {"virtualMatchString": prefix, "resultsPerPage": 50},
                deadline,
                lambda body: list(summarise_cves(body)),
            )
            if total:
                matches.append(
                    CveMatch(
                        model=f"{word} {model}",
                        cpe=prefix,
                        total=total,
                        cve_ids=ids,
                        exploited=exploited,
                    )
                )
                break
        return matches


def make_client(cache_path: Path | None = None) -> NvdClient:
    api_key = os.environ.get("NVD_API_KEY") or None
    limit = LIMIT_WITH_KEY if api_key else LIMIT_WITHOUT_KEY
    return NvdClient(
        cache=CveCache(cache_path or default_cache_path()),
        limiter=RateLimiter(limit),
        api_key=api_key,
    )
