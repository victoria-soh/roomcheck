"""Layer 5 explanations: what the AI is sent, the mocked API (valid output, invalid output,
timeout, errors, no key), the validator's rejections, and the standard-text fallbacks.
No test calls the real API."""

import json
import re
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.explain import ai, validator
from app.explain.models import AI_LABEL, STANDARD_LABEL
from app.explain.service import explain, standard_landlord_message
from app.fingerprint.facts import device_facts
from app.fingerprint.scoring import fingerprint
from app.rules.engine import RoomFacts, evaluate, load_rules
from app.rules.models import Finding
from app.wireless.models import NearbyItem
from tests.unit import devices as dev

KEY = "sk-ant-api03-TEST-ONLY"
WITH_KEY = Settings(anthropic_api_key=SecretStr(KEY), anthropic_model="claude-haiku-5-5")
NO_KEY = Settings()
SAFE = re.compile(r"\bsafe(ly|ty)?\b|no risk", re.IGNORECASE)


def scored(d):
    d.fingerprint = fingerprint(device_facts(d), "full")
    return d


def room():
    """A camera, a phone camera app, a router with UPnP and Telnet, and a flagged hotspot."""
    router = scored(dev.tp_link_gateway())
    router.identity.open_ports = [23, 80]
    devices = [scored(dev.hikvision_camera()), scored(dev.phone_ip_camera_app()), router]
    findings = evaluate(RoomFacts(devices=devices, network=None))
    hotspot = NearbyItem(
        ref="wifi:0123456789abcdef0123",
        kind="wifi",
        label='Wi-Fi network "IPCAM-7F3A21"',
        ssid="IPCAM-7F3A21",
        maker=None,
        security="WPA2",
        band="2.4 GHz",
        signal_dbm=-44,
        rule_ids=["R-CAMHOT"],
    )
    findings.append(
        Finding(
            id=f"R-CAMHOT:{hotspot.ref}",
            rule_id="R-CAMHOT",
            severity="Medium",
            confidence_band="Possible",
            device_ref=None,
            nearby_ref=hotspot.ref,
            title="Possible camera setup hotspot",
            evidence=['The network name "IPCAM-7F3A21" matches the name mentions a camera'],
            next_step="Use the locator.",
            standard_explanation="A nearby Wi-Fi network looks like a camera's setup network.",
            standard_why="A camera may be nearby.",
            landlord_question="Is there a camera in or near the room?",
        )
    )
    return findings, devices, [hotspot]


def good_output(payload, **overrides):
    out = {
        "explanations": [
            {
                "finding_id": p["finding_id"],
                "explanation": f"This looks like a {p['device_type'].lower()}.",
                "why_it_matters": "Someone else may be able to control or watch it.",
            }
            for p in payload
        ],
        "landlord_message": "Hello, could you tell me what the camera-like device is, please?",
    }
    out.update(overrides)
    return out


class FakeClient:
    """Stands in for anthropic.Anthropic. Records how it was built and called."""

    def __init__(self, reply=None, error=None, delay=0.0):
        self.reply, self.error, self.delay = reply, error, delay
        self.built = self.request = None

    def __call__(self, **kwargs):
        self.built = kwargs
        return self

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        self.request = kwargs
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.reply(kwargs) if callable(self.reply) else self.reply


def tool_reply(data, stop_reason="tool_use", name=ai.TOOL_NAME):
    block = SimpleNamespace(type="tool_use", name=name, input=data)
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Here you go."), block], stop_reason=stop_reason
    )


def via(fake, **kwargs):
    """explain() with the real call_ai, but through the fake client."""
    findings, devices, nearby = room()

    def call(settings, payload):
        return ai.call_ai(settings, payload, client_factory=fake, **kwargs)

    return explain(findings, devices, nearby, settings=WITH_KEY, call=call), findings


def payload_reply(request):
    payload = json.loads(request["messages"][0]["content"])["findings"]
    return tool_reply(good_output(payload))


# --- what is sent ----------------------------------------------------------------------------


