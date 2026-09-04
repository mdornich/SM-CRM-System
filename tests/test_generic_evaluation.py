from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from relationship_intel.opportunity_engine.evaluation import GoldCase, run_gold_evaluation
from relationship_intel.opportunity_engine.packs import PackRegistry
from relationship_intel.opportunity_engine.succession import SuccessionPack
from relationship_intel.opportunity_engine.workflow_audit import WorkflowAuditPack

FIXTURES = Path(__file__).parent.parent / "examples" / "opportunity-engine"


def registry():
    result = PackRegistry()
    result.register(SuccessionPack())
    result.register(WorkflowAuditPack())
    return result


def test_gold_fixtures_cover_two_products_and_negative_cases():
    report = run_gold_evaluation(FIXTURES, registry())
    assert report["cases"] >= 5
    assert report["failed"] == 0
    assert report["signal_precision"] == 1
    assert report["signal_recall"] == 1
    assert len({r["pack_version_id"] for r in report["results"]}) == 2


def test_gold_flags_false_positive_and_missing_signal(tmp_path):
    case = json.loads((FIXTURES / "workflow-qualified.json").read_text())
    case["expected"]["signal_keys"] = ["nonexistent"]
    case["expected"]["eligible"] = False
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(case))
    report = run_gold_evaluation(path, registry())
    assert report["failed"] == 1
    assert report["false_positive"] == 1
    assert report["false_negative"] == 1


def test_empty_malformed_unknown_pack_and_untraceable_cases_fail(tmp_path):
    with pytest.raises(ValueError, match="at least one"):
        run_gold_evaluation(tmp_path, registry())
    data = json.loads((FIXTURES / "workflow-qualified.json").read_text())
    data["observations"][0]["evidence_id"] = "missing"
    with pytest.raises(ValidationError, match="source evidence"):
        GoldCase.model_validate(data)
    data["observations"][0]["evidence_id"] = data["evidence"][0]["id"]
    data["pack_version_id"] = "missing"
    path = tmp_path / "unknown.json"
    path.write_text(json.dumps(data))
    with pytest.raises(KeyError):
        run_gold_evaluation(path, registry())
    data["expected"] = {}
    with pytest.raises(ValidationError):
        GoldCase.model_validate(data)
