"""Command-line check for development.

    python -m app.cli discover [--consent]   full check, including the nearby check
    python -m app.cli nearby                 nearby Wi-Fi and Bluetooth only
    python -m app.cli locate                 nearby check, then warmer/colder for one item
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from app.discovery.messages import message_for
from app.discovery.models import CheckStatus, Device, DiscoveryResult
from app.discovery.runner import DEFAULT_DURATION_SECONDS
from app.rules.models import Finding, RoomSummary
from app.scan import run_scan
from app.scanner import ScannerError, ScannerProcess
from app.wireless.locator import LocatorTarget, bar, locate, source_for
from app.wireless.models import HeardCounts, NearbyItem
from app.wireless.survey import NearbyResult, run_nearby_check
from app.wireless.wlanapi import WirelessError


def _print_device(d: Device, details: bool) -> None:
    fp = d.fingerprint
    tags = ["gateway"] if d.is_gateway else []
    tags += ["private MAC"] if d.mac_is_random else []
    print(f"\n  {d.ip or '?'}  {d.mac or 'MAC not seen'}  maker: {d.vendor or 'unknown'}")
    if fp is not None:
        pct = int(fp.confidence * 100)  # round down so 0.798 never shows as 80% "Possible"
        print(f"    {fp.label}: {fp.band} ({pct}%)  [{fp.identification} identification]")
        for e in fp.evidence:
            print(f"      - {e.text}  (+{e.weight})")
        for note in fp.notes:
            print(f"      - {note}  (not scored)")
        for other in fp.other_types:
            print(f"    also: {other.label} {other.band} ({int(other.score * 100)}%)")
        if details:
            for weak in fp.weak_types:
                hints = "; ".join(e.text for e in weak.evidence)
                print(f"      weak hint, {weak.label} ({int(weak.score * 100)}%): {hints}")
    if d.hostnames:
        print(f"    names: {', '.join(d.hostnames)}")
    if d.identity is not None:
        ports = d.identity.open_ports
        shown = "not checked" if ports is None else (", ".join(map(str, ports)) or "none")
        print(f"    open ports: {shown}")
        for problem in d.identity.problems:
            print(f"    ! {problem}")
    print(f"    found by: {', '.join(d.sources)}{'  ' + ' '.join(tags) if tags else ''}")


def _print_summary(s: RoomSummary | None, findings: Sequence[Finding]) -> None:
    if s is None:
        return
    icon = {"Needs attention": "[!!]", "Check these items": "[!]"}.get(s.status, "[i]")
    print()
    print(f"{icon} {s.status}  ({s.high} high, {s.medium} medium, {s.other} other)")
    for f in findings:
        print()
        print(f"  {f.severity.upper()} - {f.title}  [{f.rule_id}, {f.confidence_band}]")
        for e in f.evidence:
            print(f"      - {e}")
        print(f"    Next step: {f.next_step}")
        for g in f.guidance:
            print(f"      * {g}")
    if s.not_checked:
        print()
        print("  Not checked this time:")
        for item in s.not_checked:
            print(f"    - {item}")
    print()
    print("  What this scan can't see:")
    for item in s.cant_see:
        print(f"    - {item}")


def _print_checks(checks: Sequence[CheckStatus]) -> None:
    print("\nChecks:")
    for c in checks:
        extra = f" ({c.found})" if c.status == "ran" else ""
        reason = f": {c.reason}" if c.reason else ""
        print(f"  {c.status:7} {c.label}{extra}{reason}")


def _print_nearby(
    items: Sequence[NearbyItem], heard: HeardCounts | None, room: str | None
) -> None:
    if heard is None:
        return
    compared = f'"{room}"' if room else "unknown"
    print(f"\nNearby (compared with your Wi-Fi: {compared}):")
    if not items:
        print("  No nearby item was flagged.")
    for n, i in enumerate(items, 1):
        bits = [x for x in (i.security, i.band, i.maker and f"maker: {i.maker}") if x]
        print(f"  {n}. {i.label}  {i.signal_dbm} dBm  [{', '.join(i.rule_ids)}]")
        if bits:
            print(f"       {'; '.join(bits)}")
    cats = ", ".join(f"{v} {k}" for k, v in heard.bluetooth_by_category.items())
    print(
        f"  Also heard, then discarded: {heard.wifi_access_points} Wi-Fi access points and "
        f"{heard.bluetooth_devices} Bluetooth devices{f' ({cats})' if cats else ''}."
    )


def print_nearby_result(result: NearbyResult) -> None:
    _print_summary(result.summary, result.findings)
    for msg in result.messages:
        print(f"! {msg}")
    _print_nearby(result.items, result.heard, result.room_network)
    _print_checks(result.checks)
    print()


def print_result(result: DiscoveryResult, details: bool = False) -> None:
    _print_summary(result.summary, result.findings)
    print()
    net = result.network
    if net:
        print(f"Network {net.cidr} via {net.interface}, gateway {net.gateway_ip}")
        print(f"Mode: {result.mode}")
    for msg in result.messages:
        print(f"! {msg}")
    _print_nearby(result.nearby_items, result.nearby_heard, result.room_network)
    _print_checks(result.checks)
    print(f"\nDevices ({len(result.devices)}):", end="")
    for d in result.devices:
        _print_device(d, details)
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="roomcheck")
    sub = parser.add_subparsers(dest="command", required=True)
    disc = sub.add_parser("discover", help="find and identify devices on the network you joined")
    disc.add_argument(
        "--consent",
        action="store_true",
        help="this is my network or I have permission: allow active probes and service checks",
    )
    disc.add_argument("--duration", type=int, default=DEFAULT_DURATION_SECONDS)
    disc.add_argument("--json", action="store_true", help="print the full result as JSON")
    disc.add_argument(
        "--offline", action="store_true", help="don't look up known issues online (NVD)"
    )
    disc.add_argument(
        "--details", action="store_true", help="also show weak hints below the display threshold"
    )
    disc.add_argument("--no-nearby", action="store_true", help="skip nearby Wi-Fi and Bluetooth")
    room_help = "your Wi-Fi's name, if you're not connected to it (to spot copies of it)"
    disc.add_argument("--room-network", help=room_help)

    near = sub.add_parser("nearby", help="nearby Wi-Fi and Bluetooth only (about 30 s)")
    near.add_argument("--room-network", help=room_help)
    near.add_argument("--json", action="store_true", help="print the result as JSON")

    loc = sub.add_parser("locate", help="find a flagged nearby item: warmer or colder")
    loc.add_argument("--room-network", help=room_help)
    loc.add_argument("--item", type=int, help="number of the flagged item to find")
    args = parser.parse_args(argv)

    if args.command == "nearby":
        near_result = run_nearby_check(typed_room=args.room_network)
        if args.json:
            print(near_result.model_dump_json(indent=2))
        else:
            print_nearby_result(near_result)
        return 0
    if args.command == "locate":
        return _locate_command(args.room_network, args.item)

    if not 10 <= args.duration <= 120:
        parser.error("--duration must be between 10 and 120 seconds")

    proc = ScannerProcess()
    try:
        scanner = proc.start()
    except ScannerError:
        scanner = None
    try:
        result = run_scan(
            args.consent,
            scanner,
            args.duration,
            online=not args.offline,
            include_nearby=not args.no_nearby,
            typed_room=args.room_network,
        )
    finally:
        proc.stop()

    if args.json:
        print(result.model_dump_json(indent=2, exclude={"observations"}))
    else:
        print_result(result, args.details)
    return 0


def _pick(items: Sequence[NearbyItem], choice: int | None) -> NearbyItem | None:
    if choice is None:
        if len(items) == 1:
            return items[0]
        try:
            choice = int(input(f"Which item do you want to find (1-{len(items)})? "))
        except (ValueError, EOFError):
            return None
    return items[choice - 1] if 1 <= choice <= len(items) else None


async def _run_locator(target: LocatorTarget) -> None:
    print(f"\nFinding: {target.label}.")
    print("Walk slowly round the room, holding the laptop the same way. Press Ctrl+C to stop.\n")
    message = None
    async for r in locate(target, source_for(target)):
        if r.message and r.message != message:
            print(f"\r{' ' * 72}\r  {r.message}")
        message = r.message
        print(f"\r  {bar(r)}{' ' * 6}", end="", flush=True)


def _locate_command(room: str | None, choice: int | None) -> int:
    print("Running the nearby check first (about 30 s)...")
    result = run_nearby_check(typed_room=room)
    print_nearby_result(result)
    if not result.items:
        print("Nothing nearby was flagged, so there is nothing to find. The locator only works")
        print("on items RoomCheck flagged as a possible risk.")
        return 1
    item = _pick(result.items, choice)
    if item is None:
        print("No item picked.")
        return 1
    target = LocatorTarget(ref=item.ref, kind=item.kind, label=item.label)
    if item.kind == "wifi":
        print(f"\n{message_for('locator_wifi_slow')}")
    try:
        asyncio.run(_run_locator(target))
    except KeyboardInterrupt:
        print("\nStopped. Nothing from the locator was saved.")
    except WirelessError as e:
        print(f"\n{message_for(e.code)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
