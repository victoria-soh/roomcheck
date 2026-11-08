"""Check AI output before anything reaches the user. Fixed rules decide; the AI only explains.

Rejected as a whole (every finding falls back to its standard text):
  - output that doesn't match the schema, or names a finding that isn't in the input,
    or explains one finding twice.
Rejected per explanation (that finding falls back to its standard text):
  - longer than about 80 words (explanation and why_it_matters together),
  - reassurance ("safe", "no risk", "nothing to worry about", ...),
  - changing or softening the severity ("low risk" on a High finding, "just a minor issue"),
  - overclaiming ("definitely", "confirmed"): findings are hints, not proof,
  - anything that looks like an IP or MAC address,
  - on High or Medium findings, saying it isn't a problem ("not a fault", "isn't a problem"),
  - on R-CVE, claiming the reported issues do or don't affect this exact device,
  - saying where a device is ("in the room", "in your room"): RoomCheck only knows it's on
    this network or heard nearby.
Wording drift that can't be caught by an exact phrase (e.g. guessing whose a device is) is
handled by the payload and the prompt, not by fuzzy matching here.
The landlord message is rejected if it reassures, accuses or threatens, asks no question,
is too long, or holds an address; if it isn't written as the one sender ("we", "our", "us");
if it calls an unconfirmed camera finding "the camera"; or if it mentions a finding outside
the set it's meant to cover (e.g. a device the user marked as theirs).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.vocabulary import old_phrase

MAX_WORDS = 80
MAX_MESSAGE_WORDS = 250

_REASSURANCE = re.compile(
    r"\bsafe(ly|ty|r|st)?\b|\bno risks?\b|\brisk[- ]free\b|\bharmless\b|\bnothing to worry\b"
    r"|\bno need to (worry|be concerned)\b|\bdon'?t worry\b|\bdo not worry\b"
    r"|\bcan (safely )?(be )?ignored?\b|\bignore (it|this)\b"
    r"|\b(probably|perfectly|totally) fine\b|\bis fine\b|\bno danger\b"
    r"|\bnot (a )?(big|real|serious|major) (deal|problem|issue|concern|risk)\b"
    r"|\bnothing serious\b|\bnot serious\b|\b(just|only) a (small|minor)\b"
    r"|\bunlikely to (be|cause) (a |any )?(problem|issue|risk|harm)",
    re.IGNORECASE,
)
_OVERCLAIM = re.compile(
    r"\bdefinitely\b|\bcertainly\b|\bfor sure\b|\bwithout (a |any )?doubt\b|\b100 ?%"
    r"|\bguaranteed?\b|\bconfirm(ed|s) (that|it|this)\b|\bproves?\b",
    re.IGNORECASE,
)
_LEVEL = r"(high|critical|severe|serious|medium|moderate|low|minor|informational)"
_SEVERITY_TALK = [
    re.compile(rf"\b{_LEVEL}[- ](risk|severity|priority|threat|danger)\b", re.IGNORECASE),
    re.compile(
        rf"\b(risk|severity|priority|threat|danger)( level)?( is| of| rated| seems| looks)?"
        rf"( (quite|very|fairly|rather))? {_LEVEL}\b",
        re.IGNORECASE,
    ),
]
_LEVEL_TO_SEVERITY = {
    "high": "High",
    "critical": "High",
    "severe": "High",
    "serious": "High",
    "medium": "Medium",
    "moderate": "Medium",
    "low": "Low",
    "minor": "Low",
    "informational": "Info",
}
# High and Medium findings only: exact phrases that say the finding isn't a real problem.
# Deliberately literal; anything fuzzier would reject honest text.
_DOWNPLAY = re.compile(
    r"\bnot a (fault|problem|flaw|concern|threat|danger)\b"
    r"|\b(isn'?t|is not|aren'?t|are not) (a |any )?(real |big |serious |major )?"
    r"(problem|issue|fault|concern|threat|danger)\b"
    r"|\bnothing (is )?wrong\b|\bno cause for (concern|alarm)\b"
    r"|\bnot a cause for (concern|alarm)\b",
    re.IGNORECASE,
)
# R-CVE only: claims, either way, about whether the reported issues affect this exact device.
# The firmware version is never confirmed, so neither "affected" nor "not affected" is known.
_DEVICE_CLAIM = re.compile(
    r"\bnot a (fault|flaw|problem|weakness|vulnerability) (found |seen |present )?in (this|your)"
    r" (exact )?(device|camera|model)\b"
    r"|\b(this|your|the) (device|camera) (is|isn'?t|is not) (affected|vulnerable|exposed)\b"
    r"|\b(does|do)(n'?t| not) (affect|apply to) (this|your) (device|camera)\b"
    r"|\b(affects|applies to) (this|your) (device|camera)\b",
    re.IGNORECASE,
)
# A sentence that says it's unknown ("It isn't confirmed whether this device is affected")
# is the wording the prompt asks for, so _DEVICE_CLAIM only counts in sentences without one.
_HEDGE = re.compile(
    r"\bwhether\b|\b(not|isn'?t|can'?t be|cannot be|hasn'?t been|has not been) (yet )?"
    r"(confirmed|known|checked)\b|\bunknown\b|\bmay\b|\bmight\b|\bcould\b",
    re.IGNORECASE,
)
# RoomCheck never knows where a device is, only that it's on this network or heard nearby.
_LOCATION = re.compile(
    r"\bin (the|this|your) (room|bedroom|space|flat|apartment|unit)\b", re.IGNORECASE
)
# WPS: RoomCheck sees that WPS is advertised, not that a PIN can be guessed.
_WPS_CLAIM = re.compile(
    r"\b(pin|wps)\b[^.]*\b(can|will) be (guessed|cracked|brute[- ]?forced)\b"
    r"|\bopen to (pin )?brute[- ]?forc",
    re.IGNORECASE,
)
_CONDITIONAL = re.compile(r"\bif\b|\bcould\b|\bmay\b|\bmight\b", re.IGNORECASE)
# RoomCheck can't know whose a device or tracker is, so the text never says.
_OWNERSHIP = re.compile(
    r"\b(isn'?t|is not|aren'?t|are not|not) (yours|your own|the user'?s)\b"
    r"|\b(doesn'?t|does not|don'?t|do not) (seem to )?belong to (you|the user)\b"
    r"|\bbelongs? to (someone|somebody|another person|a stranger)( else)?\b"
    r"|\b(someone|somebody) else'?s\b|\bnot (owned by|from) you\b",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _unhedged_device_claim(text: str) -> bool:
    return any(_DEVICE_CLAIM.search(s) and not _HEDGE.search(s) for s in _SENTENCE.split(text))


_IDENTIFIER = re.compile(
    r"\b\d{1,3}(\.\d{1,3}){3}\b|\b[0-9a-f]{2}([:-][0-9a-f]{2}){5}\b", re.IGNORECASE
)
_ACCUSATION = re.compile(
    r"\byou (are|were|have been|'re) (spying|recording|watching|tracking|filming|lying)"
    r"|\bspy(ing)? on\b|\billegal(ly)?\b|\bviolat|\bbreach|\blied\b|\bsecretly\b"
    r"|\bpolice\b|\blawyer\b|\bsue\b|\breport you\b|\byou must\b|\bhidden camera\b"
    r"|\bcriminal\b|\bunacceptable\b",
    re.IGNORECASE,
)


class OutputRejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# The sender is one person: "I", never "we", "our" or "us" ("the router", not "our router").
_PLURAL_SENDER = re.compile(r"\b(we|we'?ve|we'?re|we'?d|we'?ll|our|ours|us)\b", re.IGNORECASE)
# Stating an unconfirmed camera finding as a camera. "the device that may be a camera",
# "a camera-like device" and "a camera's setup network" are fine.
_CAMERA_AS_FACT = re.compile(
    r"\b(?:the|this|that|your) cameras?\b(?![- ]like|'s setup)(?: devices?\b)?", re.IGNORECASE
)
UNCONFIRMED_CAMERA = "the device that may be a camera"
CAMERA_RULES = frozenset({"R-CAM", "R-NEW-CAMERA", "R-CAMHOT"})

# What each finding is about, as the words a message would use for it. A message may only
# mention topics of the findings it covers.
TOPICS: dict[str, re.Pattern[str]] = {
    "camera": re.compile(r"\bcameras?\b", re.IGNORECASE),
    "wps": re.compile(r"\bwps\b", re.IGNORECASE),
    "known_issues": re.compile(
        r"\bfirmware\b|\bknown (?:security )?(?:issues|problems)\b|\bvulnerab\w*|\bcves?\b"
        r"|\bup to date\b|\bbeen updated\b",
        re.IGNORECASE,
    ),
    "upnp": re.compile(r"\bupnp\b", re.IGNORECASE),
    "telnet": re.compile(r"\btelnet\b", re.IGNORECASE),
    "lock": re.compile(r"\b(?:smart )?locks?\b|\bdoorbells?\b", re.IGNORECASE),
    "cloud": re.compile(r"\bcloud\b|\bwhose account\b|\blinked to\b", re.IGNORECASE),
    "encryption": re.compile(r"\bwep\b|\bno password\b|\bunencrypted wi-?fi\b", re.IGNORECASE),
    "dns": re.compile(r"\bdns\b|\baddress lookups?\b", re.IGNORECASE),
    "router_answer": re.compile(r"\banswer(?:s|ed)? for the router\b", re.IGNORECASE),
    "dhcp": re.compile(r"\bdhcp\b|\bhand(?:s|ing)? out (?:network )?addresses\b", re.IGNORECASE),
    "lookalike": re.compile(
        r"\blookalike\b|\bsame (?:wi-?fi )?name\b|\bcopy of (?:the|this|your) wi-?fi\b",
        re.IGNORECASE,
    ),
    "tracker": re.compile(r"\btrackers?\b|\bairtags?\b", re.IGNORECASE),
    "hidden": re.compile(r"\bhidden (?:wi-?fi|network)s?\b", re.IGNORECASE),
}
RULE_TOPICS: dict[str, str] = {
    "R-CAM": "camera",
    "R-NEW-CAMERA": "camera",
    "R-CAMHOT": "camera",
    "R-WPS": "wps",
    "R-CVE": "known_issues",
    "R-UPNP": "upnp",
    "R-TELNET": "telnet",
    "R-LOCK": "lock",
    "R-CLOUD": "cloud",
    "R-WIFI-ENC": "encryption",
    "R-OPEN": "encryption",
    "R-DNS": "dns",
    "R-ARP": "router_answer",
    "R-DHCP": "dhcp",
    "R-TWIN": "lookalike",
    "R-TWIN-VENDOR": "lookalike",
    "R-TWIN-DOWNGRADE": "lookalike",
    "R-TRACKER": "tracker",
    "R-HIDDEN": "hidden",
}


def mentioned_topics(text: str) -> set[str]:
    return {topic for topic, pattern in TOPICS.items() if pattern.search(text)}


def hedge_camera(text: str) -> str:
    """The template guard: an unconfirmed camera finding is never called "the camera"."""
    return _CAMERA_AS_FACT.sub(UNCONFIRMED_CAMERA, text)


def template_problem(text: str) -> str | None:
    """Why a fixed template (a rule's question or a task's ask) breaks the message rules."""
    if _PLURAL_SENDER.search(text):
        return "not_first_person"
    if _CAMERA_AS_FACT.search(text):
        return "camera_overclaim"
    return None


class AiItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    explanation: str
    why_it_matters: str


class AiOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explanations: list[AiItem]
    landlord_message: str


def words(text: str) -> int:
    return len(text.split())


def problem_with_text(text: str, severity: str, rule_id: str = "") -> str | None:
    """Why one explanation can't be shown, or None if it's acceptable."""
    if not text.strip():
        return "empty"
    if words(text) > MAX_WORDS:
        return "too_long"
    if _REASSURANCE.search(text):
        return "reassurance"
    if _OVERCLAIM.search(text):
        return "overclaim"
    if _IDENTIFIER.search(text):
        return "identifier"
    for pattern in _SEVERITY_TALK:
        for m in pattern.finditer(text):
            level = next(g for g in m.groups() if g and g.lower() in _LEVEL_TO_SEVERITY)
            if _LEVEL_TO_SEVERITY[level.lower()] != severity:
                return "severity_changed"
    if severity in ("High", "Medium") and _DOWNPLAY.search(text):
        return "downplays"
    if rule_id == "R-CVE" and _unhedged_device_claim(text):
        return "unconfirmed_claim"
    if any(_WPS_CLAIM.search(s) and not _CONDITIONAL.search(s) for s in _SENTENCE.split(text)):
        return "unconfirmed_claim"
    if _LOCATION.search(text):
        return "location_claim"
    if _OWNERSHIP.search(text):
        return "ownership_claim"
    if old_phrase(text):
        return "vocabulary"
    if rule_id in CAMERA_RULES and _CAMERA_AS_FACT.search(text):
        return "camera_overclaim"
    return None


def parse_output(raw: Any, known_ids: set[str]) -> AiOutput:
    """Whole-output checks. Raises OutputRejected."""
    try:
        out = AiOutput.model_validate(raw)
    except ValidationError as e:
        raise OutputRejected("schema") from e
    seen: set[str] = set()
    for item in out.explanations:
        if item.finding_id not in known_ids:
            raise OutputRejected("unknown_finding")
        if item.finding_id in seen:
            raise OutputRejected("duplicate_finding")
        seen.add(item.finding_id)
    return out


def check_explanation(item: AiItem, severity: str, rule_id: str = "") -> str | None:
    return problem_with_text(f"{item.explanation} {item.why_it_matters}", severity, rule_id)


def check_landlord_message(
    text: str, covers: Iterable[str] | None = None, *, camera_confirmed: bool = False
) -> str | None:
    """Why the drafted message can't be used, or None. covers: the rule ids of the findings
    the message is meant to ask about; anything it mentions must be one of them."""
    if not text.strip():
        return "empty"
    if words(text) > MAX_MESSAGE_WORDS:
        return "too_long"
    if _REASSURANCE.search(text):
        return "reassurance"
    if _ACCUSATION.search(text):
        return "accusation"
    if _IDENTIFIER.search(text):
        return "identifier"
    if "?" not in text:
        return "no_question"
    if _PLURAL_SENDER.search(text):
        return "not_first_person"
    if not camera_confirmed and _CAMERA_AS_FACT.search(text):
        return "camera_overclaim"
    if covers is not None:
        allowed = {RULE_TOPICS[r] for r in covers if r in RULE_TOPICS}
        if mentioned_topics(text) - allowed:
            return "mentions_excluded"
    return None