def test_payload_holds_only_allowed_fields_and_no_identifiers():
    findings, devices, nearby = room()
    payload, ids = ai.build_payload(findings, devices, nearby)
    allowed = {
        "finding_id",
        "rule_id",
        "rule_title",
        "rule_text",
        "severity",
        "device_type",
        "vendor",
        "evidence",
        "in_message",  # a flag: whether the host message covers this finding (B11)
    }
    assert all(set(p) <= allowed for p in payload)
    assert [p["finding_id"] for p in payload] == [f"f{n}" for n in range(1, len(findings) + 1)]
    assert ids["f1"] == findings[0].id
    text = json.dumps(payload)
    for secret in (
        "192.168.1.",
        "00:bc:99",
        "aa:bb:cc",
        "cc:ba:bd",
        "IPCAM-7F3A21",
        "wifi:0123",
        "IP Webcam",
        "Hikvision-Webs",
        "mac:",
    ):
        assert secret not in text, secret
    assert not re.search(r"\d{1,3}(\.\d{1,3}){3}", text)


def test_payload_names_type_vendor_and_fixed_evidence():
    findings, devices, nearby = room()
    payload, _ = ai.build_payload(findings, devices, nearby)
    cam = next(p for p in payload if p["rule_id"] == "R-CAM" and "Hikvision" in p.get("vendor", ""))
    assert cam["device_type"] == "Camera" and cam["severity"] == "High"
    assert "Answered a camera discovery request (ONVIF video transmitter)" in cam["evidence"]
    hot = next(p for p in payload if p["rule_id"] == "R-CAMHOT")
    assert hot["device_type"] == "Nearby Wi-Fi access point" and "vendor" not in hot


def test_request_uses_config_model_tool_use_and_8s_without_retries():
    fake = FakeClient(reply=payload_reply)
    out, _ = via(fake)
    assert fake.built == {"api_key": KEY, "timeout": 8.0, "max_retries": 0}
    r = fake.request
    assert r["model"] == "claude-haiku-5-5"
    assert r["tool_choice"] == {"type": "auto"}
    [tool] = r["tools"]
    assert tool["name"] == ai.TOOL_NAME and tool["strict"] is True
    item = tool["input_schema"]["properties"]["explanations"]["items"]
    assert item["required"] == ["finding_id", "explanation", "why_it_matters"]
    assert "safe" in r["system"]  # the prompt forbids it


# --- valid and invalid output ----------------------------------------------------------------


def test_valid_output_is_used_and_labelled_ai():
    out, findings = via(FakeClient(reply=payload_reply))
    assert out.ai_status == "used"
    assert [e.finding_id for e in out.items] == [f.id for f in findings]
    assert all(e.source == "ai" and e.label == AI_LABEL for e in out.items)
    assert out.landlord_message.source == "ai"
    assert "could you tell me" in out.landlord_message.text


@pytest.mark.parametrize(
    "bad",
    [
        {"explanations": "not a list", "landlord_message": "x?"},
        {"explanations": []},  # missing landlord_message
        {"explanations": [], "landlord_message": "Hi?", "extra": 1},
    ],
)
def test_schema_violations_fall_back_to_standard(bad):
    out, findings = via(FakeClient(reply=tool_reply(bad)))
    assert out.ai_status == "rejected"
    assert all(e.source == "standard" and e.label == STANDARD_LABEL for e in out.items)
    assert out.items[0].explanation == findings[0].standard_explanation


def test_unknown_or_duplicate_finding_id_rejects_everything():
    def unknown(request):
        payload = json.loads(request["messages"][0]["content"])["findings"]
        data = good_output(payload)
        data["explanations"][0]["finding_id"] = "f99"
        return tool_reply(data)

    def duplicate(request):
        payload = json.loads(request["messages"][0]["content"])["findings"]
        data = good_output(payload)
        data["explanations"].append(dict(data["explanations"][0]))
        return tool_reply(data)

    for reply in (unknown, duplicate):
        out, _ = via(FakeClient(reply=reply))
        assert out.ai_status == "rejected"
        assert {e.source for e in out.items} == {"standard"}


def test_one_bad_explanation_falls_back_alone():
    def reply(request):
        payload = json.loads(request["messages"][0]["content"])["findings"]
        data = good_output(payload)
        data["explanations"][0]["why_it_matters"] = "It's probably fine, nothing to worry about."
        return tool_reply(data)

    out, findings = via(FakeClient(reply=reply))
    assert out.ai_status == "partly_used"
    assert out.items[0].source == "standard" and out.items[0].label == STANDARD_LABEL
    assert all(e.source == "ai" for e in out.items[1:])


