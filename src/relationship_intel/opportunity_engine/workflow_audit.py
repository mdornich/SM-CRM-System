"""Unrelated architecture fixture, not an approved product or discovery policy."""

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


class WorkflowAuditPack:
    product = Product(
        id="workflow-audit",
        name="980labs Workflow Automation Audit",
        description="Architecture fixture for professional-services workflow research",
    )
    version = ProductPackVersion(
        id="workflow-audit:fixture-v1",
        product_id=product.id,
        version="fixture-v1",
        fixture_only=True,
        policy={
            "employees_min": 20,
            "employees_max": 250,
            "industry": "professional_services",
            "manual_hours_min": 5,
            "approval": "human",
            "offer": "provisional workflow audit",
        },
    )
    definitions = (
        SignalDefinition(
            id="workflow-audit:fixture-v1:manual_work",
            pack_version_id="workflow-audit:fixture-v1",
            key="manual_work",
            description="Reported recurring manual work of at least five hours per week",
        ),
    )

    def assess(self, observations: tuple[Observation, ...]) -> Assessment:
        check_subject(observations)
        facts: dict[str, list[Observation]] = {}
        for observation in observations:
            facts.setdefault(observation.predicate, []).append(observation)
        required = ("employee_count", "industry", "manual_hours_week")
        if any(len({str(o.value) for o in facts.get(key, [])}) > 1 for key in required):
            return Assessment(
                (),
                ScoreDimensions(contradiction_penalty=100),
                "contradiction",
                False,
                "Resolve conflicting observations",
                "fixture-v1",
            )
        if any(not facts.get(key) for key in required):
            return Assessment(
                (),
                ScoreDimensions(),
                "insufficient_evidence",
                False,
                "Missing size, industry, or quantified manual work",
                "fixture-v1",
            )
        size, industry, hours = (facts[key][0].value for key in required)
        if type(size) is not int or type(hours) not in (int, float) or hours < 0:
            return Assessment(
                (),
                ScoreDimensions(),
                "insufficient_evidence",
                False,
                "Invalid numeric observation",
                "fixture-v1",
            )
        fit = 20 <= size <= 250 and industry == "professional_services"
        if not fit:
            return Assessment(
                (),
                ScoreDimensions(fit=0),
                "rejected_fit",
                False,
                "Outside provisional ICP",
                "fixture-v1",
            )
        if hours < 5:
            return Assessment(
                (),
                ScoreDimensions(fit=100, timing_signal=0),
                "no_signal",
                False,
                "No qualifying recurring manual work",
                "fixture-v1",
            )
        observation = facts["manual_hours_week"][0]
        signal = SignalObservation(
            id=f"{self.version.id}:manual_work:{observation.id}",
            definition_id=self.definitions[0].id,
            observation_id=observation.id,
            strength=min(100, hours * 5),
            rationale="Reported weekly manual work; fixture rubric",
        )
        return Assessment(
            (signal,),
            ScoreDimensions(fit=100, timing_signal=signal.strength),
            "qualified",
            True,
            "Provisional audit candidate",
            "fixture-v1",
        )
