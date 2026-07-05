from __future__ import annotations

from pathlib import Path

from relationship_intel.evaluation import run_evaluation


def _write_eval_case(folder: Path, *, lead_type: str = "warm") -> None:
    folder.mkdir(exist_ok=True)
    (folder / "2026-07-03-granola-redacted-owner.md").write_text(
        f"""---
title: Redacted Owner Intro
date: 2026-07-03
owner: James
source_system: granola-redacted
source_id: eval-001
attendees: [James Whitfield, Alice Jones]
expected:
  profiles:
    - person_name: Alice Jones
      lead_type: {lead_type}
      timing_window: 3_6_months
      min_score: 50
      next_action_contains: personal check-in
      required_evidence:
        - next chapter
        - valuation
---
Alice Jones: I am the owner of Redacted Services and I have been thinking about the next chapter.
Alice Jones: I want to understand valuation over the next three to six months.
Alice Jones: I need that before I decide what to do.
James Whitfield: I can send over the valuation checklist and then we can talk.
""",
        encoding="utf-8",
    )


def test_evaluation_passes_matching_expectations(tmp_path, settings):
    _write_eval_case(tmp_path)

    report = run_evaluation(settings, tmp_path)

    assert report["cases"] == 1
    assert report["passed"] == 1
    assert report["failed"] == 0
    assert all(finding["status"] == "pass" for finding in report["results"][0]["findings"])


def test_evaluation_fails_mismatched_expectations(tmp_path, settings):
    _write_eval_case(tmp_path, lead_type="not_fit")

    report = run_evaluation(settings, tmp_path)

    assert report["cases"] == 1
    assert report["passed"] == 0
    assert report["failed"] == 1
    assert any(
        finding["field"] == "Alice Jones.lead_type" and finding["status"] == "fail"
        for finding in report["results"][0]["findings"]
    )
