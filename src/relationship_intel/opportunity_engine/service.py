"""Explicit shadow assessment; never called by legacy ingest/sync automatically."""

from __future__ import annotations

from datetime import datetime

from relationship_intel.opportunity_engine.models import Observation, OpportunityHypothesis
from relationship_intel.opportunity_engine.packs import ProductPack
from relationship_intel.opportunity_engine.repository import OpportunityRepository


def create_hypothesis(
    repo: OpportunityRepository,
    pack: ProductPack,
    observation_ids: tuple[str, ...],
    *,
    hypothesis_id: str,
    episode_key: str,
    thesis: str,
    created_at: datetime,
    account_id: int | None = None,
    person_id: int | None = None,
) -> OpportunityHypothesis:
    """Caller assigns stable command ID and resolved subject; replays must match."""
    observations = tuple(repo.get(Observation, oid) for oid in observation_ids)
    assessment = pack.assess(observations)
    if not assessment.eligible or not assessment.signals:
        raise ValueError(f"hypothesis gate: {assessment.reason}")
    if any(s.observation_id not in observation_ids for s in assessment.signals):
        raise ValueError("pack cited an observation outside its input")
    hypothesis = OpportunityHypothesis(
        id=hypothesis_id,
        account_id=account_id,
        person_id=person_id,
        pack_version_id=pack.version.id,
        episode_key=episode_key,
        thesis=thesis,
        created_at=created_at,
        signal_ids=tuple(s.id for s in assessment.signals),
        observation_ids=observation_ids,
        scores=assessment.scores,
        scoring_version=assessment.scoring_version,
    )
    with repo.transaction():
        repo.put(pack.product)
        repo.put(pack.version)
        for definition in pack.definitions:
            repo.put(definition)
        for signal in assessment.signals:
            repo.put(signal)
        repo.put(hypothesis)
    return hypothesis