def test_missing_explanations_use_standard_text():
    def reply(request):
        payload = json.loads(request["messages"][0]["content"])["findings"]
        return tool_reply(good_output(payload[:1]))

    out, _ = via(FakeClient(reply=reply))
    assert out.items[0].source == "ai"
    assert all(e.source == "standard" for e in out.items[1:])


def test_bad_landlord_message_falls_back_but_explanations_stay():
    def reply(request):
        payload = json.loads(request["messages"][0]["content"])["findings"]
        return tool_reply(good_output(payload, landlord_message="You are spying on me. Remove it."))

    out, _ = via(FakeClient(reply=reply))
    assert out.ai_status == "used"
    assert out.landlord_message.source == "standard"


@pytest.mark.parametrize(
    ("reply", "status"),
    [
        (tool_reply({}, stop_reason="refusal"), "failed"),
        (tool_reply({}, stop_reason="max_tokens"), "failed"),
        (tool_reply({}, name="other_tool"), "failed"),
        (
            SimpleNamespace(
                content=[SimpleNamespace(type="text", text="Sure!")], stop_reason="end_turn"
            ),
            "failed",
        ),
        (tool_reply("{not json"), "failed"),
    ],
)
def test_refusal_truncation_and_missing_tool_call_fall_back(reply, status):
    out, _ = via(FakeClient(reply=reply))
    assert out.ai_status == status
    assert {e.source for e in out.items} == {"standard"}


# --- timeout, errors, no key -----------------------------------------------------------------

REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    "error",
    [
        anthropic.APITimeoutError(request=REQ),
        anthropic.APIConnectionError(request=REQ),
        anthropic.AuthenticationError(
            "bad key", response=httpx2.Response(401, request=REQ), body=None
        ),
        anthropic.RateLimitError(
            "slow down", response=httpx2.Response(429, request=REQ), body=None
        ),
        anthropic.InternalServerError(
            "oops", response=httpx2.Response(500, request=REQ), body=None
        ),
    ],
)
def test_api_errors_fall_back_to_standard(error):
    out, _ = via(FakeClient(error=error))
    assert out.ai_status == "failed"
    assert {e.source for e in out.items} == {"standard"}
    assert out.landlord_message.source == "standard"


def test_slow_api_is_cut_off_at_the_timeout():
    started = time.monotonic()
    out, _ = via(FakeClient(reply=payload_reply, delay=2.0), timeout=0.2)
    assert time.monotonic() - started < 1.5
    assert out.ai_status == "failed"
    assert {e.source for e in out.items} == {"standard"}


def test_default_timeout_is_8_seconds():
    assert ai.TIMEOUT_SECONDS == 8.0


def test_no_api_key_means_no_call_and_standard_text():
    calls = []
    findings, devices, nearby = room()
    out = explain(findings, devices, nearby, settings=NO_KEY, call=lambda *a: calls.append(a))
    assert calls == []
    assert out.ai_status == "not_configured"
    assert {e.label for e in out.items} == {STANDARD_LABEL}


def test_offline_means_no_call():
    calls = []
    findings, devices, nearby = room()
    out = explain(
        findings, devices, nearby, online=False, settings=WITH_KEY, call=lambda *a: calls.append(a)
    )
    assert calls == [] and out.ai_status == "offline"


def test_no_findings_means_no_call_and_no_message():
    out = explain([], settings=WITH_KEY, call=lambda *a: pytest.fail("called"))
    assert out.items == [] and out.landlord_message is None and out.ai_status == "none"


# --- the validator's rejections --------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "severity", "reason"),
    [
        ("This camera is safe to keep.", "High", "reassurance"),
        ("There is no risk from this device.", "High", "reassurance"),
        ("You can safely ignore this.", "Medium", "reassurance"),
        ("Nothing to worry about here.", "Medium", "reassurance"),
        ("This is harmless.", "Low", "reassurance"),
        ("It's just a minor thing.", "High", "reassurance"),
        ("This is a low risk finding.", "High", "severity_changed"),
        ("Overall a medium-risk issue.", "High", "severity_changed"),
        ("The risk level is low here.", "Medium", "severity_changed"),
        ("This is a critical threat.", "Medium", "severity_changed"),
        ("This is definitely a camera.", "High", "overclaim"),
        ("Its address is 192.168.1.64.", "High", "identifier"),
        ("Its MAC is 00:bc:99:aa:bb:cc.", "High", "identifier"),
        ("word " * 81, "High", "too_long"),
        ("   ", "High", "empty"),
    ],
)
def test_validator_rejections(text, severity, reason):
    assert validator.problem_with_text(text, severity) == reason


