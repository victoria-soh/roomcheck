"""The optional AI call: a minimal payload out, structured explanations back through tool use.

Data minimisation (docs/original-plan.md): per finding, only the device type, vendor name, evidence
names, rule ID, the rule's fixed title and severity are sent. Finding IDs are replaced by "f1",
"f2", ... because real IDs contain MAC addresses. Evidence names are the fixed signal
descriptions from weights.yaml, never the matched details (which can hold device names).
No IPs, MACs, BSSIDs, SSIDs, Bluetooth addresses or the room label are ever included.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from app.config import Settings
from app.discovery.models import Device
from app.fingerprint.models import Fingerprint
from app.fingerprint.scoring import load_weights
from app.rules.engine import load_rules
from app.rules.models import Finding
from app.wireless.models import NearbyItem

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 8.0
MAX_TOKENS = 4096
MAX_VENDOR_CHARS = 80
TOOL_NAME = "submit_explanations"

SYSTEM_PROMPT = """\
You explain the results of RoomCheck, a tool a tenant or short-stay guest uses to check the \
connected devices and Wi-Fi in a room they just moved into. Fixed rules have already decided \
every finding and its severity. Your job is only to explain them in plain words.

Rules:
- Write for a secondary-school reading level. Short sentences. Explain any technical word.
- For each finding, give an explanation (what was found) and why_it_matters (what could \
happen). Keep both together under 70 words.
- Never change, question or soften a severity, and don't describe how serious a finding is \
in your own words. Don't call anything high, medium or low risk.
- Never say or suggest that anything is safe, harmless, risk-free or fine, or that the \
user can ignore it.
- Findings are unconfirmed: clues, not proof. Never say "definitely", \
"certainly" or "confirmed". The page already says once that device types are \
unconfirmed, so don't repeat "clue, not proof" in each explanation.
- Use RoomCheck's words for uncertainty exactly: "Not detected" (the check ran and \
flagged no issue), "Not checked" (the check couldn't run, or only partly ran), "Unconfirmed" \
(a clue, not proof). Never say "skipped", "not run", "nothing found" or "a hint, not proof".
- Only mention devices and findings that are in the input.
- Each finding has rule_text, the rule's own fixed wording. Stay within it: don't add claims \
that make a finding more or less serious than rule_text says, and don't guess where a device \
is or whose it is.
- RoomCheck only knows a device is on this network or heard nearby, never where it is. Never \
say a device is "in the room", "in this room", "in your room", "here", or in any other place. \
Say "on this network" for devices on the network, and "nearby" only for Wi-Fi or Bluetooth \
heard that isn't this network's router.
- Say what was observed as fact, and anything inferred from it as possible: "could", \
"may", "if". For example, "The router advertises WPS. If PIN-based WPS is enabled, \
the PIN could be guessed", never "the PIN can be guessed".
- Never say or suggest whose a device or tracker is: not that it is or isn't the user's, \
belongs to someone else, or is "unknown to you". RoomCheck can't know. For trackers, ask \
"Do you recognise this tracker?" instead.
- For known issues (rule R-CVE), don't speculate about whether they affect this exact \
device, in either direction. Say it isn't confirmed for this device.
- landlord_message: one short, polite message to the host about the findings \
marked in_message, and nothing else: don't mention any other finding, device or setting. Ask \
questions, for example "Could you confirm what this device is?". Write as the one person \
sending it: "I", "my", never "we", "our" or "us"; say "the router" and "the Wi-Fi", not "our \
router". A device that looks like a camera is "the device that may be a camera", never "the \
camera" or "the camera device". Never accuse anyone or say anyone did something wrong, and \
don't mention the law or the police. Under 200 words. If no finding is marked in_message, \
return an empty string.

