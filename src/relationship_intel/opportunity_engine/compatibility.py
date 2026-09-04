"""Opt-in, exact-quote projection of a legacy profile into generic shadow state."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from relationship_intel.extraction.schemas import SuccessionLeadProfile
from relationship_intel.intake.local_folder import RawTranscript
from relationship_intel.opportunity_engine.models import (
    Evidence,
    Observation,
    OpportunityHypothesis,
)
from relationship_intel.opportunity_engine.repository import OpportunityRepository
from relationship_intel.opportunity_engine.succession import SuccessionPack


def _key(*parts: str) -> str:
    import json

    return sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def project_legacy_profile(
    repo: OpportunityRepository,
    raw: RawTranscript,
    profile: SuccessionLeadProfile,
    *,
    account_id: int | None,
    person_id: int,
    lens_version: str,
    llm_provider: str,
    captured_at: datetime,
) -> OpportunityHypothesis | None:
    """Use already-resolved IDs. Never re-resolve a name or write legacy rows.

    Approximate/paraphrased legacy snippets fail closed: their original attribution
    cannot be proven by this bridge. Review those cases instead of inventing quotes.
    Keep captured_at stable on replay (the original ingest timestamp).
    """
    pack = SuccessionPack()
    if lens_version != pack.version.policy["lens_version"]:
        raise ValueError("legacy lens version is not supported by this adapter")
    observations = []
    with repo.transaction():
        for quote in dict.fromkeys(profile.evidence_snippets):
            offset = raw.raw_text.find(quote)
            if offset < 0:
                raise ValueError("legacy snippet is not an exact source quote")
            if raw.raw_text.find(quote, offset + 1) >= 0:
                raise ValueError("repeated source quote requires explicit attribution review")
            locator = f"chars:{offset}:{offset + len(quote)}"
            evidence_id = _key(raw.source_system, raw.source_id, raw.transcript_hash, locator)
            repo.put(
                Evidence(
                    id=evidence_id,
                    source_type="transcript",
                    source_ref=f"{raw.source_system}:{raw.source_id}",
                    content_hash=raw.transcript_hash,
                    locator=locator,
                    excerpt=quote,
                    captured_at=captured_at,
                )
            )
            method = f"legacy-extraction:{llm_provider}:{lens_version}"
            observation = Observation(
                id=_key(evidence_id, str(account_id), str(person_id), method),
                account_id=account_id,
                person_id=person_id,
                evidence_id=evidence_id,
                predicate="statement",
                value=quote,
                method=method,
                confidence=profile.confidence,
            )
            repo.put(observation)
            observations.append(observation)
        assessment = pack.from_profile(profile, tuple(observations))
        repo.put(pack.product)
        repo.put(pack.version)
        for definition in pack.definitions:
            repo.put(definition)
        for signal in assessment.signals:
            repo.put(signal)
        if not assessment.eligible:
            return None
        hypothesis = OpportunityHypothesis(
            id=_key(pack.version.id, raw.transcript_hash, str(person_id), str(account_id)),
            account_id=account_id,
            person_id=person_id,
            pack_version_id=pack.version.id,
            episode_key=f"legacy-transcript:{raw.transcript_hash}",
            thesis=f"Legacy Succession {profile.lead_type.value} assessment for human review",
            created_at=captured_at,
            signal_ids=tuple(s.id for s in assessment.signals),
            observation_ids=tuple(o.id for o in observations),
            scores=assessment.scores,
            scoring_version=assessment.scoring_version,
        )
        repo.put(hypothesis)
        return hypothesis
