"""Layer 5 follow-ups: the shared, warmed AI client; the connected router vs nearby access
points in the payload; and wording drift seen live on 3 Nov. No test calls the real API."""

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.explain import ai, validator
from app.explain.ai import start_warm_up as real_start_warm_up  # before conftest's no-op
from app.explain.service import explain
from tests.unit.test_explain import (
    KEY,
    NO_KEY,
    REQ,
    WITH_KEY,
    FakeClient,
    payload_reply,
    room,
)

# --- the shared client and its warm-up -------------------------------------------------------


class FakeModels:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(data=[])


def test_warm_up_lists_one_model_and_loads_messages():
    client = SimpleNamespace(models=FakeModels(), messages=object())
    assert ai.warm_up(WITH_KEY, client=client) is None
    assert client.models.calls == [{"limit": 1}]  # a free request; nothing about the scan


def test_warm_up_failure_logs_the_code_only(caplog):
    error = anthropic.AuthenticationError(
        f"invalid x-api-key {KEY}", response=httpx2.Response(401, request=REQ), body=None
    )
    client = SimpleNamespace(models=FakeModels(error=error), messages=object())
    caplog.set_level("DEBUG")
    assert ai.warm_up(WITH_KEY, client=client) == "auth"
    assert "AI warm-up failed (auth)" in caplog.text
    assert KEY not in caplog.text and "invalid x-api-key" not in caplog.text


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (anthropic.APIConnectionError(request=REQ), "unreachable"),
        (anthropic.APITimeoutError(request=REQ), "timeout"),
        (RuntimeError("boom"), "internal"),
    ],
)
def test_warm_up_never_raises(error, code):
    client = SimpleNamespace(models=FakeModels(error=error), messages=object())
    assert ai.warm_up(WITH_KEY, client=client) == code


def test_no_key_means_no_warm_up_thread():
    assert real_start_warm_up(NO_KEY) is None


def test_warm_up_runs_in_the_background(monkeypatch):
    calls = []
    monkeypatch.setattr(ai, "warm_up", lambda settings: calls.append(settings))
    thread = real_start_warm_up(WITH_KEY)
    thread.join(timeout=5)
    assert thread.daemon and calls == [WITH_KEY]


def test_one_shared_client_is_built_and_reused(monkeypatch):
    built = []
    fake = FakeClient(reply=payload_reply)

    def build(api_key):
        built.append(api_key)
        return fake

    monkeypatch.setattr(ai, "_build_client", build)
    findings, devices, nearby = room()
    first = explain(findings, devices, nearby, settings=WITH_KEY)
    second = explain(findings, devices, nearby, settings=WITH_KEY)
    assert first.ai_status == second.ai_status == "used"
    assert built == [KEY]  # built once, then reused
    other = Settings(
        anthropic_api_key=SecretStr("sk-ant-other"), anthropic_model="claude-haiku-5-5"
    )
    explain(findings, devices, nearby, settings=other)
    assert built == [KEY, "sk-ant-other"]  # a different key gets its own client