@pytest.mark.parametrize(
    ("text", "severity"),
    [
        ("This looks like a camera. Someone else may be able to watch the room.", "High"),
        ("This is a high-risk finding because a camera may record you.", "High"),
        ("It offers low-level access over Telnet.", "High"),  # "low-level" isn't a severity
        ("Ask the host to confirm what the device is.", "Medium"),
    ],
)
def test_validator_accepts_plain_honest_text(text, severity):
    assert validator.problem_with_text(text, severity) is None


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("Hello, could you confirm what the device that may be a camera is?", None),
        ("Hello, could you confirm what the camera is?", "camera_overclaim"),  # B1
        ("Hello, we found a device. Could you tell me what it is?", "not_first_person"),  # B11
        ("Hello, you are recording me illegally.", "accusation"),
        ("I will call the police unless you remove it?", "accusation"),
        ("Please remove the camera.", "no_question"),
        ("Hi, is it safe to use the Wi-Fi?", "reassurance"),
        ("Could you check device 00:bc:99:aa:bb:cc?", "identifier"),
        ("", "empty"),
    ],
)
def test_landlord_message_checks(message, reason):
    assert validator.check_landlord_message(message) == reason


# --- standard text ---------------------------------------------------------------------------


def test_every_rule_has_plain_standard_text():
    for rule in load_rules().rules:
        texts = []
        for value in (rule.explanation, rule.why_it_matters, rule.landlord_question):
            if isinstance(value, dict):
                texts += list(value.values())
            elif value:
                texts.append(value)
        for t in texts:
            assert not SAFE.search(t), rule.id
        for exp, why in _variant_pairs(rule):
            assert validator.words(f"{exp} {why}") <= validator.MAX_WORDS, rule.id
        questions = rule.landlord_question
        for q in (
            questions.values() if isinstance(questions, dict) else [questions] if questions else []
        ):
            assert q.rstrip().endswith("?"), rule.id
            assert validator.check_landlord_message(q) is None, rule.id


def _variant_pairs(rule):
    exp, why = rule.explanation, rule.why_it_matters
    keys = set(exp) if isinstance(exp, dict) else set(why) if isinstance(why, dict) else {None}
    for k in keys:
        yield (exp[k] if isinstance(exp, dict) else exp), (why[k] if isinstance(why, dict) else why)


def test_findings_carry_their_rule_text():
    findings, _, _ = room()
    cam = next(f for f in findings if f.rule_id == "R-CAM")
    assert cam.standard_explanation.startswith("A device on this network looks like a camera.")
    assert cam.landlord_question.endswith("who can view it?")


def test_standard_landlord_message_asks_open_questions_once():
    findings, _, _ = room()
    m = standard_landlord_message(findings)
    assert m.source == "standard" and "?" in m.text
    assert m.text.count("looks like a camera. Could you tell me") == 1  # two cameras, one question
    assert "RoomCheck never sends anything" in m.note
    assert validator.check_landlord_message(m.text) is None
    info_only = [f for f in findings if f.rule_id == "R-UPNP"]
    for f in info_only:
        f.severity = "Info"
    assert standard_landlord_message(info_only) is None


# --- thinking off, per model -----------------------------------------------------------------


def test_explanation_call_turns_thinking_off():
    fake = FakeClient(reply=payload_reply)
    via(fake)
    assert fake.request["thinking"] == {"type": "disabled"}  # claude-haiku-5-5
    assert fake.request["output_config"] == {"effort": "low"}


