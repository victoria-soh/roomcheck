"""Command-line check for development: `python -m app.cli discover [--consent]`."""

from __future__ import annotations

import argparse
import sys

from app.discovery.models import Device, DiscoveryResult
from app.discovery.runner import DEFAULT_DURATION_SECONDS
from app.scan import run_scan
from app.scanner import ScannerError, ScannerProcess


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


def _print_summary(result: DiscoveryResult) -> None:
    s = result.summary
    if s is None:
        return
    icon = {"Needs attention": "[!!]", "Check these items": "[!]"}.get(s.status, "[i]")
    print()
    print(f"{icon} {s.status}  ({s.high} high, {s.medium} medium, {s.other} other)")
    for f in result.findings:
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


def print_result(result: DiscoveryResult, details: bool = False) -> None:
    _print_summary(result)
    print()
    net = result.network
    if net:
        print(f"Network {net.cidr} via {net.interface}, gateway {net.gateway_ip}")
        print(f"Mode: {result.mode}")
    for msg in result.messages:
        print(f"! {msg}")
    print("\nChecks:")
    for c in result.checks:
        extra = f" ({c.found})" if c.status == "ran" else ""
        reason = f": {c.reason}" if c.reason else ""
        print(f"  {c.status:7} {c.label}{extra}{reason}")
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
    args = parser.parse_args(argv)

    if not 10 <= args.duration <= 120:
        parser.error("--duration must be between 10 and 120 seconds")

    proc = ScannerProcess()
    try:
        scanner = proc.start()
    except ScannerError:
        scanner = None
    try:
        result = run_scan(args.consent, scanner, args.duration, online=not args.offline)
    finally:
        proc.stop()

    if args.json:
        print(result.model_dump_json(indent=2, exclude={"observations"}))
    else:
        print_result(result, args.details)
    return 0


if __name__ == "__main__":
    sys.exit(main())