def test_app_startup_starts_the_warm_up(monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as main

    started = []
    monkeypatch.setattr(ai, "start_warm_up", lambda settings: started.append(settings))
    with TestClient(main.app):
        pass
    assert len(started) == 1


# --- connected router vs nearby access points ------------------------------------------------


def test_connected_router_is_this_networks_router_not_nearby():
    findings, devices, nearby = room()
    router = nearby[0].model_copy(update={"connected": True, "rule_ids": ["R-WPS"]})
    wps = findings[-1].model_copy(
        update={"rule_id": "R-WPS", "title": "Your Wi-Fi router offers WPS"}
    )
    payload, _ = ai.build_payload([wps], devices, [router])
    assert payload[0]["device_type"] == "This network's router or access point"
    assert "nearby" not in payload[0]["device_type"].lower()
    payload, _ = ai.build_payload([wps], devices, [nearby[0]])  # not connected
    assert payload[0]["device_type"] == "Nearby Wi-Fi access point"


def test_payload_carries_the_rules_fixed_text_and_the_prompt_rules():
    findings, devices, nearby = room()
    payload, _ = ai.build_payload(findings, devices, nearby)
    cam = next(p for p in payload if p["rule_id"] == "R-CAM")
    assert cam["rule_text"].startswith("A device on this network looks like a camera.")
    assert "don't add claims" in ai.SYSTEM_PROMPT
    assert "Say it isn't confirmed for this device." in ai.SYSTEM_PROMPT


# --- wording drift seen live on 3 Nov (claude-haiku-5-5) -------------------------------------

HAIKU_CVE = (
    "Known issues have been reported for this camera model. This is general information about "
    "the model, not a fault found in this device."
)
HAIKU_WPS = (
    "A nearby Wi-Fi router offers WPS. This was found from the Wi-Fi signal, so the router may "
    "not be the one in this room."
)


def test_haiku_cve_sentence_is_rejected():
    assert validator.problem_with_text(HAIKU_CVE, "Info", "R-CVE") == "unconfirmed_claim"


def test_not_confirmed_wording_is_accepted_for_known_issues():
    text = (
        "Known issues have been reported for this camera model. It isn't confirmed whether "
        "they affect this device, because its exact firmware version is unknown."
    )
    assert validator.problem_with_text(text, "Info", "R-CVE") is None


@pytest.mark.parametrize(
    "claim",
    [
        "Your camera is not affected.",
        "The device is vulnerable to these issues.",
        "These issues don't affect your device.",
        "This flaw affects this device.",
    ],
)
def test_claims_either_way_about_this_device_are_rejected_for_known_issues(claim):
    assert validator.problem_with_text(claim, "Medium", "R-CVE") == "unconfirmed_claim"


@pytest.mark.parametrize(
    "hedged",
    [
        # The wording the prompt asks for. The first version of this check rejected sentences
        # like this one, most likely what run 3 on 3 Nov produced (rejected text isn't kept).
        "It is not confirmed whether this device is affected.",
        "It isn't confirmed whether these issues affect this device.",
        "RoomCheck can't tell if the device is affected, because its firmware is unknown.",
        "The camera may be affected if it hasn't been updated.",
    ],
)
def test_hedged_known_issue_wording_is_accepted(hedged):
    assert validator.problem_with_text(hedged, "Info", "R-CVE") is None


def test_one_hedged_sentence_doesnt_excuse_a_flat_claim_in_another():
    text = "It is not confirmed which version it runs. The device is vulnerable to these issues."
    assert validator.problem_with_text(text, "Info", "R-CVE") == "unconfirmed_claim"


def test_device_claims_are_allowed_outside_known_issues():
    # On R-TELNET this is a true statement, not speculation about a CVE.
    text = "Telnet sends passwords unencrypted, so the device is vulnerable to anyone nearby."
    assert validator.problem_with_text(text, "High", "R-TELNET") is None


def test_haiku_wps_sentence_is_now_caught_and_its_cause_is_gone():
    # The model said it because the payload called the room's own router "nearby"
    # (test_connected_router_is_this_networks_router_not_nearby shows it no longer does). Its
    # "in this room" is now also caught by the exact-phrase location check.
    assert validator.problem_with_text(HAIKU_WPS, "Medium", "R-WPS") == "location_claim"


@pytest.mark.parametrize(
    ("text", "severity", "reason"),
    [
        ("This isn't a problem for most people.", "High", "downplays"),
        ("It is not a fault in the router.", "Medium", "downplays"),
        ("There is nothing wrong with the device.", "High", "downplays"),
        ("This is no cause for concern.", "Medium", "downplays"),
        ("These aren't a serious issue.", "High", "downplays"),
        ("This isn't a problem for most people.", "Low", None),  # only High and Medium
        ("Many routers hide a second network, so this is often not a concern.", "Info", None),
    ],
)
def test_downplaying_phrases_on_high_and_medium(text, severity, reason):
    assert validator.problem_with_text(text, severity, "R-X") == reason


def test_downplaying_ai_text_falls_back_to_the_rule_text():
    def reply(request):
        payload = json.loads(request["messages"][0]["content"])["findings"]
        data = {
            "explanations": [
                {
                    "finding_id": p["finding_id"],
                    "explanation": "This is a device.",
                    "why_it_matters": "It isn't a problem." if p["severity"] == "High" else "Ask.",
                }
                for p in payload
            ],
            "landlord_message": "Could you tell me what the device is?",
        }
        return SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", name=ai.TOOL_NAME, input=data)],
            stop_reason="tool_use",
        )

    findings, devices, nearby = room()
    out = explain(
        findings,
        devices,
        nearby,
        settings=WITH_KEY,
        call=lambda s, p: ai.call_ai(s, p, client_factory=FakeClient(reply=reply)),
    )
    high = [f for f in findings if f.severity == "High"]
    assert {out.for_finding(f.id).source for f in high} == {"standard"}
    assert set(out.ai_rejected.values()) == {"downplays"}


# --- location claims (R-CAM, 3 Nov: "A device in the room may be a camera") -----------------


def test_rcam_rule_text_says_on_this_network_not_in_the_room():
    findings, devices, nearby = room()
    payload, _ = ai.build_payload(findings, devices, nearby)
    cam = next(p for p in payload if p["rule_id"] == "R-CAM")
    assert "on this network" in cam["rule_text"]
    assert validator.problem_with_text(cam["rule_text"], "High", "R-CAM") is None
    assert '"in the room"' in ai.SYSTEM_PROMPT and '"on this network"' in ai.SYSTEM_PROMPT


@pytest.mark.parametrize(
    "text",
    [
        "A device in the room may be a camera.",
        "There may be a camera in your room.",
        "This camera is in this room and could record you.",
        "A tracker may be hidden in the bedroom.",
    ],
)
def test_location_claims_are_rejected(text):
    assert validator.problem_with_text(text, "High", "R-CAM") == "location_claim"
    assert validator.problem_with_text(text, "Info", "R-X") == "location_claim"


def test_on_this_network_wording_is_accepted():
    text = "A device on this network may be a camera. This is unconfirmed: a clue, not proof."
    assert validator.problem_with_text(text, "High", "R-CAM") is None