@pytest.mark.parametrize(
    ("model", "thinking"),
    [
        ("claude-haiku-5-5", {"type": "disabled"}),
        ("claude-sonnet-5-5", {"type": "between_tools"}),  # rejects "disabled"
        ("claude-opus-5-5", None),  # can't be turned off: lowest effort instead
        ("claude-fable-5-1", None),
        ("claude-sonnet-5", {"type": "disabled"}),
    ],
)
def test_thinking_off_setting_per_model(model, thinking):
    assert ai.thinking_off(model) == thinking
    fake = FakeClient(reply=payload_reply)
    settings = Settings(anthropic_api_key=SecretStr(KEY), anthropic_model=model)
    findings, devices, nearby = room()
    explain(
        findings,
        devices,
        nearby,
        settings=settings,
        call=lambda s, p: ai.call_ai(s, p, client_factory=fake),
    )
    assert fake.request.get("thinking") == thinking
    assert fake.request["model"] == model


# --- failure reasons (CLI and API), never with the key or request contents --------------------


@pytest.mark.parametrize(
    ("make", "code", "text"),
    [
        (
            lambda: FakeClient(reply=payload_reply, delay=2.0),
            "timeout",
            "The AI didn't answer within 8 seconds.",
        ),
        (
            lambda: FakeClient(
                error=anthropic.AuthenticationError(
                    f"invalid x-api-key {KEY}",
                    response=httpx2.Response(401, request=REQ),
                    body=None,
                )
            ),
            "auth",
            "The AI service didn't accept the API key in .env.",
        ),
        (
            lambda: FakeClient(
                error=anthropic.RateLimitError(
                    "slow down", response=httpx2.Response(429, request=REQ), body=None
                )
            ),
            "rate_limited",
            "The AI service is limiting requests for now. Try again later.",
        ),
        (
            lambda: FakeClient(
                error=anthropic.InternalServerError(
                    "overloaded", response=httpx2.Response(529, request=REQ), body=None
                )
            ),
            "http_529",
            "The AI service returned an error (HTTP 529).",
        ),
        (
            lambda: FakeClient(error=anthropic.APIConnectionError(request=REQ)),
            "unreachable",
            "Couldn't reach the AI service. Check the internet connection.",
        ),
        (
            lambda: FakeClient(reply=tool_reply({"explanations": "x", "landlord_message": "y"})),
            "schema",
            "Invalid output: the AI's answer didn't match the required format.",
        ),
        (
            lambda: FakeClient(reply=SimpleNamespace(content=[], stop_reason="end_turn")),
            "no_tool_call",
            "Invalid output: the AI didn't return its answer in the required format.",
        ),
    ],
)
def test_failure_reason_is_reported(make, code, text):
    out, _ = via(make(), timeout=0.2)
    assert (out.ai_reason, out.ai_reason_text) == (code, text)
    dumped = out.model_dump_json()
    assert KEY not in dumped  # even when the API's own error message held it
    assert "findings" not in (out.ai_reason_text or "")  # no request contents


def test_rejected_items_are_named_by_rule_and_check():
    def reply(request):
        payload = json.loads(request["messages"][0]["content"])["findings"]
        data = good_output(payload, landlord_message="Please remove it now.")
        data["explanations"][0]["explanation"] = "This camera is safe."
        return tool_reply(data)

    out, findings = via(FakeClient(reply=reply))
    assert out.ai_reason == "item_checks"
    assert out.ai_rejected == {
        findings[0].rule_id: "reassurance",
        "landlord_message": "no_question",
    }


def test_no_key_and_offline_reasons():
    findings, devices, nearby = room()
    assert (
        explain(findings, settings=NO_KEY).ai_reason_text == "No ANTHROPIC_API_KEY is set in .env."
    )
    assert explain(findings, online=False).ai_reason == "offline"
    out, _ = via(FakeClient(reply=payload_reply))
    assert out.ai_reason is None and out.ai_reason_text is None


def test_cli_prints_the_reason(capsys):
    from app.cli import print_explanations
    from app.discovery.models import DiscoveryResult

    findings, devices, nearby = room()
    out = explain(
        findings,
        devices,
        nearby,
        settings=WITH_KEY,
        call=lambda s, p: (_ for _ in ()).throw(ai.AiUnavailable("timeout")),
    )
    now = datetime.now(UTC)
    result = DiscoveryResult(
        started_at=now,
        finished_at=now,
        mode="full",
        network=None,
        devices=devices,
        checks=[],
        findings=findings,
    )
    print_explanations(result, out)
    assert (
        "Explanations (AI: failed - The AI didn't answer within 8 seconds.)"
        in capsys.readouterr().out
    )
