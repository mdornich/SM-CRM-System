"""Succession compatibility pack. Legacy extraction stays authoritative for parity."""

from __future__ import annotations

from relationship_intel.extraction import succession_lens as lens
from relationship_intel.extraction.schemas import PROSPECT_LEAD_TYPES, SuccessionLeadProfile
from relationship_intel.opportunity_engine.models import (
    Observation,
    Product,
    ProductPackVersion,
    ScoreDimensions,
    SignalDefinition,
    SignalObservation,
)
from relationship_intel.opportunity_engine.packs import Assessment, check_subject


class SuccessionPack:
    product = Product(id="succession", name="Succession", description="Succession advisory")
    version = ProductPackVersion(
        id="succession:foundation-v1",
        product_id=product.id,
        version="foundation-v1",
        policy={
            "lens_version": lens.LENS_VERSION,
            "prompt": lens.EXTRACTION_PROMPT,
            "rules": lens.RULES,
            "weights": lens.SCORE_WEIGHTS,
            "warm_threshold": lens.WARM_THRESHOLD,
            "cues": {
                "exit": lens.EXIT_CUES,
                "timing": list(lens.TIMING_CUES),
                "pain": lens.PAIN_CUES,
                "buying": lens.BUYING_CUES,
                "followup": lens.FOLLOWUP_CUES,
                "owner": lens.OWNER_CUES,
                "referral": lens.REFERRAL_CUES,
            },
            "mode": "shadow; no CRM export",
        },
    )
    definitions = tuple(
        SignalDefinition(
            id=f"succession:foundation-v1:{key}",
            pack_version_id="succession:foundation-v1",
            key=key,
            description=f"Succession {key} interpretation",
        )
        for key in (*lens.SCORE_WEIGHTS, "legacy_assessment")
    )

    def assess(self, observations: tuple[Observation, ...]) -> Assessment:
        check_subject(observations)
        cues = self.version.policy["cues"]
        signals = []
        found = set()
        referral = False
        for observation in observations:
            if observation.predicate != "statement" or not isinstance(observation.value, str):
                continue
            text = observation.value.lower()
            if any(cue in text for cue in cues["referral"]):
                referral = True
                continue
            for key, weight in lens.SCORE_WEIGHTS.items():
                if any(cue in text for cue in cues[key]):
                    found.add(key)
                    signals.append(
                        SignalObservation(
                            id=f"{self.version.id}:{key}:{observation.id}",
                            definition_id=f"{self.version.id}:{key}",
                            observation_id=observation.id,
                            strength=weight,
                            rationale=f"Attributed statement matches {key} cue",
                        )
                    )
        score = min(100, sum(lens.SCORE_WEIGHTS[key] for key in found))
        warm = score >= lens.WARM_THRESHOLD and bool(found & {"exit", "timing", "pain", "followup"})
        classification = "referral_source" if referral else "warm" if warm else "unknown"
        return Assessment(
            tuple(signals),
            ScoreDimensions(timing_signal=score),
            classification,
            warm and not referral,
            "Cue-based shadow assessment; no inferred fit or contact quality",
            lens.LENS_VERSION,
        )

    def from_profile(
        self,
        profile: SuccessionLeadProfile,
        observations: tuple[Observation, ...],
    ) -> Assessment:
        """Map the legacy result without laundering its score into neutral facts.

        Each cited snippet must already exist as an attributed statement. Identity
        resolution belongs to the caller; this adapter never resolves by display name.
        """
        check_subject(observations)
        by_quote = {
            o.value: o
            for o in observations
            if o.predicate == "statement" and isinstance(o.value, str)
        }
        missing = set(profile.evidence_snippets) - by_quote.keys()
        if missing:
            raise ValueError("legacy evidence must be registered as observations first")
        signals = tuple(
            SignalObservation(
                id=f"{self.version.id}:legacy:{by_quote[quote].id}",
                definition_id=f"{self.version.id}:legacy_assessment",
                observation_id=by_quote[quote].id,
                strength=profile.succession_signal_score,
                rationale=f"Legacy {lens.LENS_VERSION} classification: {profile.lead_type.value}",
            )
            for quote in dict.fromkeys(profile.evidence_snippets)
        )
        return Assessment(
            signals,
            ScoreDimensions(timing_signal=profile.succession_signal_score),
            profile.lead_type.value,
            profile.lead_type in PROSPECT_LEAD_TYPES and bool(signals),
            "Compatibility projection; legacy score is not a calibrated generic composite",
            lens.LENS_VERSION,
        )
