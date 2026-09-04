"""Versioned product-neutral gold cases; measures pack decisions, not LLM quality."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from relationship_intel.evaluation import Finding
from relationship_intel.opportunity_engine.models import Evidence, Key, Observation, Score
from relationship_intel.opportunity_engine.packs import PackRegistry


class Expected(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classification: Key
    eligible: bool
    signal_keys: tuple[Key, ...]
    timing_min: Score | None = None
    timing_max: Score | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.timing_min is not None and self.timing_max is not None:
            if self.timing_min > self.timing_max:
                raise ValueError("invalid score range")
        if len(set(self.signal_keys)) != len(self.signal_keys):
            raise ValueError("duplicate expected signal keys")
        return self


class GoldCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    id: Key
    pack_version_id: Key
    evidence: tuple[Evidence, ...] = Field(min_length=1)
    observations: tuple[Observation, ...] = Field(min_length=1)
    expected: Expected
    labeler: Key
    split: Literal["development", "holdout"]

    @model_validator(mode="after")
    def traceable(self):
        evidence = {e.id: e for e in self.evidence}
        if len(evidence) != len(self.evidence):
            raise ValueError("duplicate evidence ID")
        if len({o.id for o in self.observations}) != len(self.observations):
            raise ValueError("duplicate observation ID")
        for observation in self.observations:
            if observation.evidence_id not in evidence:
                raise ValueError("observation lacks source evidence")
            if observation.predicate == "statement":
                if (
                    not isinstance(observation.value, str)
                    or observation.value not in evidence[observation.evidence_id].excerpt
                ):
                    raise ValueError("statement is not grounded in source excerpt")
        return self


def run_gold_evaluation(source: Path, registry: PackRegistry) -> dict:
    paths = sorted(source.glob("*.json")) if source.is_dir() else [source]
    if not paths:
        raise ValueError("gold set must contain at least one JSON case")
    cases = [GoldCase.model_validate_json(path.read_text()) for path in paths]
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("duplicate gold case ID")
    results = []
    tp = fp = fn = 0
    for case in cases:
        pack = registry.get(case.pack_version_id)
        assessment = pack.assess(case.observations)
        definition_keys = {d.id: d.key for d in pack.definitions}
        actual = {definition_keys[s.definition_id] for s in assessment.signals}
        expected = set(case.expected.signal_keys)
        tp += len(actual & expected)
        fp += len(actual - expected)
        fn += len(expected - actual)
        comparisons = {
            "classification": assessment.classification == case.expected.classification,
            "eligible": assessment.eligible == case.expected.eligible,
            "signal_keys": actual == expected,
            "citation_integrity": all(
                s.observation_id in {o.id for o in case.observations} for s in assessment.signals
            ),
        }
        score = assessment.scores.timing_signal
        if case.expected.timing_min is not None:
            comparisons["timing_min"] = score is not None and score >= case.expected.timing_min
        if case.expected.timing_max is not None:
            comparisons["timing_max"] = score is not None and score <= case.expected.timing_max
        findings = [
            Finding(field, "pass" if passed else "fail", "gold expectation comparison")
            for field, passed in comparisons.items()
        ]
        results.append(
            {
                "id": case.id,
                "pack_version_id": case.pack_version_id,
                "split": case.split,
                "passed": all(comparisons.values()),
                "actual": {
                    "classification": assessment.classification,
                    "eligible": assessment.eligible,
                    "signal_keys": sorted(actual),
                    "scores": assessment.scores.model_dump(),
                },
                "findings": [f.__dict__ for f in findings],
            }
        )
    passed = sum(r["passed"] for r in results)
    return {
        "schema_version": 1,
        "cases": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
        "signal_precision": tp / (tp + fp) if tp + fp else None,
        "signal_recall": tp / (tp + fn) if tp + fn else None,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
    }


def main() -> int:
    import argparse

    from relationship_intel.opportunity_engine.succession import SuccessionPack
    from relationship_intel.opportunity_engine.workflow_audit import WorkflowAuditPack

    parser = argparse.ArgumentParser(description="Evaluate generic Product Pack gold fixtures")
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()
    registry = PackRegistry()
    registry.register(SuccessionPack())
    registry.register(WorkflowAuditPack())
    try:
        report = run_gold_evaluation(args.source, registry)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(2, f"Invalid gold set: {exc}\n")
    print(json.dumps(report, indent=2))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