Call the submit_explanations tool exactly once with your answer. When you use a tool, you may \
say a brief sentence first. If no tool can express what the user asked for, say so instead of \
guessing. Do not include internal or system XML tags in your response."""

# Models where thinking can't be switched off; they run at the lowest effort instead.
_ALWAYS_THINKING = ("claude-opus-5-5", "claude-fable-5", "claude-mythos-5")


def thinking_off(model: str) -> dict[str, str] | None:
    """The thinking setting that turns thinking off for `model`, or None where it can't be.

    Explanations are short rewrites of decided findings, so thinking only adds latency under
    the 8 s limit. Claude Sonnet 5.5 rejects "disabled" and uses "between_tools" instead
    (accepted at low effort); Opus 5.5 and Fable 5.x can't turn it off at all.
    """
    m = model.lower()
    if m.startswith("claude-sonnet-5-5"):
        return {"type": "between_tools"}
    if m.startswith(_ALWAYS_THINKING):
        return None
    return {"type": "disabled"}


def _tool(finding_ids: list[str]) -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": "Submit one plain explanation per finding, and the landlord message.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "explanations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "finding_id": {"type": "string", "enum": finding_ids},
                            "explanation": {"type": "string"},
                            "why_it_matters": {"type": "string"},
                        },
                        "required": ["finding_id", "explanation", "why_it_matters"],
                        "additionalProperties": False,
                    },
                },
                "landlord_message": {"type": "string"},
            },
            "required": ["explanations", "landlord_message"],
            "additionalProperties": False,
        },
    }


class AiUnavailable(Exception):
    """The AI call didn't produce usable output. `reason` is a short code for logs."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --- payload ---------------------------------------------------------------------------------


def _type_ids(rule_id: str) -> list[str]:
    rule = next((r for r in load_rules().rules if r.id == rule_id), None)
    if rule is None:
        return []
    args = rule.when[rule.predicate_name()]
    if "type" in args:
        return [str(args["type"])]
    return [str(t) for t in args.get("types", [])]


def evidence_names(fp: Fingerprint | None, type_ids: list[str]) -> list[str]:
    """Fixed descriptions of the signals that matched, from weights.yaml."""
    if fp is None:
        return []
    weights = load_weights()
    scores = [(fp.type, fp.evidence)] + [
        (t.type, t.evidence) for t in fp.other_types + fp.weak_types
    ]
    names: list[str] = []
    for type_id, evidence in scores:
        if type_id not in type_ids or type_id not in weights.types:
            continue
        fixed = {s.id: s.evidence for s in weights.types[type_id].signals}
        names += [fixed[e.signal] for e in evidence if e.signal in fixed]
    return list(dict.fromkeys(names))


