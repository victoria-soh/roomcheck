"""Command-line check for development.

python -m app.cli discover [--consent]   full check, including the nearby check
python -m app.cli nearby                 nearby Wi-Fi and Bluetooth only
python -m app.cli locate                 nearby check, then warmer/colder for one item
python -m app.cli report [--consent]     full check, explanations and a timestamped PDF
python -m app.cli verify REPORT.pdf      recompute the hash and check the timestamp
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from app.baseline.store import BaselineStore, DpapiProtector, default_store_path
from app.config import get_settings
from app.discovery.messages import message_for
from app.discovery.models import CheckStatus, Device, DiscoveryResult
from app.discovery.runner import DEFAULT_DURATION_SECONDS
from app.explain import ai
from app.explain.models import Explanations
from app.explain.service import explain
from app.handover.session import HandoverSession
from app.questions import text
from app.report import render, tamper
from app.rules.models import Finding, RoomSummary
from app.scan import run_scan
from app.scanner import ScannerError, ScannerProcess
from app.wireless.locator import LocatorTarget, bar, locate, source_for
from app.wireless.models import HeardCounts, NearbyItem
from app.wireless.survey import NearbyResult, run_nearby_check
from app.wireless.wlanapi import WirelessError


def urgency(severity: str) -> str:
    """The plain word for a priority, as on the dashboard and in the report."""
    return text(f"results.severity.{severity}")


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
        print(f"  {urgency(f.severity)} - {f.title}  [{f.rule_id}, {f.confidence_band}]")
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


def _print_nearby(items: Sequence[NearbyItem], heard: HeardCounts | None, room: str | None) -> None:
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

    rep = sub.add_parser("report", help="full check, then a timestamped PDF handover report")
    rep.add_argument("--consent", action="store_true", help="as for discover: allow active probes")
    rep.add_argument("--duration", type=int, default=DEFAULT_DURATION_SECONDS)
    rep.add_argument("--room-label", help="optional label for the report, e.g. 'Room 4B'")
    rep.add_argument("--room-network", help=room_help)
    rep.add_argument("--no-nearby", action="store_true", help="skip nearby Wi-Fi and Bluetooth")
    rep.add_argument("--no-ai", action="store_true", help="use the standard explanations only")
    rep.add_argument(
        "--offline", action="store_true", help="no outside calls at all: no NVD, AI or timestamp"
    )
    rep.add_argument("--out", type=Path, help="folder for the report files")

    ver = sub.add_parser("verify", help="check a report's hash and timestamp")
    ver.add_argument("pdf", type=Path)
    ver.add_argument("--tsr", type=Path, help="timestamp token (default: next to the PDF)")
    ver.add_argument("--sha256", type=Path, help="hash file (default: next to the PDF)")
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
    if args.command == "verify":
        return _verify_command(args.pdf, args.tsr, args.sha256)
    if args.command == "report" and not 10 <= args.duration <= 120:
        parser.error("--duration must be between 10 and 120 seconds")
    if args.command == "report":
        return _report_command(args)

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


def print_explanations(result: DiscoveryResult, explanations: Explanations) -> None:
    reason = f" - {explanations.ai_reason_text}" if explanations.ai_reason_text else ""
    print(f"\nExplanations (AI: {explanations.ai_status}{reason}):")
    for rule_id, check in explanations.ai_rejected.items():
        print(f"  ! AI text for {rule_id} rejected by the {check!r} check")
    for f in result.findings:
        e = explanations.for_finding(f.id)
        if e is None:
            continue
        print(f"\n  {urgency(f.severity)} - {f.title}  [{f.rule_id}]")
        print(f"    {e.explanation}")
        print(f"    Why it matters: {e.why_it_matters}")
        print(f"    ({e.label})")
    m = explanations.landlord_message
    print("\nMessage to the host (draft):")
    if m is None:
        print("  No open findings to ask about.")
    else:
        for line in m.text.splitlines():
            print(f"  {line}")
        print(f"  ({m.label} {m.note})")


def _report_command(args: argparse.Namespace) -> int:
    online = not args.offline
    if online and not args.no_ai:
        ai.start_warm_up(get_settings())  # warms during the scan; failure is logged, not raised
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
            online=online,
            include_nearby=not args.no_nearby,
            typed_room=args.room_network,
        )
    finally:
        proc.stop()
    result.explanations = explain(
        result.findings, result.devices, result.nearby_items, online=online and not args.no_ai
    )
    # The handover data saved on this laptop (tasks, statuses, answers, the physical check), so
    # the report asks the host about exactly the open tasks it lists, as from the dashboard.
    session = HandoverSession(BaselineStore(default_store_path(), DpapiProtector()))
    handover = session.state_for(result)
    comparison = session.comparison(result) if session.saved else None
    compare_state = "ready" if comparison else session.info().state
    print_result(result)
    print_explanations(result, result.explanations)
    try:
        report = render.make_report(
            result,
            result.explanations,
            room_label=args.room_label,
            out_dir=args.out,
            online=online,
            tsa_url=get_settings().tsa_url,
            handover=handover,
            compare_state=compare_state,
            comparison=comparison,
        )
    except render.PdfUnavailable:
        print(f"\n! {message_for('pdf_unavailable')}")
        return 1
    files = report.files
    print(f"\nReport: {files.pdf}")
    print(f"SHA-256: {files.sha256}  (saved in {files.sha256_file.name})")
    if files.tsr is not None and files.timestamped_at is not None:
        print(
            f"Timestamp: {files.timestamped_at:%d %b %Y, %H:%M:%S} UTC  (saved in {files.tsr.name})"
        )
    else:
        print(f"! {files.timestamp_message}")
    return 0


def _verify_command(pdf: Path, tsr: Path | None, sha: Path | None) -> int:
    if not pdf.is_file():
        print(f"No such file: {pdf}")
        return 2
    tsr = tsr or pdf.with_suffix(".tsr")
    sha = sha or pdf.with_suffix(".sha256")
    expected = tamper.read_hash_file(sha.read_text("ascii", "replace")) if sha.is_file() else None
    result = tamper.verify(pdf.read_bytes(), tsr.read_bytes() if tsr.is_file() else None, expected)
    print(f"SHA-256:   {result.sha256}")
    print(f"Hash file: {result.hash_file}")
    print(
        f"Timestamp: {result.token}"
        + (f" ({result.timestamped_at:%d %b %Y, %H:%M:%S} UTC)" if result.timestamped_at else "")
    )
    print(f"\n{'OK' if result.ok else 'NOT VERIFIED'}: {result.message}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
