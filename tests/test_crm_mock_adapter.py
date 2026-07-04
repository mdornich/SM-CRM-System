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


def test_pipeline_items_round_trip(settings, samples_dir):
    pipeline.run_ingest(settings, samples_dir)
    pipeline.run_sync(settings, "mock")
    items = pipeline.make_adapter(settings, "mock").get_pipeline_items()
    assert len(items) == 1
    assert items[0].person_name == "Bob Smith"
    assert items[0].lead_type == "warm"
    assert items[0].crm_ref is not None
