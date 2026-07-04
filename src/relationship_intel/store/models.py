"""Row-level views used by the writer and planner (thin, read-side shapes)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PersonRecord:
    id: int
    name: str
    email: str | None
    title: str | None
    company_id: int | None
    company_name: str | None
    identity_confidence: str
    needs_review: bool
    last_interaction: str | None = None
    profile: dict | None = None
    evidence: list[str] = field(default_factory=list)
    transcripts: list[tuple[str | None, str]] = field(default_factory=list)
    """(meeting_date, title) pairs, in interaction order."""


@dataclass
class CompanyRecord:
    id: int
    name: str
    domain: str | None
    website: str | None
    industry: str | None
    location: str | None
    ownership_context: str | None
    people_names: list[str] = field(default_factory=list)


@dataclass
class OpportunityRecord:
    id: int
    name: str
    person_id: int | None
    person_name: str | None
    company_id: int | None
    company_name: str | None
    stage: str
    lead_type: str
    succession_signal_score: int
    urgency: str
    timing_window: str
    owner: str | None
    next_action: str | None
    next_action_due: str | None
