"""Scan coverage: what each part of a check managed to do, from the real check statuses only.

Every check status (ran, skipped, failed) belongs to one plain area, such as "Finding devices"
or "Bluetooth". An area is Completed when all of its checks ran, Not run when none did, and
Limited in between, with a one-line reason taken from the first check that didn't run. The
Results screen and the PDF report show the same table, so a check that didn't fully run is
never mistaken for one that found nothing.
"""

from __future__ import annotations

import re

from app.discovery.messages import MESSAGES
from app.discovery.models import CheckStatus, CoverageItem, CoverageState, DiscoveryResult

# (area id, label, the check names that belong to it), in the order the table lists them.
AREAS: list[tuple[str, str, tuple[str, ...]]] = [
    (
        "devices",
        "Finding devices on this network",
        ("passive_listen", "mdns", "arp_sweep", "ssdp", "onvif"),
    ),
    ("services", "Identifying devices", ("vendor_lookup", "port_check", "identity_check")),
    (
        "router",
        "Checking the router and network",
        ("wifi_encryption", "dns", "arp", "dhcp", "upnp"),
    ),
    ("known_issues", "Known-issue lookups", ("cve",)),
    ("nearby_wifi", "Nearby Wi-Fi", ("nearby_wifi", "lookalike", "wps")),
    ("bluetooth", "Bluetooth", ("bluetooth",)),
]

# A listening-only check skips the parts that need permission. Every one says the same plain
# reason, the user's own choice: "Not checked: you chose a listen-only check".
PASSIVE_REASON = "you chose a listen-only check"

# Short reasons for the table, by the message code behind a check's reason. Anything else
# falls back to the check's own message.
SHORT_REASON = {
    "no_network": "not connected to a network",
    "npcap_missing": "the Npcap driver isn't installed",
    "scanner_not_started": "the scanner couldn't start",
    "scanner_unavailable": "the scanner stopped during this step",
    "permission": "the scanner couldn't start",
    "subnet_too_large": "large shared network, so listening only",
    "client_isolation": "this network hides devices from each other",
    "nmap_missing": "Nmap isn't installed",
    "nmap_failed": "the service check couldn't run",
    "no_swept_hosts": "the network sweep found no devices to check",
    "partly_identified": "some devices didn't answer in time",
    "not_wifi": "connected by cable, so there's no Wi-Fi encryption to check",
    "wifi_unreadable": "couldn't read the Wi-Fi connection details",
    "dns_unclear": "address lookups didn't answer clearly",
    "no_listener": "the network listener wasn't running",
    "no_dhcp_offer": "no device answered the address request",
    "offline": "you chose not to look anything up online",
    "no_models": "no device shared a model name to look up",
    "nvd_unavailable": "the vulnerability database didn't answer",
    "location_off": "Windows Location is off",
    "no_wifi": "Wi-Fi is off",
    "bluetooth_off": "Bluetooth is off",
    "nearby_unreadable": "couldn't read the list of nearby networks",
    "no_room_network": "RoomCheck doesn't know your Wi-Fi network's name",
    "wps_unknown": "WPS couldn't be read this time",
    "nearby_wifi_failed": "the list of nearby Wi-Fi networks couldn't be read",
    "nearby_off": "you chose not to run the nearby check",
    "nearby_only": "this was a nearby-only check",
    "timeout": "the {check} check took too long and was stopped",
    "internal": "something went wrong in this step",
}
_CODE_OF = {text: code for code, text in MESSAGES.items()}

# What each check is called in a reason that names it ("Not checked: the second-address-server
# check took too long and was stopped"). Lowercase where the word allows.
CHECK_NOUN = {
    "passive_listen": "listening",
    "mdns": "device-announcement",
    "arp_sweep": "network-sweep",
    "ssdp": "UPnP-announcement",
    "onvif": "camera-discovery",
    "vendor_lookup": "maker-lookup",
    "port_check": "service",
    "identity_check": "device-identity",
    "wifi_encryption": "Wi-Fi encryption",
    "dns": "address-lookup",
    "arp": "router-answer",
    "dhcp": "second-address-server",
    "upnp": "UPnP",
    "cve": "known-issue",
    "nearby_wifi": "nearby Wi-Fi",
    "lookalike": "lookalike-network",
    "wps": "WPS",
    "bluetooth": "Bluetooth",
}


def _reason(area: str, check: CheckStatus) -> str:
    code = _CODE_OF.get(check.reason or "")
    if code == "passive_mode":
        return PASSIVE_REASON
    if code in SHORT_REASON:
        return SHORT_REASON[code].format(check=CHECK_NOUN.get(check.name, "this"))
    if check.reason:
        return short_phrase(check.reason)
    return "it wasn't checked this time"


_NOT_CHECKED = re.compile(r"^\s*not checked\s*[:,]?\s*(because\s+)?", re.IGNORECASE)


def short_phrase(message: str) -> str:
    """A check's message as a short phrase for "Not checked: <reason>": its first sentence,
    without its own "Not checked" opening (so the row never says it twice) or the full stop,
    e.g. "Not checked, because you chose a listen-only check." -> "you chose a listen-only
    check"."""
    first = re.split(r"(?<=\.)\s", message.strip(), maxsplit=1)[0]
    text = _NOT_CHECKED.sub("", first).rstrip(".").strip()
    return text or "it wasn't checked this time"


def _area_of(name: str) -> str:
    return next((area for area, _, names in AREAS if name in names), "")


