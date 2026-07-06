"""Weekly-plan prioritization (test 9), Monday week math, and draft marking."""

from __future__ import annotations

import json
import subprocess
import sys
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


def test_plan_items_have_stable_ids_for_feedback_loop(settings, samples_dir):
    """gh #16: every plan item must carry an `id` field derived from a
    stable (person, week) hash so the operator can record feedback against
    a hash they copy out of the plan Markdown/JSON."""
    pipeline.run_ingest(settings, samples_dir)
    plan = pipeline.run_weekly_plan(settings, run_date=date(2026, 7, 4))
    all_items = [item for items in plan["groups"].values() for item in items]
    assert all_items, "plan should have at least one item"
    for item in all_items:
        assert item.get("id"), f"item missing id: {item['person_name']}"
    # Regenerating for the same week gives the SAME ids — feedback keeps
    # working across re-runs.
    plan_again = pipeline.run_weekly_plan(settings, run_date=date(2026, 7, 4))
    ids_first = {
        (g, i["person_name"], i["id"]) for g, items in plan["groups"].items() for i in items
    }
    ids_second = {
        (g, i["person_name"], i["id"]) for g, items in plan_again["groups"].items() for i in items
    }
    assert ids_first == ids_second


def test_plan_feedback_record_and_summary(settings, samples_dir):
    """gh #16: record captures the action, summary rolls up by group so
    tuning decisions ('cold_retouch is acted 0/N, drop its weight') have
    a data source."""
    pipeline.run_ingest(settings, samples_dir)
    plan = pipeline.run_weekly_plan(settings, run_date=date(2026, 7, 4))
    warm_items = plan["groups"]["warm"]
    assert warm_items, "sample data should have at least one warm item to feedback on"
    target = warm_items[0]

    repo = pipeline.open_repo(settings)
    repo.record_plan_feedback(
        plan["week_start"],
        target["id"],
        "acted",
        notes="called Tuesday AM, got voicemail",
        person_name=target["person_name"],
        group_name="warm",
    )
    repo.record_plan_feedback(
        plan["week_start"],
        target["id"],
        "deferred",
        person_name=target["person_name"],
        group_name="warm",
    )

    rows = repo.plan_feedback_for_week(plan["week_start"])
    assert len(rows) == 2  # both events kept — the revision history is the signal
    actions = [r["action"] for r in rows]
    assert actions == ["acted", "deferred"]

    summary = repo.plan_feedback_summary()
    assert summary["weeks_covered"] == 1
    assert summary["by_group"]["warm"] == {"acted": 1, "deferred": 1}


def test_plan_feedback_rejects_unknown_action(settings):
    """gh #16: only the enum of {acted, deferred, rejected, ignored} is
    accepted — guards against silent typos in a future UI or CLI."""
    import pytest as _pytest

    repo = pipeline.open_repo(settings)
    with _pytest.raises(ValueError, match="plan-feedback action"):
        repo.record_plan_feedback("2026-07-06", "abc123", "maybe")


def test_plan_feedback_cli_record_and_summary(tmp_path, samples_dir):
    """gh #16: CLI surface for record + summary. Uses run-demo to bootstrap
    an ingest + plan, then records feedback and asserts the summary
    reflects it."""
    from relationship_intel.config import Settings

    # Isolate all state under tmp_path.
    settings = Settings(
        llm_provider="mock",
        obsidian_vault_path=tmp_path / "vault",
        db_path=tmp_path / "ri.db",
        mock_crm_path=tmp_path / "mock_crm",
        crm_review_required=False,
    )
    pipeline.run_ingest(settings, samples_dir)
    plan = pipeline.run_weekly_plan(settings, run_date=date(2026, 7, 4))
    (target,) = plan["groups"]["top_plays"][:1] or plan["groups"]["warm"][:1]

    env = {
        "PATH": subprocess.os.environ["PATH"],
        "HOME": subprocess.os.environ["HOME"],
        "OBSIDIAN_VAULT_PATH": str(settings.obsidian_vault_path),
        "RI_DB_PATH": str(settings.db_path),
        "RI_MOCK_CRM_PATH": str(settings.mock_crm_path),
        "CRM_REVIEW_REQUIRED": "false",
    }

    record = subprocess.run(
        [
            sys.executable,
            "-m",
            "relationship_intel.cli",
            "plan-feedback",
            "record",
            "--week-start",
            plan["week_start"],
            "--item-id",
            target["id"],
            "--action",
            "acted",
            "--notes",
            "cli test",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert record.returncode == 0, record.stderr
    assert "Recorded: acted" in record.stdout

    summary = subprocess.run(
        [sys.executable, "-m", "relationship_intel.cli", "plan-feedback", "summary", "--json"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert summary.returncode == 0, summary.stderr
    payload = json.loads(summary.stdout)
    assert payload["weeks_covered"] == 1
    assert payload["totals"]["acted"] == 1
