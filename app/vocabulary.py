"""One vocabulary for uncertainty, used in the UI, the report and the AI's rules.

  Not detected  the check ran, and found nothing to flag
  Not checked   the check didn't run, or was limited
  Unconfirmed   a clue, not proof
  Resolved      a handover task's status, when the user says it's sorted

OLD_PHRASES are the wordings these replaced. A test checks that none of them is left in any
user-facing text, and the AI validator rejects them in explanations.
"""

from __future__ import annotations

import re

NOT_DETECTED = "Not detected"
NOT_CHECKED = "Not checked"
UNCONFIRMED = "Unconfirmed"
RESOLVED = "Resolved"
# The phrase for anything inferred from limited evidence (types, makers, lookalikes, trackers).
CLUES_NOT_PROOF = "unconfirmed: clues, not proof"

OLD_PHRASES = re.compile(
    r"\bflagged nothing\b|\bnothing (was )?found\b|\bno issues found\b|\bnothing to flag\b"
    r"|\bskipped\b|\bnot run\b|\bdidn'?t run\b|\bcouldn'?t be checked\b"
    r"|\bhints?, not proof\b|\bcontext, not proof\b|\bis not proof\b|\bisn'?t proof\b"
    r"|\bfrom limited evidence\b",
    re.IGNORECASE,
)


def old_phrase(text: str) -> str | None:
    """The first old phrasing in a text, or None."""
    m = OLD_PHRASES.search(text)
    return m.group(0) if m else None
