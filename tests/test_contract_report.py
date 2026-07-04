"""Contract-1 union report: passes the vendored fleet validator; both consumer
shapes present; confidence is a non-empty string (the divergence that would have
failed the runtime validator — see docs/architecture.md §3.7)."""

from __future__ import annotations

import json
from datetime import date

from relationship_intel import pipeline
from relationship_intel.planning.contract import validate_agent_report_v1


def _report(settings, samples_dir) -> dict:
    pipeline.run_ingest(settings, samples_dir)
    plan = pipeline.run_weekly_plan(settings, run_date=date(2026, 7, 4))
    path = (
        settings.obsidian_vault_path
        / "relationship-intelligence"
        / "reports"
        / f"CRM-{plan['generated_at']}.json"
    )
    return json.loads(path.read_text())


def test_emitted_report_passes_fleet_validator(settings, samples_dir):
    report = _report(settings, samples_dir)
    assert validate_agent_report_v1(report) is None


def test_union_shape_serves_both_consumers(settings, samples_dir):
    report = _report(settings, samples_dir)
    # fleet runtime validator shape
    assert report["agent"] == "crm-source"
    assert isinstance(report["confidence"], str) and report["confidence"]
    assert isinstance(report["findings"], list) and isinstance(report["decisions"], list)
    # morning-brief template shape
    assert report["department"] == "CRM"
    for key in ("top_decisions", "flagged_anomalies", "yesterday_followups", "tomorrow_focus"):
        assert key in report
    # mock provenance is surfaced, and confidence honestly reflects it
    assert report["metrics"]["llm_provider"] == "mock"
    assert report["confidence"] == "low"


def test_validator_rejects_broken_reports(settings, samples_dir):
    report = _report(settings, samples_dir)
    broken = {k: v for k, v in report.items() if k != "findings"}
    assert validate_agent_report_v1(broken) == "missing field: findings"
    assert validate_agent_report_v1({**report, "confidence": 0.9}) == "confidence must be string"
    assert validate_agent_report_v1({**report, "headline": ""}) == (
        "headline must be non-empty string"
    )
