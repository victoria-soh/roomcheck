"""Layer 5 report: contents, MAC masking, nothing about neighbours, the saved files, the
timestamp (unreachable and offline), verify (valid, tampered, mismatched, unpinned), and the
API and CLI. Uses a real FreeTSA token recorded once (tests/fixtures/report); no network."""

import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from markupsafe import escape

import app.cli as cli
import app.main as main
from app.checks.models import ArpClaim, NetworkFacts
from app.discovery.models import CheckStatus, DiscoveryResult, NetworkInfo
from app.explain.models import Explanations
from app.explain.service import explain
from app.fingerprint.facts import device_facts
from app.fingerprint.scoring import fingerprint
from app.report import render, tamper
from app.report.masking import mask_mac, mask_text
from app.rules.engine import RoomFacts, evaluate, summarise
from app.wireless.ie import make_security
from app.wireless.models import BssReading, NearbySurvey, RoomNetwork
from app.wireless.survey import aggregate_wifi, flagged_items
from tests.unit import devices as dev

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "report"
SAMPLE_PDF = (FIXTURES / "sample.pdf").read_bytes()
SAMPLE_TSR = (FIXTURES / "sample.tsr").read_bytes()
CACERT = (Path(tamper.__file__).parent / "data" / "freetsa_cacert.pem").read_bytes()
T0 = datetime(2026, 11, 3, 4, 0, tzinfo=UTC)
T1 = datetime(2026, 11, 3, 4, 2, tzinfo=UTC)
PLAN_OFFLINE = (
    "Couldn't get a trusted timestamp. Email the report to yourself now to keep a dated copy."
)
SAFE = re.compile(r"\bsafe(ly|ty)?\b|no risk", re.IGNORECASE)
FULL_MAC = re.compile(r"\b[0-9a-f]{2}(:[0-9a-f]{2}){5}\b", re.IGNORECASE)

NET = NetworkInfo(
    interface="Wi-Fi",
    own_ip="192.0.2.60",
    own_mac="c4:0f:08:11:22:33",
    gateway_ip="192.0.2.1",
    netmask="255.255.252.0",
    cidr="192.0.2.0/24",
    prefixlen=22,
    sweep_allowed=True,
)
WPA2 = make_security("wpa2", pairwise=["CCMP"])
OPEN = make_security("open")


def scored(d):
    d.fingerprint = fingerprint(device_facts(d), "full")
    return d


def scan_result() -> DiscoveryResult:
    """A camera, the router answered for by a second (private) MAC, an open twin of the room
    network, and a neighbour's open network."""
    devices = [scored(dev.hikvision_camera()), scored(dev.tp_link_gateway())]
    net = NetworkFacts(
        arp_claims=[
            ArpClaim(ip="192.0.2.1", mac="cc:ba:bd:00:00:01", first_seen=T0, last_seen=T1),
            ArpClaim(ip="192.0.2.1", mac="02:00:00:00:00:66", first_seen=T0, last_seen=T1),
        ]
    )
    rounds = [
        [
            BssReading(bssid="cc:ba:bd:00:10:d9", ssid="Example-Home", rssi_dbm=-40, security=WPA2),
            BssReading(bssid="9a:3b:4c:00:11:22", ssid="Example-Home", rssi_dbm=-42, security=OPEN),
            BssReading(
                bssid="00:0c:6e:00:00:09", ssid="Neighbour-Open", rssi_dbm=-80, security=OPEN
            ),
        ]
    ] * 2
    survey = NearbySurvey(
        room=RoomNetwork(
            ssid="Example-Home", bssid="cc:ba:bd:00:10:d9", security=WPA2, source="connected"
        ),
        access_points=aggregate_wifi(rounds),
        wifi_method="wlanapi",
        ble_devices=[],
        ble_rounds=3,
    )
    checks = [
        CheckStatus(name="arp_sweep", label="Sweeping the network", status="ran", found=2),
        CheckStatus(
            name="dhcp",
            label="Checking for a second address server",
            status="skipped",
            reason="Skipped because you chose a listen-only check.",
        ),
    ]
    findings = evaluate(
        RoomFacts(devices=devices, network=NET, net=net, checks=checks, nearby=survey)
    )
    return DiscoveryResult(
        started_at=T0,
        finished_at=T1,
        mode="full",
        network=NET,
        devices=devices,
        checks=checks,
        network_facts=net,
        findings=findings,
        summary=summarise(findings, checks),
        nearby_items=flagged_items(survey, findings),
        room_network="Example-Home",
    )


