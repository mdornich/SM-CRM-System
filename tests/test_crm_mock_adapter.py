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
