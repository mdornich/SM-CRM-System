"""Message drafts. Every draft is explicitly marked DRAFT — this system never
sends anything (ORD-0003 Level 2: drafting is not sending; marking is required)."""

from __future__ import annotations

DRAFT_MARKER = "DRAFT — not sent"

_FALLBACKS = {
    "warm": "{first}, I enjoyed our recent conversation and wanted to follow up "
    "on the timing we discussed. Open to a quick call this week?",
    "referral_source": "{first}, thank you again for offering introductions — "
    "happy to make that as easy as possible for you and your clients.",
    "cold": "{first}, it's been a while since we last spoke — no agenda, just "
    "checking in on how the business is going.",
}


def draft_for(person_name: str, lead_type: str, suggested_message: str | None) -> str:
    first = person_name.split()[0] if person_name else "there"
    body = suggested_message or _FALLBACKS.get(lead_type, "").format(first=first)
    if not body:
        return ""
    return f"{DRAFT_MARKER}: {body}"