def html_for(result=None, label="Flat 4B", explanations=None):
    result = result or scan_result()
    explanations = explanations or explain(
        result.findings, result.devices, result.nearby_items, online=False
    )
    view = render.build_view(result, explanations, room_label=label, generated_at=T1)
    return render.render_html(view)


# --- contents ------------------------------------------------------------------------------


def test_report_contains_everything_plan_md_lists():
    result = scan_result()
    html = html_for(result)
    assert "RoomCheck handover report" in html
    assert "Flat 4B" in html
    assert "03 Nov 2026" in html  # scan date and time, in local time with the UTC offset
    assert "<td><b>Type of check</b></td><td>With permission</td>" in html  # as the dashboard says
    assert "Sweeping the network" in html  # a check that ran
    # One that didn't: a "Not checked" row in Coverage and limits, as on Results.
    assert "Not checked: Skipped because you chose a listen-only check" in html
    assert "Coverage and limits" in html
    for f in result.findings:
        assert str(escape(f.title)) in html and str(escape(f.next_step.split(".")[0])) in html
    assert "identification confidence Likely" in html
    assert "Answered a camera discovery request" in html  # evidence
    assert "Photograph it where it is" in html  # guidance
    assert "What this scan can't see" in html and "memory card" in html
    assert "Limitations" in html and "not legal advice" in html
    assert "Message to the host (draft)" in html
    assert "RoomCheck never sends anything" in html
    assert "Standard explanation" in html
    assert "A device on this network looks like a camera." in html


def test_ai_label_is_shown_for_ai_explanations():
    result = scan_result()
    base = explain(result.findings, online=False)
    ai_items = [
        e.model_copy(
            update={
                "source": "ai",
                "label": "Explained by AI from the scan results. "
                "The risk level comes from fixed rules.",
            }
        )
        for e in base.items
    ]
    html = html_for(result, explanations=Explanations(items=ai_items, landlord_message=None))
    assert "Explained by AI from the scan results. The risk level comes from fixed rules." in html


def test_room_label_is_escaped_and_capped():
    html = html_for(label="<script>alert(1)</script>" + "x" * 200)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "x" * 81 not in html


def test_report_never_says_safe():
    assert not SAFE.search(html_for())


# --- masking and neighbours ----------------------------------------------------------------


def test_mask_mac_keeps_maker_and_last_three_octets():
    assert (
        mask_mac("00:bc:99:aa:bb:cc")
        == "xx:xx:xx:aa:bb:cc (Hangzhou Hikvision Digital Technology Co.,Ltd.)"
    )
    assert mask_mac("02-00-00-00-00-66") == "xx:xx:xx:00:00:66 (private address)"
    assert (
        mask_text("seen from cc:ba:bd:00:00:01 twice")
        == "seen from xx:xx:xx:00:00:01 (TP-Link Systems Inc.) twice"
    )


def test_no_full_mac_appears_anywhere_in_the_report():
    html = html_for()
    assert not FULL_MAC.search(html), FULL_MAC.search(html)
    assert "xx:xx:xx:aa:bb:cc (Hangzhou Hikvision" in html  # the camera
    assert "xx:xx:xx:00:00:66 (private address)" in html  # R-ARP evidence, masked
    for raw in ("00:bc:99:aa:bb:cc", "cc:ba:bd:00:00:01", "9a:3b:4c:00:11:22", "cc:ba:bd:00:10:d9"):
        assert raw not in html


