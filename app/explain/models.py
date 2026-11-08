"""Layer 5 output: one explanation per finding and the landlord message, each with its source."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Source = Literal["ai", "standard"]
AiStatus = Literal["used", "partly_used", "offline", "not_configured", "failed", "rejected", "none"]

AI_LABEL = "Explained by AI from the scan results. The risk level comes from fixed rules."
STANDARD_LABEL = "Standard explanation"
AI_MESSAGE_LABEL = "Drafted by AI from the scan results. Check it before you send it."
STANDARD_MESSAGE_LABEL = "Standard message"
SEND_NOTE = "RoomCheck never sends anything. Edit this message, then send it yourself."


# Why the AI text wasn't used. Fixed sentences only: never the key, the request or the reply.
_REASONS = {
    "timeout": "The AI didn't answer within 8 seconds.",
    "unreachable": "Couldn't reach the AI service. Check the internet connection.",
    "auth": "The AI service didn't accept the API key in .env.",
    "rate_limited": "The AI service is limiting requests for now. Try again later.",
    "refused": "The AI declined to answer.",
    "truncated": "Invalid output: the AI's answer was cut off.",
    "no_tool_call": "Invalid output: the AI didn't return its answer in the required format.",
    "bad_json": "Invalid output: the AI's answer couldn't be read.",
    "schema": "Invalid output: the AI's answer didn't match the required format.",
    "unknown_finding": "Invalid output: the AI mentioned a finding that wasn't in the scan.",
    "duplicate_finding": "Invalid output: the AI explained the same finding twice.",
    "item_checks": "Invalid output: some explanations failed RoomCheck's checks.",
    "missing_items": "Invalid output: the AI left out some findings.",
    "not_configured": "No ANTHROPIC_API_KEY is set in .env.",
    "offline": "Skipped because you chose not to go online.",
}


def reason_text(code: str) -> str:
    if code.startswith("http_") and code[5:].isdigit():
        return f"The AI service returned an error (HTTP {code[5:]})."
    return _REASONS.get(code, "The AI explanation couldn't be used.")


class Explanation(BaseModel):
    finding_id: str
    explanation: str
    why_it_matters: str
    source: Source
    label: str


class LandlordMessage(BaseModel):
    text: str
    source: Source
    label: str
    note: str = SEND_NOTE
    # The findings this message asks about (finding ids). An AI draft is only used where
    # exactly these are still to ask (app/handover/tasks.py bundle_message).
    covers: list[str] = Field(default_factory=list)


class Explanations(BaseModel):
    items: list[Explanation] = Field(default_factory=list)
    landlord_message: LandlordMessage | None = None  # None: no open findings to ask about
    # How the AI step went, for the developer CLI and the API. The UI shows only the labels.
    ai_status: AiStatus = "none"
    ai_reason: str | None = None  # a fixed code, e.g. "timeout", "auth", "http_529", "schema"
    ai_reason_text: str | None = None  # the fixed sentence for that code
    ai_rejected: dict[str, str] = Field(default_factory=dict)  # rule ID -> check that failed

    def for_finding(self, finding_id: str) -> Explanation | None:
        return next((e for e in self.items if e.finding_id == finding_id), None)
