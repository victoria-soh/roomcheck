"""R-DNS input: is the network's DNS answering honestly? Uses only the system resolver.

(a) A random name under example.com must not exist (NXDOMAIN). An answer means the resolver
    invents results, which is how some networks redirect or intercept traffic.
(b) Well-known public names must not resolve to private, reserved or other non-public
    addresses.
docs/original-plan.md's DoH comparison is left out on purpose: it would add an outside call, and it
was only ever context, never a trigger.
"""

from __future__ import annotations

import ipaddress
import secrets
from collections.abc import Callable

from app.checks.models import DnsResult

PUBLIC_DOMAINS = ("example.com", "www.iana.org")
LIFETIME_SECONDS = 3.0

# Resolve one A query: returns ("ok", [ips]), ("nxdomain", []) or ("unclear", []).
Resolve = Callable[[str], tuple[str, list[str]]]


def random_label_name() -> str:
    return f"roomcheck-{secrets.token_hex(8)}.example.com"


def is_non_public(ip: str) -> bool:
    try:
        return not ipaddress.ip_address(ip).is_global
    except ValueError:
        return True


def system_resolve(name: str) -> tuple[str, list[str]]:
    import dns.exception
    import dns.resolver

    resolver = dns.resolver.Resolver()  # configured from the system's DNS settings
    resolver.lifetime = LIFETIME_SECONDS
    try:
        answer = resolver.resolve(name, "A", search=False)
    except dns.resolver.NXDOMAIN:
        return "nxdomain", []
    except dns.resolver.NoAnswer:
        return "ok", []
    except (
        dns.exception.Timeout,
        dns.resolver.NoNameservers,
        dns.resolver.NoResolverConfiguration,
    ):
        return "unclear", []
    return "ok", [r.to_text() for r in answer][:10]


def check_dns(resolve: Resolve = system_resolve, random_name: str | None = None) -> DnsResult:
    name = random_name or random_label_name()
    outcome, answers = resolve(name)
    result = DnsResult(
        random_name=name,
        nxdomain={"nxdomain": True, "ok": False}.get(outcome),
        random_name_answers=answers,
    )
    # "ok" with no addresses is not a hijack: nothing was invented.
    if outcome == "ok" and not answers:
        result.nxdomain = True
    for domain in PUBLIC_DOMAINS:
        outcome, answers = resolve(domain)
        if outcome != "ok":
            continue
        result.checked_domains.append(domain)
        bad = [ip for ip in answers if is_non_public(ip)]
        if bad:
            result.non_public_answers[domain] = bad
    return result


def is_tampered(result: DnsResult) -> bool:
    return result.nxdomain is False or bool(result.non_public_answers)