def test_nothing_about_neighbours_devices():
    result = scan_result()
    assert "R-OPEN" in {f.rule_id for f in result.findings}
    html = html_for(result)
    assert "Neighbour-Open" not in html
    assert "1 open network(s) nearby; names left out" in html
    assert "Also heard" not in html and "discarded" not in html


def test_open_count_includes_the_and_more_line():
    assert render._open_count(['"A" has no password', '"B" has no password', "and 3 more"]) == 5


# --- making the files ----------------------------------------------------------------------


def test_make_report_saves_pdf_hash_and_token(tmp_path):
    rep = render.make_report(
        scan_result(),
        Explanations(),
        out_dir=tmp_path,
        render=lambda html: SAMPLE_PDF,
        request=lambda digest, url: SAMPLE_TSR,
        now=lambda: T1,
    )
    f = rep.files
    assert f.pdf.read_bytes() == SAMPLE_PDF
    assert f.pdf.name.startswith("roomcheck-report-") and f.pdf.suffix == ".pdf"
    assert f.sha256 == tamper.sha256(SAMPLE_PDF).hex()
    assert f.sha256_file.read_text("ascii") == f"{f.sha256}  {f.pdf.name}\n"
    assert f.tsr.read_bytes() == SAMPLE_TSR and f.timestamped_at is not None
    assert f.timestamp_message is None
    assert tamper.verify(f.pdf.read_bytes(), f.tsr.read_bytes(), f.sha256).ok


def test_only_the_hash_is_sent_to_the_timestamp_authority(tmp_path):
    sent = []
    render.make_report(
        scan_result(),
        Explanations(),
        out_dir=tmp_path,
        render=lambda html: SAMPLE_PDF,
        request=lambda digest, url: sent.append((digest, url)) or SAMPLE_TSR,
    )
    [(digest, url)] = sent
    assert digest == tamper.sha256(SAMPLE_PDF) and len(digest) == 32
    assert url == tamper.FREETSA_URL


def test_tsa_unreachable_skips_token_with_plan_message(tmp_path):
    def unreachable(digest, url):
        raise tamper.TimestampUnavailable("ConnectionError")

    rep = render.make_report(
        scan_result(),
        Explanations(),
        out_dir=tmp_path,
        render=lambda html: SAMPLE_PDF,
        request=unreachable,
    )
    assert rep.files.tsr is None and rep.files.timestamped_at is None
    assert rep.files.timestamp_message == PLAN_OFFLINE
    assert rep.files.sha256_file.exists()  # the hash is still saved
    assert list(tmp_path.glob("*.tsr")) == []


def test_offline_report_makes_no_request(tmp_path):
    rep = render.make_report(
        scan_result(),
        Explanations(),
        out_dir=tmp_path,
        online=False,
        render=lambda html: SAMPLE_PDF,
        request=lambda d, u: pytest.fail("called the TSA"),
    )
    assert rep.files.tsr is None
    assert rep.files.timestamp_message.startswith("No trusted timestamp")


def test_request_token_maps_network_failure_to_unavailable():
    import requests
    import rfc3161ng

    class Down:
        def __init__(self, *a, **k):
            pass

        def __call__(self, **kwargs):
            raise rfc3161ng.TimestampingError("Unable to send", requests.ConnectionError())

    with pytest.raises(tamper.TimestampUnavailable):
        tamper.request_token(b"\x00" * 32, tamper.FREETSA_URL, timestamper_factory=Down)


def test_request_token_refuses_a_reply_for_another_request():
    import rfc3161ng

    class Replay:  # returns an old, genuine response: wrong nonce and wrong hash
        def __init__(self, *a, **k):
            pass

        def __call__(self, **kwargs):
            return rfc3161ng.decode_timestamp_response(SAMPLE_TSR)

    with pytest.raises(tamper.TimestampUnavailable):
        tamper.request_token(b"\x01" * 32, tamper.FREETSA_URL, timestamper_factory=Replay)


