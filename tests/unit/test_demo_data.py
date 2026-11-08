"""The demo data is what the pipeline makes from its made-up raw inputs, not hand-written."""

import json
import re

from tests.unit import demo_data

DEMO = demo_data.OUT


def test_every_demo_file_is_exactly_the_pipelines_output():
    made = demo_data.render(demo_data.build())
    on_disk = {p.stem: p.read_text("utf-8") for p in DEMO.glob("*.json")}
    assert set(on_disk) == set(made), "run: uv run python -m app.demo_data"
    for name, text in made.items():
        assert on_disk[name] == text, f"{name}.json drifted: run uv run python -m app.demo_data"


def test_the_demo_uses_documentation_addresses_and_made_up_names_only():
    text = "".join(p.read_text("utf-8") for p in DEMO.glob("*.json"))
    ips = set(re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text))
    ips.discard("255.255.255.0")  # the netmask
    assert ips and all(ip.startswith("192.0.2.") for ip in ips), ips
    macs = set(re.findall(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", text, re.I))
    assert all(m.lower()[3:].startswith("00:5e:00:53") for m in macs), macs
    cves = set(re.findall(r"CVE-\d{4}-\d+", text))
    assert cves == {"CVE-2099-0001"}


def test_the_listening_check_says_what_it_skipped():
    result = json.loads((DEMO / "result_listening.json").read_text("utf-8"))
    skipped = {c["name"] for c in result["checks"] if c["status"] == "skipped"}
    assert {"arp_sweep", "onvif", "port_check", "identity_check"} <= skipped
    assert all(
        c["short_reason"] == "you chose a listen-only check"
        for c in result["checks"]
        if c["status"] == "skipped"
    )


def test_the_full_check_never_shows_known_issues_with_the_lookup_not_answering():
    result = json.loads((DEMO / "result_full.json").read_text("utf-8"))
    lookup = next(c for c in result["checks"] if c["name"] == "cve")
    has_issue = any(f["rule_id"] == "R-CVE" for f in result["findings"])
    assert lookup["status"] == "ran" and has_issue
