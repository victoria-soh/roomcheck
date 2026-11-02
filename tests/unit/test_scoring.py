import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.discovery.messages import MESSAGES
from app.fingerprint.facts import device_facts
from app.fingerprint.scoring import (
    WEIGHTS_FILE,
    Bands,
    Weights,
    band_for,
    fingerprint,
    load_weights,
    noisy_or,
)
from tests.unit import devices as dev


def fp(device, ident="full"):
    return fingerprint(device_facts(device), ident)


def camera_score(f):
    if f.type == "camera":
        return f.confidence
    return next((t.score for t in f.other_types + f.weak_types if t.type == "camera"), 0.0)


def test_noisy_or():
    assert noisy_or([]) == 0
    assert noisy_or([0.6]) == pytest.approx(0.6)
    assert noisy_or([0.6, 0.5, 0.3]) == pytest.approx(1 - 0.4 * 0.5 * 0.7)
    assert 0.99 < noisy_or([0.9] * 50) <= 1.0


def test_bands():
    b = Bands(likely=0.8, possible=0.5)
    assert band_for(0.8, b) == "Likely"
    assert band_for(0.79, b) == "Possible"
    assert band_for(0.5, b) == "Possible"
    assert band_for(0.49, b) == "Unclear"
    assert band_for(0.0, b) == "Unclear"


def test_weights_file_has_plan_camera_weights():
    w = load_weights()
    cam = {s.id: s.weight for s in w.types["camera"].signals}
    assert cam["onvif_nvt"] == 0.6
    assert cam["rtsp_server"] == 0.5
    assert cam["camera_ports"] == 0.3
    assert cam["camera_vendor"] == 0.3
    assert cam["camera_name"] == 0.3
    assert cam["multi_type_vendor"] == 0.1
    assert cam["tuya_broadcast"] == 0.05
    assert set(w.types) == {
        "camera",
        "lock_doorbell",
        "router",
        "hub",
        "speaker",
        "tv",
        "smart_plug",
        "computer_phone",
    }


def test_weights_file_rejects_bad_values(tmp_path: Path):
    data = yaml.safe_load(WEIGHTS_FILE.read_text(encoding="utf-8"))
    data["types"]["camera"]["signals"][0]["weight"] = 1.5
    with pytest.raises(ValidationError):
        Weights.model_validate(data)
    data = yaml.safe_load(WEIGHTS_FILE.read_text(encoding="utf-8"))
    data["types"]["camera"]["signals"][0]["when"] = {"shell_command": "x"}
    with pytest.raises(ValidationError):
        Weights.model_validate(data)


def test_camera_like_device_is_likely_camera():
    f = fp(dev.hikvision_camera())
    assert (f.type, f.band) == ("camera", "Likely")
    assert f.confidence == pytest.approx(1 - 0.4 * 0.5 * 0.7 * 0.7)
    signals = {e.signal for e in f.evidence}
    assert signals == {"onvif_nvt", "rtsp_server", "camera_ports", "camera_vendor"}
    texts = " | ".join(e.text for e in f.evidence)
    assert "Hikvision" in texts and "port 554" in texts and "port 8000" in texts


def test_phone_camera_app_is_at_least_possible_camera():
    f = fp(dev.phone_ip_camera_app())
    assert f.type == "camera"
    assert f.band in ("Possible", "Likely")
    assert {e.signal for e in f.evidence} >= {"rtsp_server", "camera_name"}


def test_sonos_is_speaker_not_camera():
    f = fp(dev.sonos())
    assert (f.type, f.band) == ("speaker", "Likely")
    assert camera_score(f) < 0.5
    assert any("Sonos" in e.text for e in f.evidence)


def test_macbook_is_computer_not_camera():
    f = fp(dev.macbook())
    assert (f.type, f.band) == ("computer_phone", "Likely")
    assert camera_score(f) < 0.5


def test_windows_laptop_with_private_mac_is_computer_not_camera():
    d = dev.windows_laptop()
    assert d.vendor is None
    f = fp(d)
    assert f.type == "computer_phone"
    assert f.band in ("Possible", "Likely")
    assert camera_score(f) == 0


def test_gateway_is_router():
    f = fp(dev.tp_link_gateway())
    assert (f.type, f.band) == ("router", "Likely")
    # TP-Link also makes cameras: it shows as weak camera evidence, not a camera label.
    assert 0 < camera_score(f) < 0.5


def test_no_evidence_is_unidentified_and_unclear():
    f = fp(dev.make("192.168.68.99", None), "passive")
    assert (f.type, f.band, f.confidence, f.evidence) == ("unknown", "Unclear", 0.0, [])
    assert f.identification == "passive"


def test_name_regex_avoids_obvious_false_matches():
    d = dev.make("192.168.68.90", None, hostnames=["Cambridge-Audio.local", "camden-pc"])
    assert camera_score(fp(d)) == 0
    d = dev.make("192.168.68.91", None, hostnames=["front-cam.local"])
    assert camera_score(fp(d)) == pytest.approx(0.3)


_SAFE = re.compile(r"\bsafe(ly|ty)?\b|no risk", re.IGNORECASE)


def test_never_says_safe():
    text = WEIGHTS_FILE.read_text(encoding="utf-8")
    assert not _SAFE.search(text)
    assert not any(_SAFE.search(m) for m in MESSAGES.values())
    for d in (dev.sonos(), dev.macbook(), dev.hikvision_camera(), dev.make("10.0.0.9", None)):
        assert not _SAFE.search(fp(d).model_dump_json())


def test_weak_other_types_are_kept_out_of_the_shown_list():
    assert load_weights().other_type_min == 0.3
    f = fp(dev.tp_link_gateway())
    assert all(t.score >= 0.3 for t in f.other_types)
    assert "camera" not in {t.type for t in f.other_types}
    [weak] = [t for t in f.weak_types if t.type == "camera"]
    assert weak.score == pytest.approx(0.1)
    assert weak.evidence[0].signal == "multi_type_vendor"


def test_strong_other_types_are_shown():
    # A camera that is also the gateway: router evidence (0.6) is strong enough to show.
    d = dev.hikvision_camera()
    d.is_gateway = True
    f = fp(d)
    assert f.type == "camera"
    assert [t.type for t in f.other_types] == ["router"]
