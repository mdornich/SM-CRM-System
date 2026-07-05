"""Weekly-plan prioritization (test 9), Monday week math, and draft marking."""

from __future__ import annotations

import json
from datetime import date, timedelta

from relationship_intel import pipeline
from relationship_intel.extraction.schemas import Person
from relationship_intel.planning.message_drafts import DRAFT_MARKER
from relationship_intel.planning.weekly_plan import build_plan, to_markdown
from relationship_intel.store.db import connect
from relationship_intel.store.repository import Repository
from relationship_intel.util.dates import monday_of_week

WEEK_START = date(2026, 6, 29)  # Monday


def _seed_person(repo, name, profile_overrides, days_before_week_start, transcript_title):
    class _Raw:
        source_system = "test"
        source_id = transcript_title
        title = transcript_title
        meeting_date = WEEK_START - timedelta(days=days_before_week_start)
        owner = "James"
        transcript_hash = f"hash-{transcript_title}"
        source_path = None

    transcript_id, _ = repo.register_transcript(_Raw())
    person_id, _ = repo.resolve_person(Person(name=name), None)
    repo.add_interaction(
        person_id, transcript_id, _Raw.meeting_date.isoformat(), [f"{name} said something."]
    )
    profile = {
        "person_name": name,
        "company_name": None,
        "lead_type": "warm",
        "stage": "discovery",
        "succession_signal_score": 60,
        "urgency": "medium",
        "timing_window": "3_6_months",
        "next_best_action": f"Call {name}",
        "next_action_due_window": "this_week",
        "recommended_cadence": "weekly",
        "suggested_message": None,
        "evidence_snippets": [f"{name} said something."],
        **profile_overrides,
    }
    repo.add_lead_profile(person_id, transcript_id, json.dumps(profile), "succession-v0.1", "mock")
    return person_id


def _plan(repo, stall_days=21):
    return build_plan(repo, "James", WEEK_START, stall_days, "mock", date(2026, 7, 4))


def test_monday_week_math():
    assert monday_of_week(date(2026, 7, 4)) == date(2026, 6, 29)  # Saturday -> that Monday
    assert monday_of_week(date(2026, 6, 29)) == date(2026, 6, 29)  # Monday is fixed point


def test_default_and_override_week_start(settings, samples_dir):
    pipeline.run_ingest(settings, samples_dir)
    plan = pipeline.run_weekly_plan(settings, run_date=date(2026, 7, 4))
    assert plan["week_start"] == "2026-06-29"
    plan = pipeline.run_weekly_plan(
        settings, week_start=date(2026, 7, 6), run_date=date(2026, 7, 4)
    )
    assert plan["week_start"] == "2026-07-06"


def test_overdue_outranks_higher_scored_non_overdue(tmp_path):
    repo = Repository(connect(tmp_path / "t.db"))
    # A: overdue (due this_week=7d, last touch 10 days ago), modest score.
    _seed_person(repo, "Alice Overdue", {"succession_signal_score": 55}, 10, "t1")
    # B: fresher and higher-scored, not overdue.
    _seed_person(repo, "Brian Hot", {"succession_signal_score": 90, "urgency": "high"}, 2, "t2")
    plan = _plan(repo)
    assert [i["person_name"] for i in plan["groups"]["top_plays"]][:2] == [
        "Alice Overdue",
        "Brian Hot",
    ]
    assert plan["groups"]["overdue"][0]["person_name"] == "Alice Overdue"


def test_stalled_boundary_exact_threshold(tmp_path):
    repo = Repository(connect(tmp_path / "t.db"))
    # No next action -> can't be overdue; days control stalled classification.
    _seed_person(
        repo,
        "Stan Stalled",
        {"next_best_action": None, "next_action_due_window": None},
        21,
        "t1",
    )
    _seed_person(
        repo,
        "Fred Fresh",
        {"next_best_action": None, "next_action_due_window": None},
        20,
        "t2",
    )
    plan = _plan(repo, stall_days=21)
    assert [i["person_name"] for i in plan["groups"]["stalled"]] == ["Stan Stalled"]
    assert "Fred Fresh" in [i["person_name"] for i in plan["groups"]["warm"]]


def test_drafts_are_marked_and_items_carry_links(tmp_path):
    repo = Repository(connect(tmp_path / "t.db"))
    _seed_person(repo, "Alice Overdue", {}, 2, "t1")
    plan = _plan(repo)
    item = plan["groups"]["warm"][0]
    assert item["suggested_message"].startswith(DRAFT_MARKER)
    assert item["obsidian_link"] == "[[alice-overdue|Alice Overdue]]"
    assert item["evidence_links"]
    markdown = to_markdown(plan)
    assert "## Top Plays This Week" in markdown
    assert "## Needs Review" in markdown
    assert DRAFT_MARKER in markdown


def test_flagged_identity_lands_in_needs_review_group(tmp_path):
    repo = Repository(connect(tmp_path / "t.db"))
    person_id = _seed_person(repo, "Jane Doe", {}, 2, "t1")
    repo.conn.execute("UPDATE people SET needs_review = 1 WHERE id = ?", (person_id,))
    repo.conn.commit()
    plan = _plan(repo)
    flagged = [i["person_name"] for i in plan["groups"]["needs_review"]]
    assert flagged == ["Jane Doe"]
    assert plan["groups"]["needs_review"][0]["needs_review"] is True
    # And the rendered section actually lists her (not just the heading).
    markdown = to_markdown(plan)
    needs_review_section = markdown.split("## Needs Review")[1].split("## Risks")[0]
    assert "Jane Doe" in needs_review_section


def test_not_fit_people_never_enter_the_plan(settings, samples_dir):
    pipeline.run_ingest(settings, samples_dir)
    plan = pipeline.run_weekly_plan(settings, run_date=date(2026, 7, 4))
    everyone = [i["person_name"] for g in plan["groups"].values() for i in g]
    assert "Tom Rivera" not in everyone


def test_weekly_plan_writes_l1_promotion_proposal(settings, samples_dir):
    pipeline.run_ingest(settings, samples_dir)
    pipeline.run_weekly_plan(settings, run_date=date(2026, 7, 4))
    root = settings.obsidian_vault_path / "relationship-intelligence"

    proposals = list((root / "promotion-proposals").glob("*.md"))
    assert proposals
    text = proposals[0].read_text()
    assert "L1 Promotion Proposal" in text
    assert "Approval status: `proposed`" in text
    assert "cairns/L1/succession-pipeline.md" in text
    assert list((root / "promotion-proposals").glob("*.json"))
