"""Pure EOS cold qualification; explicit reviewer proof, never keyword inference.

human_label values are {"criterion": <signal key>, "proved": true|false|null}.
True asserts the ENTIRE criterion, including its source/proof law. False denies it;
null/partial/malformed facts cannot prove it, and a label or presence fact the pack
cannot read is never discarded — it holds the verdict at UNKNOWN, so a mistyped
exclusion key can never leave a subject scored FIT. Reviewers own source verification.
Directory/website/LinkedIn presence alone cannot establish a compound FIT criterion.
Statements remain reusable evidence; a reviewer must label their implications.
"""

from __future__ import annotations

from relationship_intel.opportunity_engine.models import (
    Observation,
    Product,
    ProductPackVersion,
    ScoreDimensions,
    SignalDefinition,
    SignalObservation,
)
from relationship_intel.opportunity_engine.packs import Assessment, check_subject

FIT_CRITERIA = {
    "eos_directory_owner_led": (
        "Owner-led Professional or Certified EOS Implementer, or senior Implementer "
        "controlling recommendations"
    ),
    "active_portfolio": (
        "Solo practice or small firm with an active recurring portfolio of leadership teams"
    ),
    "public_practice_footprint": (
        "Public implementation-practice footprint with repeated Process Component references"
    ),
    "identity_matched": (
        "Identity matched on name + firm + geography before a LinkedIn URL is attached"
    ),
}
EXCLUSIONS = {
    "excl_no_portfolio": "one-off advisor with no active portfolio",
    "excl_generic_sop_binder": "wants a generic SOP binder",
    "excl_no_team_access": "will not sponsor access to the leadership team",
    "excl_own_rollout": "expects Succession to own rollout",
    "excl_official_affiliation": "seeks official EOS affiliation",
}


class SuccessionColdPack:
    product = Product(id="succession", name="Succession", description="Succession advisory")
    version = ProductPackVersion(
        id="succession:cold-v0",
        product_id=product.id,
        version="cold-v0",
        fixture_only=False,
        policy={
            "rubric_path": "agents/profiles/growth-lead/rubrics/qualification.md",
            "rubric_commit": "77d543889c712a666d3ce274c382de13a033f30a",
            "rubric_sha256": "8e884b7f14755a18791124d691ad7bab53e16cab21ff0c9991dcbd52d636cef7",
            "department_pack_version": "v0",
        },
    )
    definitions = tuple(
        SignalDefinition(
            id=f"succession:cold-v0:{key}",
            pack_version_id="succession:cold-v0",
            key=key,
            description=description,
        )
        for key, description in (FIT_CRITERIA | EXCLUSIONS).items()
    )

    def assess(self, observations: tuple[Observation, ...]) -> Assessment:
        check_subject(observations)
        labels: dict[str, set[bool]] = {d.key: set() for d in self.definitions}
        presence: dict[str, set[bool]] = {
            key: set()
            for key in ("eos_directory_listed", "firm_website_present", "linkedin_public_present")
        }
        signals = []
        proof_sources = set()
        unreadable = []
        for observation in observations:
            value = observation.value
            if observation.predicate in presence:
                # A presence fact the pack cannot read is not the same as absence:
                # `0` beside `true` would drop out of the set and the directory /
                # footprint contradiction check would never see the disagreement.
                if type(value) is bool:
                    presence[observation.predicate].add(value)
                else:
                    unreadable.append(observation.id)
                continue
            if observation.predicate != "human_label":
                continue
            key = value.get("criterion") if isinstance(value, dict) else None
            proved = value.get("proved") if isinstance(value, dict) else None
            if not isinstance(key, str) or key not in labels or type(proved) is not bool:
                # Never discard a label silently. A mistyped exclusion key, a
                # string "true", or a missing `proved` used to vanish here — and
                # a reviewer asserting an exclusion would still see FIT/100.
                # Proof the pack cannot read holds the verdict at UNKNOWN.
                unreadable.append(key if isinstance(key, str) and key in labels else observation.id)
                continue
            labels[key].add(proved)
            if proved:
                proof_sources.add(observation.evidence_id)
                signals.append(
                    SignalObservation(
                        id=f"{self.version.id}:{key}:{observation.id}",
                        definition_id=f"{self.version.id}:{key}",
                        observation_id=observation.id,
                        strength=100,
                        rationale=f"Reviewer asserts full rubric proof: {key}",
                    )
                )

        exclusions = [key for key in EXCLUSIONS if True in labels[key]]
        missing = [key for key in FIT_CRITERIA if labels[key] != {True}]
        if presence["eos_directory_listed"] != {True}:
            missing.append("eos_directory_owner_led: directory proof missing or contradictory")
        if not any(
            presence[key] == {True} for key in ("firm_website_present", "linkedin_public_present")
        ) or any(len(values) > 1 for values in presence.values()):
            missing.append("public_practice_footprint: presence missing or contradictory")
        if len(proof_sources) < 2:
            missing.append("rubric UNKNOWN: one source only or missing evidence")
        if unreadable:
            missing.append("unreadable proof: " + ", ".join(sorted(set(unreadable))))
        fit: int | None
        if exclusions:
            classification, fit = "unfit", 0
            reason = "Exclusion proved: " + ", ".join(exclusions)
        elif missing:
            classification, fit = "unknown", None
            reason = "Missing, partial, denied or contradictory proof: " + ", ".join(missing)
        else:
            classification, fit = "fit", 100
            reason = "All four EOS criteria proved; no exclusion proved"
        return Assessment(
            tuple(signals),
            ScoreDimensions(fit=fit),
            classification,
            classification == "fit",
            reason,
            "succession-cold-v0",
        )
