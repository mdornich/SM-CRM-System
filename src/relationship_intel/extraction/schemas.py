"""Pydantic schema set — the closed vocabularies and models from docs/build-prompt.md
§"Extraction schema", plus the architecture.md §5 additions (identity_confidence,
needs_review, llm_provider/lens_version provenance, approval_status, review_status)."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class LeadType(StrEnum):
    cold = "cold"
    warm = "warm"
    active = "active"
    referral_source = "referral_source"
    partner = "partner"
    not_fit = "not_fit"
    unknown = "unknown"


# Lead types that count as an active prospect (create opportunities, enter the
# pipeline). Single source — weekly_plan, pipeline, and templates all import this.
# StrEnum members equal their string values, so post-model_dump dicts compare too.
PROSPECT_LEAD_TYPES = frozenset({LeadType.cold, LeadType.warm, LeadType.active})


class Stage(StrEnum):
    new = "new"
    nurture = "nurture"
    discovery = "discovery"
    qualified = "qualified"
    active_opportunity = "active_opportunity"
    stalled = "stalled"
    closed_won = "closed_won"
    closed_lost = "closed_lost"
    not_fit = "not_fit"


class Urgency(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    unknown = "unknown"


class TimingWindow(StrEnum):
    immediate = "immediate"
    months_0_3 = "0_3_months"
    months_3_6 = "3_6_months"
    months_6_12 = "6_12_months"
    long_term = "long_term"
    unknown = "unknown"


class IdentityConfidence(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class ReviewStatus(StrEnum):
    """ORD-0003 review-status model. AI synthesis defaults to unreviewed."""

    unreviewed = "unreviewed"
    reviewed = "reviewed"
    corrected = "corrected"
    confirmed = "confirmed"


class ApprovalStatus(StrEnum):
    """Phase 0: everything stays `proposed`; CRM upserts are pre-authorized-additive."""

    proposed = "proposed"
    approved = "approved"
    rejected = "rejected"
    executed = "executed"


class TranscriptMetadata(BaseModel):
    source_system: str = "local"
    source_id: str
    title: str
    meeting_date: date | None = None
    owner: str | None = None
    attendees: list[str] = Field(default_factory=list)
    transcript_hash: str


class Person(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    title: str | None = None
    role_in_opportunity: str | None = None
    relationship_to_owner: str | None = None
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    identity_confidence: IdentityConfidence = IdentityConfidence.high
    needs_review: bool = False


class Company(BaseModel):
    name: str
    website: str | None = None
    industry: str | None = None
    location: str | None = None
    size_estimate: str | None = None
    ownership_context: str | None = None
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class SuccessionLeadProfile(BaseModel):
    person_name: str
    company_name: str | None = None
    lead_type: LeadType = LeadType.unknown
    stage: Stage = Stage.new
    succession_signal_score: int = Field(default=0, ge=0, le=100)
    urgency: Urgency = Urgency.unknown
    timing_window: TimingWindow = TimingWindow.unknown
    business_owner_signal: bool | None = None
    exit_or_transition_signal: bool | None = None
    pain_points: list[str] = Field(default_factory=list)
    stated_goals: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    buying_signals: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_best_action: str | None = None
    next_action_due_window: str | None = None
    recommended_cadence: str | None = None
    suggested_message: str | None = None
    confidence: float = 0.0
    evidence_snippets: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _classification_requires_evidence(self) -> SuccessionLeadProfile:
        if self.lead_type != LeadType.unknown and not self.evidence_snippets:
            raise ValueError(
                f"lead_type={self.lead_type.value!r} requires at least one evidence snippet"
            )
        return self


class ConversationSummary(BaseModel):
    concise_summary: str = ""
    key_quotes: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    follow_up_items: list[str] = Field(default_factory=list)
    who_owes_what: list[str] = Field(default_factory=list)


class RecommendedCRMAction(BaseModel):
    action: str
    target: str
    detail: str | None = None
    approval_status: ApprovalStatus = ApprovalStatus.proposed


class ExtractedRelationshipIntelligence(BaseModel):
    transcript_metadata: TranscriptMetadata
    people: list[Person] = Field(default_factory=list)
    companies: list[Company] = Field(default_factory=list)
    lead_profiles: list[SuccessionLeadProfile] = Field(default_factory=list)
    conversation_summary: ConversationSummary = Field(default_factory=ConversationSummary)
    recommended_crm_actions: list[RecommendedCRMAction] = Field(default_factory=list)
    recommended_obsidian_notes: list[str] = Field(default_factory=list)
    llm_provider: str = "mock"
    lens_version: str = ""
    review_status: ReviewStatus = ReviewStatus.unreviewed
