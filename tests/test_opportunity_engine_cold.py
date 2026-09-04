from __future__ import annotations

import ast
import re
from hashlib import sha256
from pathlib import Path

import pytest

from relationship_intel.opportunity_engine.evaluation import GoldCase, run_gold_evaluation
from relationship_intel.opportunity_engine.packs import PackRegistry
from relationship_intel.opportunity_engine.succession_cold import (
    EXCLUSIONS,
    FIT_CRITERIA,
    SuccessionColdPack,
)

ROOT = Path(__file__).parent.parent
COLD = ROOT / "examples/opportunity-engine/cold"


def case(name="fit"):
    return GoldCase.model_validate_json((COLD / f"{name}.json").read_text())


def test_rubric_digest_and_exact_one_to_one_coverage():
    rubric = (ROOT / "docs/opportunity-engine/source/qualification.md").read_bytes()
    pack = SuccessionColdPack()
    assert sha256(rubric).hexdigest() == pack.version.policy["rubric_sha256"]
    eos = rubric.decode().split("## Wedge 1 — EOS Practitioner\n")[1].split("## Wedge 2")[0]
    fit = eos.split("**FIT** needs all four proved:\n")[1].split("**UNFIT**")[0]
    headings = [
        re.split(r" — proof| \(source:", " ".join(bullet.split()))[0].rstrip(".")
        for bullet in fit.strip().removeprefix("- ").split("\n- ")
    ]
    excluded = eos.split("**UNFIT**, any one proved: ")[1].split(" (source:")[0]
    headings += " ".join(excluded.split()).split("; ")
    assert len(headings) == 9
    assert sorted(d.description for d in pack.definitions) == sorted(headings)
    assert len({d.key for d in pack.definitions}) == 9
    assert not pack.version.fixture_only


def test_six_gold_cases():
    registry = PackRegistry()
    registry.register(SuccessionColdPack())
    report = run_gold_evaluation(COLD, registry)
    assert report["cases"] == 6
    assert report["failed"] == 0


@pytest.mark.parametrize(
    "name,score", [("fit", 100), ("unfit-exclusion", 0), ("missing-evidence", None)]
)
def test_verdict_scores_and_null_dimensions(name, score):
    result = SuccessionColdPack().assess(case(name).observations)
    assert result.scores.fit == score
    assert all(v is None for k, v in result.scores.model_dump().items() if k != "fit")
    assert result.scoring_version == "succession-cold-v0"


@pytest.mark.parametrize("key", FIT_CRITERIA)
@pytest.mark.parametrize("proof", [None, False, "partial", 1, "true"])
def test_partial_proof_never_fits(key, proof):
    observations = tuple(
        o.model_copy(update={"value": {"criterion": key, "proved": proof}}) if o.id == key else o
        for o in case().observations
    )
    result = SuccessionColdPack().assess(observations)
    assert result.classification == "unknown"
    assert not result.eligible
    assert result.scores.fit is None
    assert key in result.reason


@pytest.mark.parametrize("key", EXCLUSIONS)
def test_exclusion_wins_even_with_full_fit_and_denial(key):
    observations = case().observations
    positive = observations[-1].model_copy(
        update={"id": "exclude", "value": {"criterion": key, "proved": True}}
    )
    denial = positive.model_copy(
        update={"id": "denial", "value": {"criterion": key, "proved": False}}
    )
    result = SuccessionColdPack().assess((*observations, positive, denial))
    assert result.classification == "unfit"
    assert not result.eligible
    assert result.scores.fit == 0
    assert key in result.reason


def test_presence_keywords_and_one_source_cannot_prove_fit():
    observations = case().observations
    pack = SuccessionColdPack()
    assert pack.assess(observations[:3]).classification == "unknown"
    assert pack.assess(()).classification == "unknown"
    assert (
        pack.assess(
            tuple(o.model_copy(update={"evidence_id": "one"}) for o in observations)
        ).classification
        == "unknown"
    )
    statements = tuple(
        o.model_copy(update={"predicate": "statement", "value": str(o.value)}) for o in observations
    )
    assert pack.assess(statements).classification == "unknown"


@pytest.mark.parametrize(
    "predicate", ["eos_directory_listed", "firm_website_present", "linkedin_public_present"]
)
def test_presence_conflict_holds(predicate):
    observations = case().observations
    conflict = observations[0].model_copy(
        update={"id": "conflict", "predicate": predicate, "value": False}
    )
    assert SuccessionColdPack().assess((*observations, conflict)).classification == "unknown"


def test_subject_and_duplicate_guards():
    observations = case().observations
    with pytest.raises(ValueError, match="duplicate"):
        SuccessionColdPack().assess((*observations, observations[0]))
    other = observations[0].model_copy(update={"id": "other", "person_id": 2})
    with pytest.raises(ValueError, match="one resolved subject"):
        SuccessionColdPack().assess((*observations, other))


def test_generic_core_has_no_product_imports():
    root = ROOT / "src/relationship_intel/opportunity_engine"
    for name in ("models", "packs", "repository", "schema", "service", "evaluation"):
        tree = ast.parse((root / f"{name}.py").read_text())
        # CLI composition is the existing explicit registration boundary.
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.ImportFrom):
                    assert not any(
                        s in (child.module or "") for s in ("succession", "workflow_audit")
                    )
                if isinstance(child, ast.Import):
                    assert not any(
                        "succession" in a.name or "workflow_audit" in a.name for a in child.names
                    )


def test_adr_checks_cover_all_thirteen():
    text = (ROOT / "docs/opportunity-engine/DECISION_LOG.md").read_text()
    adrs = re.split(r"## ADR-\d{3}[^\n]*\n", text)[1:]
    assert len(adrs) == 13
    assert all(len(re.findall(r"^Transcript check:", adr, re.M)) == 1 for adr in adrs)