def build_payload(
    findings: Sequence[Finding], devices: Sequence[Device], nearby: Sequence[NearbyItem]
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """(payload, local id -> real finding id)."""
    by_device = {d.id: d for d in devices}
    by_ref = {i.ref: i for i in nearby}
    payload: list[dict[str, Any]] = []
    ids: dict[str, str] = {}
    for n, f in enumerate(findings, 1):
        local = f"f{n}"
        ids[local] = f.id
        entry: dict[str, Any] = {
            "finding_id": local,
            "rule_id": f.rule_id,
            "rule_title": f.title,
            "severity": f.severity,
            # The rule's fixed text from rules.yaml (no device data), to anchor the wording.
            "rule_text": f"{f.standard_explanation} {f.standard_why}".strip(),
            # The landlord message covers exactly these (High or Medium, with a question).
            "in_message": f.severity in ("High", "Medium") and bool(f.landlord_question),
        }
        device = by_device.get(f.device_ref or "")
        item = by_ref.get(f.nearby_ref or "")
        vendor: str | None = None
        if device is not None:
            entry["device_type"] = device.fingerprint.label if device.fingerprint else "Device"
            vendor = device.vendor
            names = evidence_names(device.fingerprint, _type_ids(f.rule_id))
            if names:
                entry["evidence"] = names
        elif item is not None:
            # A Wi-Fi item's label holds its network name, so only the kind is sent. Only
            # access points the laptop isn't connected to are "nearby".
            if item.kind != "wifi":
                entry["device_type"] = item.label
            elif item.connected:
                entry["device_type"] = "This network's router or access point"
            else:
                entry["device_type"] = "Nearby Wi-Fi access point"
            vendor = item.maker
        else:
            entry["device_type"] = "Your network"
        if vendor:
            entry["vendor"] = vendor[:MAX_VENDOR_CHARS]
        payload.append(entry)
    return payload, ids


# --- the shared client and its warm-up ---------------------------------------------------------

KEEPALIVE_SECONDS = 300.0  # keep the warmed connection through a scan (httpx2's default is 5 s)

_client_lock = threading.Lock()
_client: Any = None
_client_key: str | None = None  # SHA-256 of the key the shared client was built with


def _build_client(api_key: str) -> Any:
    import anthropic
    import httpx2

    return anthropic.Anthropic(
        api_key=api_key,
        timeout=TIMEOUT_SECONDS,
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(
            limits=httpx2.Limits(
                max_connections=10, max_keepalive_connections=2, keepalive_expiry=KEEPALIVE_SECONDS
            )
        ),
    )


def shared_client(settings: Settings) -> Any:
    """One Anthropic client for the whole process, so its connection can be reused."""
    global _client, _client_key
    assert settings.anthropic_api_key is not None
    key = settings.anthropic_api_key.get_secret_value()
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    with _client_lock:
        if _client is None or _client_key != fingerprint:
            _client = _build_client(key)
            _client_key = fingerprint
        return _client


def reset_shared_client() -> None:
    global _client, _client_key
    with _client_lock:
        _client, _client_key = None, None


def reason_for(exc: BaseException) -> str:
    """A fixed reason code for an SDK error. Never the error's message, which may hold data."""
    import anthropic

    if isinstance(exc, FutureTimeout | anthropic.APITimeoutError):
        return "timeout"
    if isinstance(exc, anthropic.APIConnectionError):
        return "unreachable"
    if isinstance(exc, anthropic.AuthenticationError):
        return "auth"
    if isinstance(exc, anthropic.RateLimitError):
        return "rate_limited"
    if isinstance(exc, anthropic.APIStatusError):
        return f"http_{exc.status_code}"
    return "internal"


def warm_up(settings: Settings, client: Any = None) -> str | None:
    """Pay the one-off costs before the first explanation: build the client, open and keep a
    TLS connection, and load the SDK's messages module. Uses a free request (listing one
    model) and sends nothing about the scan. Returns None, or a reason code (logged only)."""
    try:
        client = client if client is not None else shared_client(settings)
        client.models.list(limit=1)
        _ = client.messages  # the SDK loads this resource lazily on first use
        return None
    except Exception as e:
        code = reason_for(e)
        log.info("AI warm-up failed (%s); explanations will still be tried", code)
        return code


def start_warm_up(settings: Settings) -> threading.Thread | None:
    """Warm up in the background; returns the thread, or None when there's no key."""
    if settings.anthropic_api_key is None:
        return None
    thread = threading.Thread(target=warm_up, args=(settings,), name="ai-warm-up", daemon=True)
    thread.start()
    return thread


# --- the call --------------------------------------------------------------------------------


def _create(settings: Settings, payload: list[dict[str, Any]], client: Any) -> Any:
    tool = _tool([p["finding_id"] for p in payload])
    options: dict[str, Any] = {}
    thinking = thinking_off(settings.anthropic_model)
    if thinking is not None:
        options["thinking"] = thinking
    return client.messages.create(
        model=settings.anthropic_model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[tool],
        # Forced tool choice is rejected by several current models, so steer from the prompt
        # and rely on strict schemas; a reply without the tool call is treated as invalid.
        tool_choice={"type": "auto"},
        output_config={"effort": "low"},
        messages=[
            {"role": "user", "content": json.dumps({"findings": payload}, ensure_ascii=False)}
        ],
        **options,
    )


def call_ai(
    settings: Settings,
    payload: list[dict[str, Any]],
    *,
    client_factory: Callable[..., Any] | None = None,
    timeout: float = TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """The tool input Claude submitted. Raises AiUnavailable; never logs the key or the reply.

    Uses the shared, warmed client unless `client_factory` is given (tests).
    """
    assert settings.anthropic_api_key is not None
    if client_factory is not None:
        client = client_factory(
            api_key=settings.anthropic_api_key.get_secret_value(),
            timeout=TIMEOUT_SECONDS,
            max_retries=0,
        )
    else:
        client = shared_client(settings)
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="explain")
    try:
        # The SDK timeout applies per network phase; this caps the whole call at 8 s.
        response = pool.submit(_create, settings, payload, client).result(timeout=timeout)
    except Exception as e:  # any failure falls back to the standard text
        raise AiUnavailable(reason_for(e)) from e
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if getattr(response, "stop_reason", None) == "refusal":
        raise AiUnavailable("refused")
    if getattr(response, "stop_reason", None) == "max_tokens":
        raise AiUnavailable("truncated")
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL_NAME:
            data = block.input
            if isinstance(data, str):  # parse, never string-match, the tool input
                try:
                    data = json.loads(data)
                except ValueError as e:
                    raise AiUnavailable("bad_json") from e
            if not isinstance(data, dict):
                raise AiUnavailable("bad_json")
            return data
    raise AiUnavailable("no_tool_call")
