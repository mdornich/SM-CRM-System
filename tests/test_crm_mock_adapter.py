"""Mock CRM adapter: idempotency (test 10) and the summary boundary (KTD-8c)."""

from __future__ import annotations

import json

from conftest import tree_snapshot

from relationship_intel import pipeline
from relationship_intel.crm.mock_adapter import MockCRMAdapter


def test_find_or_create_returns_same_ref(tmp_path):
    adapter = MockCRMAdapter(tmp_path / "crm")
    ref1 = adapter.find_or_create_contact({"name": "Bob Smith", "email": "bob@x.com"})
    ref2 = adapter.find_or_create_contact({"name": "Bob Smith", "email": "bob@x.com"})
    assert ref1 == ref2


def test_second_sync_of_unchanged_data_performs_zero_writes(settings, samples_dir):
    pipeline.run_ingest(settings, samples_dir)
    first = pipeline.run_sync(settings, "mock")
    snapshot = tree_snapshot(settings.mock_crm_path)
    mtimes = {p: p.stat().st_mtime_ns for p in settings.mock_crm_path.rglob("*.json")}

    second = pipeline.run_sync(settings, "mock")

    assert first["people"] > 0 and first["opportunities"] == 1
    assert second["people"] == 0 and second["companies"] == 0 and second["opportunities"] == 0
    assert tree_snapshot(settings.mock_crm_path) == snapshot
    assert {p: p.stat().st_mtime_ns for p in settings.mock_crm_path.rglob("*.json")} == mtimes


def test_review_required_sync_only_pushes_approved_items(settings, samples_dir):
    from dataclasses import replace

    reviewed = replace(settings, crm_review_required=True)
    pipeline.run_ingest(reviewed, samples_dir)

    assert pipeline.run_sync(reviewed, "mock") == {
        "companies": 0,
        "people": 0,
        "opportunities": 0,
        "notes": 0,
        "tasks": 0,
        "skipped": 8,
        "skipped_by_stage": 0,
    }

    repo = pipeline.open_repo(reviewed)
    bob = next(p for p in repo.people_records() if p.name == "Bob Smith")
    company = next(c for c in repo.company_records() if c.name == "Smith HVAC")
    repo.set_review_item("company", company.id, "approved", {"name": company.name})
    repo.set_review_item(
        "person",
        bob.id,
        "approved",
        {"name": bob.name, "email": bob.email, "title": bob.title},
    )
    repo.set_review_item(
        "person_note",
        bob.id,
        "approved",
        {"title": "Relationship intelligence — Bob Smith", "body": "approved note"},
    )
    repo.set_review_item(
        "person_task",
        bob.id,
        "approved",
        {"title": "Call Bob", "body": "approved task", "due_window": "this_week"},
    )

    stats = pipeline.run_sync(reviewed, "mock")

    assert stats["companies"] == 1
    assert stats["people"] == 1
    assert stats["notes"] == 1
    assert stats["tasks"] == 1
    people = json.loads((reviewed.mock_crm_path / "people.json").read_text())
    assert [p["name"] for p in people.values()] == ["Bob Smith"]


def test_opportunity_custom_field_contract_forces_one_upgrade_sync(settings, samples_dir):
    from relationship_intel.crm.sync import _payload_hash

    pipeline.run_ingest(settings, samples_dir)
    pipeline.run_sync(settings, "mock")
    repo = pipeline.open_repo(settings)
    (opp,) = repo.opportunity_records()
    person_state = repo.get_sync_state("mock", "person", opp.person_id)
    company_state = repo.get_sync_state("mock", "company", opp.company_id)
    old_payload = {
        "name": opp.name,
        "stage": opp.stage,
        "lead_type": opp.lead_type,
        "succession_signal_score": opp.succession_signal_score,
        "urgency": opp.urgency,
        "timing_window": opp.timing_window,
        "owner": opp.owner,
        "next_action": opp.next_action,
        "next_action_due": opp.next_action_due,
        "person_name": opp.person_name,
        "company_name": opp.company_name,
        "person_crm_id": person_state["crm_id"],
        "company_crm_id": company_state["crm_id"],
    }
    opp_state = repo.get_sync_state("mock", "opportunity", opp.id)
    repo.set_sync_state(
        "mock",
        "opportunity",
        opp.id,
        opp_state["crm_id"],
        opp_state["url"],
        _payload_hash(old_payload),
    )

    stats = pipeline.run_sync(settings, "mock")
    assert stats["opportunities"] == 1
    assert pipeline.run_sync(settings, "mock")["opportunities"] == 0