def test_pdf_renderer_missing_raises_pdf_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)  # import fails
    with pytest.raises(render.PdfUnavailable):
        render.render_pdf("<p>x</p>")


def test_real_pdf_render_fetches_nothing():
    """Prints the real report through headless Chromium (skipped if Chromium isn't installed).
    An external image is in the page: it must be blocked, not fetched."""
    html = html_for().replace("</body>", '<img src="https://example.com/x.png"></body>')
    try:
        pdf = render.render_pdf(html)
    except render.PdfUnavailable:
        pytest.skip("Chromium for Playwright isn't installed")
    assert pdf.startswith(b"%PDF-") and len(pdf) > 5000
    assert b"example.com" not in pdf


# --- verify --------------------------------------------------------------------------------


def test_verify_genuine_freetsa_token():
    r = tamper.verify(SAMPLE_PDF, SAMPLE_TSR, tamper.sha256(SAMPLE_PDF).hex())
    assert (r.token, r.hash_file, r.pinned_authority, r.ok) == ("valid", "match", True, True)
    assert r.timestamped_at is not None
    assert "not that its findings are correct" in r.message


def test_tampered_pdf_fails_verify():
    middle = len(SAMPLE_PDF) // 2
    tampered = SAMPLE_PDF[:middle] + bytes([SAMPLE_PDF[middle] ^ 1]) + SAMPLE_PDF[middle + 1 :]
    r = tamper.verify(tampered, SAMPLE_TSR, tamper.sha256(SAMPLE_PDF).hex())
    assert (r.token, r.hash_file, r.ok) == ("mismatch", "mismatch", False)
    assert "changed after it was timestamped" in r.message


def test_changed_hash_file_is_reported():
    r = tamper.verify(SAMPLE_PDF, SAMPLE_TSR, "0" * 64)
    assert r.token == "valid" and not r.ok
    assert ".sha256 file doesn't match" in r.message


def test_token_not_signed_by_the_pinned_certificate_is_not_ok():
    # Check against the wrong pinned certificate: the token is only valid by its own certificate.
    r = tamper.verify(SAMPLE_PDF, SAMPLE_TSR, certificate=CACERT)
    assert (r.token, r.pinned_authority, r.ok) == ("valid", False, False)
    assert "wasn't signed by FreeTSA" in r.message


@pytest.mark.parametrize("garbage", [b"", b"not a token", SAMPLE_TSR[:100]])
def test_damaged_token_is_invalid(garbage):
    r = tamper.verify(SAMPLE_PDF, garbage)
    assert r.token == "invalid" and not r.ok


def test_hash_only_and_nothing_to_check():
    r = tamper.verify(SAMPLE_PDF, None, tamper.sha256(SAMPLE_PDF).hex())
    assert (r.token, r.hash_file, r.ok, r.outcome) == ("missing", "match", False, "not_timestamped")
    assert r.message.startswith(
        "This report wasn't timestamped, so it can't be timestamp-verified."
    )
    assert "It does match its .sha256 file" in r.message
    bare = tamper.verify(SAMPLE_PDF)
    assert (bare.outcome, bare.message) == ("not_timestamped", tamper.NOT_TIMESTAMPED)


def test_read_hash_file():
    digest = "a" * 64
    assert tamper.read_hash_file(f"{digest}  report.pdf\n") == digest
    assert tamper.read_hash_file("not a hash") is None


def test_cli_verify(tmp_path, capsys):
    pdf = tmp_path / "roomcheck-report-20261103-120000.pdf"
    pdf.write_bytes(SAMPLE_PDF)
    shutil.copy(FIXTURES / "sample.tsr", pdf.with_suffix(".tsr"))
    assert cli.main(["verify", str(pdf)]) == 0
    assert "OK: This PDF matches its timestamp" in capsys.readouterr().out
    pdf.write_bytes(SAMPLE_PDF + b"%edited\n")
    assert cli.main(["verify", str(pdf)]) == 1
    assert "NOT VERIFIED" in capsys.readouterr().out


