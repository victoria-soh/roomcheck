"""Load the camera setup-hotspot patterns used by R-CAMHOT."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

HOTSPOT_FILE = Path(__file__).resolve().parent / "hotspot_patterns.yaml"


class PatternSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    regex: str
    label: str
    examples: list[str]


class HotspotFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_vendor_regex: str
    patterns: list[PatternSpec]
    must_not_match: list[str] = []


@dataclass(frozen=True)
class HotspotPattern:
    id: str
    regex: re.Pattern[str]
    label: str


@dataclass(frozen=True)
class Hotspots:
    camera_vendor: re.Pattern[str]
    patterns: tuple[HotspotPattern, ...]
    spec: HotspotFile

    def match_name(self, ssid: str) -> HotspotPattern | None:
        return next((p for p in self.patterns if p.regex.search(ssid)), None)

    def camera_vendor_match(self, vendor: str) -> bool:
        return bool(self.camera_vendor.search(vendor))


@lru_cache(maxsize=4)
def load_hotspots(path: Path = HOTSPOT_FILE) -> Hotspots:
    with path.open(encoding="utf-8") as f:
        spec = HotspotFile.model_validate(yaml.safe_load(f))
    return Hotspots(
        camera_vendor=re.compile(spec.camera_vendor_regex, re.IGNORECASE),
        patterns=tuple(
            HotspotPattern(p.id, re.compile(p.regex, re.IGNORECASE), p.label) for p in spec.patterns
        ),
        spec=spec,
    )