def test_crm_notes_contain_summaries_never_evidence(settings, samples_dir):
    """Twenty gets summaries, not evidence (spec §3.6) — enforced at the note boundary."""
    pipeline.run_ingest(settings, samples_dir)
    pipeline.run_sync(settings, "mock")

    repo = pipeline.open_repo(settings)
    evidence_snippets = [
        snippet
        for row in repo.conn.execute("SELECT profile_json FROM lead_profiles").fetchall()
        for snippet in json.loads(row["profile_json"])["evidence_snippets"]
    ]
    assert evidence_snippets

    notes = json.loads((settings.mock_crm_path / "notes.json").read_text())
    assert notes
    for note in notes.values():
        for snippet in evidence_snippets:
            assert snippet not in note["body"]
        assert "relationship-intelligence/people/" in note["body"]  # vault link back


def test_create_task_updates_in_place_on_same_title_redelivery(tmp_path):
    from relationship_intel.crm.base import CRMRef, TaskPayload

    adapter = MockCRMAdapter(tmp_path / "crm")
    ref = CRMRef("mock", "person", "p-1")
    first = adapter.create_task(
        ref, TaskPayload(title="Call Bob", body="v1", due_window="this_week")
    )
    second = adapter.create_task(
        ref, TaskPayload(title="Call Bob", body="v2", due_window="two_weeks")
    )
    assert first == second
    tasks = json.loads((tmp_path / "crm" / "tasks.json").read_text())
    (task,) = tasks.values()
    assert task["body"] == "v2" and task["due_window"] == "two_weeks"


def test_failed_note_attach_is_retried_on_next_sync(settings, samples_dir):
    """Note/task delivery is tracked independently of person sync state — a
    failure after the person record lands must not be skipped forever."""
    from relationship_intel import pipeline as pl
    from relationship_intel.crm.sync import sync_to_crm

    pl.run_ingest(settings, samples_dir)
    repo = pl.open_repo(settings)

    class FlakyAdapter(MockCRMAdapter):
        fail_notes = True

        def attach_note(self, ref, note):
            if self.fail_notes:
                raise RuntimeError("simulated CRM outage during attach_note")
            return super().attach_note(ref, note)

    adapter = FlakyAdapter(settings.mock_crm_path)
    try:
        sync_to_crm(repo, adapter, "James")
        raise AssertionError("expected simulated failure")
    except RuntimeError:
        pass

    adapter.fail_notes = False
    stats = sync_to_crm(repo, adapter, "James")
    assert stats["notes"] > 0  # retried and delivered, not skipped forever
    notes = json.loads((settings.mock_crm_path / "notes.json").read_text())
    assert notes


def test_pipeline_items_round_trip(settings, samples_dir):
    pipeline.run_ingest(settings, samples_dir)
    pipeline.run_sync(settings, "mock")
    items = pipeline.make_adapter(settings, "mock").get_pipeline_items()
    assert len(items) == 1
    assert items[0].person_name == "Bob Smith"
    assert items[0].lead_type == "warm"
    assert items[0].crm_ref is not None


def test_reviewer_stage_edit_to_no_opp_stage_is_filtered_for_twenty(settings, samples_dir):
    """A reviewer edits an opportunity's stage to 'not_fit' / 'stalled' /
    'closed_lost' in the review UI and approves. The NO_OPP_STAGES filter must
    read the REVIEWED payload stage, not the raw DB stage — otherwise Twenty
    receives a payload with an unmappable stage and crashes the sync mid-loop.
    (Verified finding, /code-review high-effort workflow.)"""
    from dataclasses import replace

    from relationship_intel.crm.mock_adapter import MockCRMAdapter
    from relationship_intel.crm.sync import sync_to_crm

    reviewed = replace(settings, crm_review_required=True)
    pipeline.run_ingest(reviewed, samples_dir)
    repo = pipeline.open_repo(reviewed)
    bob = next(p for p in repo.people_records() if p.name == "Bob Smith")
    company = next(c for c in repo.company_records() if c.name == "Smith HVAC")
    (opp,) = repo.opportunity_records()

    # Reviewer edits the opportunity stage to a Twenty-unmappable stage and
    # approves everything the sync loop touches.
    repo.set_review_item(
        "opportunity",
        opp.id,
        "approved",
        {"name": opp.name, "stage": "closed_lost", "lead_type": opp.lead_type},
    )
    repo.set_review_item("person", bob.id, "approved", {"name": bob.name})
    repo.set_review_item("company", company.id, "approved", {"name": company.name})

    # Simulate the Twenty provider without hitting the network.
    class FakeTwenty(MockCRMAdapter):
        provider = "twenty"

    adapter = FakeTwenty(reviewed.mock_crm_path)
    stats = sync_to_crm(repo, adapter, reviewed.default_owner, approved_only=True)
    assert stats["skipped_by_stage"] == 1
    assert stats["opportunities"] == 0