def coverage(result: DiscoveryResult) -> list[CoverageItem]:
    """One row per area that this check had anything to say about. Also gives each check that
    didn't run its short reason, for the per-check rows of Coverage and limits."""
    for c in result.checks:
        c.short_reason = None if c.status == "ran" else _reason(_area_of(c.name), c)
    by_name = {c.name: c for c in result.checks}
    rows: list[CoverageItem] = []
    for area, label, names in AREAS:
        checks = [by_name[n] for n in names if n in by_name]
        if not checks:
            continue  # e.g. a nearby-only check has no device rows
        missed = [c for c in checks if c.status != "ran"]
        if not missed:
            rows.append(CoverageItem(area=area, label=label, state="completed"))
            continue
        # A skipped "listen only" check explains the area better than a later failure.
        first = next((c for c in missed if c.status == "skipped"), missed[0])
        state: CoverageState = "not_run" if len(missed) == len(checks) else "limited"
        rows.append(
            CoverageItem(
                area=area,
                label=label,
                state=state,
                reason=_reason(area, first),
                reason_code=_CODE_OF.get(first.reason or ""),
            )
        )
    return rows


def is_partial(rows: list[CoverageItem]) -> bool:
    return any(r.state != "completed" for r in rows)


# The shared vocabulary (app/vocabulary.py): Checked, or Not checked (partly or at all).
STATE_TEXT = {"completed": "Checked", "limited": "Not checked (partly)", "not_run": "Not checked"}


def line(row: CoverageItem) -> str:
    """'Not checked (partly): listening only, no permission to check services'."""
    text = STATE_TEXT[row.state]
    return f"{text}: {row.reason}" if row.reason else text


# --- The same counting as the Results screen (web/src/results/summary.ts) ---------------------

# The checks that look for something to flag, and the rules each one feeds (as on Results, from
# web/src/components/links.ts): one that ran and flagged nothing reads "Not detected".
DETECTING: dict[str, tuple[str, ...]] = {
    "wifi_encryption": ("R-WIFI-ENC",),
    "dns": ("R-DNS",),
    "arp": ("R-ARP",),
    "dhcp": ("R-DHCP",),
    "upnp": ("R-UPNP",),
    "cve": ("R-CVE",),
    "nearby_wifi": ("R-HIDDEN", "R-OPEN", "R-CAMHOT"),
    "lookalike": ("R-TWIN", "R-TWIN-VENDOR", "R-TWIN-DOWNGRADE"),
    "wps": ("R-WPS",),
    "bluetooth": ("R-TRACKER",),
}


# Checks that count what they heard: their row says so, whatever was flagged.
COUNTING = {
    "passive_listen",
    "mdns",
    "arp_sweep",
    "ssdp",
    "onvif",
    "vendor_lookup",
    "port_check",
    "identity_check",
    "nearby_wifi",
    "bluetooth",
}


def row_text(check: CheckStatus, flagged: bool) -> str:
    """A check that ran, in its own words (en.json results.limits.rows, the same words as
    Results): what it heard, or what "nothing flagged" means for it. A check that ran with a
    note (e.g. no address server answered) shows the note; one that flagged something says
    "Checked", since its finding is above. Never "safe" or "passed"."""
    from app.questions import has_text, text  # the page's strings (no import cycle)

    key = f"results.limits.rows.{check.name}"
    if check.reason:
        note = short_phrase(check.reason)
        return note[:1].upper() + note[1:]
    if check.name in COUNTING and has_text(key, check.found):
        return text(key, count=check.found)
    if not flagged and has_text(key, check.found):
        return text(key, count=check.found)
    return "Checked"


def check_rows(result: DiscoveryResult) -> list[tuple[str, str]]:
    """One (label, result) row per check, worded as on Results: the check's own words when it
    ran, or "Not checked: <short reason>"."""
    fired = {f.rule_id for f in result.findings}
    rows: list[tuple[str, str]] = []
    for c in result.checks:
        if c.status != "ran":
            reason = c.short_reason or _reason(_area_of(c.name), c)
            rows.append((c.label, f"Not checked: {reason}" if reason else "Not checked"))
        else:
            flagged = c.name in DETECTING and bool(fired & set(DETECTING[c.name]))
            rows.append((c.label, row_text(c, flagged)))
    return rows


# The checks that find devices (the "Finding devices" area): the total row follows them.
FINDING = AREAS[0][2]


def devices_total(result: DiscoveryResult) -> tuple[str, str] | None:
    """The row that makes the device counts add up: every device heard, each counted once,
    the same number as the summary's "Heard 9 devices". None when no device check ran."""
    from app.questions import text

    if not any(c.name in FINDING and c.status == "ran" for c in result.checks):
        return None
    n = len(result.devices)
    return text("results.limits.totalLabel"), text("results.limits.total", count=n)


def table_rows(result: DiscoveryResult) -> list[tuple[str, str]]:
    """The Coverage and limits table as Results shows it: one row per check, with the total
    row straight after the device-finding checks. The total isn't a check, so check_counts
    and "N checks" never count it."""
    rows = check_rows(result)
    total = devices_total(result)
    if total is None:
        return rows
    last = max((i for i, c in enumerate(result.checks) if c.name in FINDING), default=-1)
    return [*rows[: last + 1], total, *rows[last + 1 :]]


def check_counts(result: DiscoveryResult) -> tuple[int, int]:
    """(checked, not checked), counting checks as Results does: "8 of 10 checks ran"."""
    checked = sum(1 for c in result.checks if c.status == "ran")
    return checked, len(result.checks) - checked