# --- API -----------------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "render_pdf", lambda html: SAMPLE_PDF)
    monkeypatch.setattr(tamper, "request_token", lambda digest, url: SAMPLE_TSR)
    monkeypatch.setattr(main.app.state, "report_dir", tmp_path, raising=False)
    monkeypatch.setattr(main.app.state, "last_result", None, raising=False)
    with TestClient(main.app) as c:
        yield c


def test_report_needs_a_check_first(client):
    r = client.post("/api/report", json={})
    assert r.status_code == 409
    assert r.json()["detail"] == "Run a check first, then make the report from its results."


def test_report_endpoint_makes_and_serves_files(client):
    main.app.state.last_result = scan_result()
    r = client.post("/api/report", json={"room_label": "Flat 4B"})
    assert r.status_code == 200
    body = r.json()
    assert body["tsr"].endswith(".tsr") and body["timestamp_message"] is None
    assert body["sha256"] == tamper.sha256(SAMPLE_PDF).hex()
    assert {e["source"] for e in body["explanations"]["items"]} <= {"ai", "standard"}
    pdf = client.get(f"/api/report/files/{body['pdf']}")
    assert pdf.status_code == 200 and pdf.content == SAMPLE_PDF


@pytest.mark.parametrize("name", ["..%2F..%2Fsecret.pdf", "report.pdf", "roomcheck-report-1.exe"])
def test_file_endpoint_only_serves_report_names(client, name):
    assert client.get(f"/api/report/files/{name}").status_code == 404


def test_report_endpoint_when_pdf_tool_missing(client, monkeypatch):
    def missing(html):
        raise render.PdfUnavailable("weasyprint_libraries")

    monkeypatch.setattr(render, "render_pdf", missing)
    main.app.state.last_result = scan_result()
    r = client.post("/api/report", json={})
    assert r.status_code == 503 and "PDF" in r.json()["detail"]


def test_verify_endpoint(client):
    ok = client.post(
        "/api/verify", files={"pdf": ("r.pdf", SAMPLE_PDF), "tsr": ("r.tsr", SAMPLE_TSR)}
    )
    assert ok.status_code == 200 and ok.json()["ok"] is True
    bad = client.post(
        "/api/verify", files={"pdf": ("r.pdf", SAMPLE_PDF + b"x"), "tsr": ("r.tsr", SAMPLE_TSR)}
    )
    assert bad.json()["token"] == "mismatch" and bad.json()["ok"] is False


def test_verify_endpoint_caps_upload_size(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)
    r = client.post("/api/verify", files={"pdf": ("r.pdf", SAMPLE_PDF)})
    assert r.status_code == 413


def test_report_pdf_can_be_shown_inline_with_its_own_tight_policy(client):
    main.app.state.last_result = scan_result()
    body = client.post("/api/report", json={}).json()
    inline = client.get(f"/api/report/files/{body['pdf']}?inline=true")
    assert inline.headers["content-disposition"].startswith("inline")
    assert inline.headers["content-type"] == "application/pdf"
    # The fixture is a real (made-up) PDF, so this is what a browser's PDF viewer gets.
    assert inline.content == SAMPLE_PDF
    assert inline.content.startswith(b"%PDF-") and b"%%EOF" in inline.content[-32:]
    # Nothing in the PDF may load anything, and only RoomCheck's own page may frame it.
    assert inline.headers["content-security-policy"] == main.REPORT_PDF_POLICY
    assert "default-src 'none'" in main.REPORT_PDF_POLICY
    assert "frame-ancestors 'self'" in main.REPORT_PDF_POLICY
    download = client.get(f"/api/report/files/{body['pdf']}")
    assert download.headers["content-disposition"].startswith("attachment")
    # Only PDFs can be shown inline; the token is always a download, under the page policy.
    tsr = client.get(f"/api/report/files/{body['tsr']}?inline=true")
    assert tsr.headers["content-disposition"].startswith("attachment")
    assert tsr.headers["content-security-policy"] == main.CONTENT_SECURITY_POLICY
