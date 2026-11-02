"""Refresh the bundled IEEE OUI list: `uv run python scripts/update_oui.py [--from-file oui.csv]`.

Keeps only the 24-bit prefix and organisation name (no addresses), sorted, so RoomCheck can look
up vendors offline.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

OUI_URL = "https://standards-oui.ieee.org/oui/oui.csv"
OUT = Path(__file__).resolve().parents[1] / "app" / "fingerprint" / "data" / "oui.tsv"


def convert(csv_text: str) -> list[tuple[str, str]]:
    rows = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        prefix = (row.get("Assignment") or "").strip().upper()
        name = " ".join((row.get("Organization Name") or "").split())
        if len(prefix) == 6 and name:
            rows[prefix] = name
    return sorted(rows.items())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-file", type=Path, help="use a downloaded oui.csv instead")
    args = parser.parse_args()
    if args.from_file:
        text = args.from_file.read_text(encoding="utf-8")
    else:
        resp = httpx.get(OUI_URL, timeout=60, headers={"User-Agent": "RoomCheck OUI update"})
        resp.raise_for_status()
        text = resp.text
    rows = convert(text)
    stamp = datetime.now(UTC).date().isoformat()
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        f.write(f"# IEEE MA-L (OUI) registry, {OUI_URL}, fetched {stamp}\n")
        f.writelines(f"{prefix}\t{name}\n" for prefix, name in rows)
    print(f"wrote {len(rows)} prefixes to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
