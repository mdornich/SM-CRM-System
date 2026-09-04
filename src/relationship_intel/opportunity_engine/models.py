"""Product-neutral immutable proposals. Only repositories persist canonical state."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

Key = Annotated[str, Field(min_length=1, pattern=r"\S")]
Score = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    id: Key


class Product(Record):
    name: Key
    description: Key


class ProductPackVersion(Record):
    product_id: Key
    version: Key
    policy: dict[str, JsonValue]
    fixture_only: bool = False


class Evidence(Record):
    source_type: Key
    source_ref: Key
    content_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    locator: Key
    excerpt: Key
    captured_at: AwareDatetime
    occurred_at: AwareDatetime | None = None


class SubjectRecord(Record):
    account_id: Annotated[int, Field(gt=0)] | None = None
    person_id: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def subject_required(self):
        if self.account_id is None and self.person_id is None:
            raise ValueError("an account or person is required")
        return self


class Observation(SubjectRecord):
    evidence_id: Key
    predicate: Key
    value: JsonValue
    method: Key
    confidence: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class SignalDefinition(Record):
    pack_version_id: Key
    key: Key
    description: Key


class SignalObservation(Record):
    definition_id: Key
    observation_id: Key
    strength: Score
    rationale: Key


class ScoreDimensions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    fit: Score | None = None
    timing_signal: Score | None = None
    evidence_quality: Score | None = None
    stakeholder_relevance: Score | None = None
    reachability: Score | None = None
    contradiction_penalty: Score | None = None
    cost_to_pursue: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None


class OpportunityHypothesis(SubjectRecord):
    pack_version_id: Key
    episode_key: Key
    thesis: Key
    created_at: AwareDatetime
    signal_ids: tuple[Key, ...] = Field(min_length=1)
    observation_ids: tuple[Key, ...] = Field(min_length=1)
    scores: ScoreDimensions
    scoring_version: Key
    # No mutation/approval API is shipped in the foundation slice.
    state: Literal["HYPOTHESIS_CREATED"] = "HYPOTHESIS_CREATED"
    review_status: Literal["unreviewed"] = "unreviewed"

    @model_validator(mode="after")
    def unique_signals(self):
        if len(set(self.observation_ids)) != len(self.observation_ids):
            raise ValueError("observation_ids must be unique")
        if len(set(self.signal_ids)) != len(self.signal_ids):
            raise ValueError("signal_ids must be unique")
        return self
