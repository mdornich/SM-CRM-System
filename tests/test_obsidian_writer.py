"""Spec §8 vault-integrity tests (build-prompt tests 7-8) + the KTD-7 managed-section
mechanism edge cases."""

from __future__ import annotations

import json
import logging
from datetime import date

from relationship_intel import pipeline
from relationship_intel.config import Settings
from relationship_intel.obsidian.writer import BEGIN, END, VaultWriter

FM = [("type", "person"), ("name", "Test Person")]


def test_notes_render_with_frontmatter_and_wikilinks(settings, samples_dir):
    pipeline.run_ingest(settings, samples_dir)
    root = settings.obsidian_vault_path / "relationship-intelligence"
    bob = (root / "people" / "bob-smith.md").read_text()
    assert bob.startswith("---\n")
    assert "review_status: unreviewed" in bob
    assert "llm_provider: mock" in bob
    assert "[[smith-hvac|Smith HVAC]]" in bob
    assert BEGIN in bob and END in bob
    transcript_paths = list((root / "transcripts").glob("2026-06-30-bob-smith-*.md"))
    assert len(transcript_paths) == 1
    transcript = transcript_paths[0].read_text()
    assert "[[bob-smith|Bob Smith]]" in transcript
    assert "transcript_hash:" in transcript


def test_rewrite_unchanged_is_byte_identical(tmp_path):
    writer = VaultWriter(tmp_path)
    path = writer.write_note("people", "test", FM, "# Test\ncontent")
    first = path.read_bytes()
    writer.write_note("people", "test", FM, "# Test\ncontent")
    assert path.read_bytes() == first


def test_manual_edit_outside_markers_survives_with_backup(tmp_path):
    writer = VaultWriter(tmp_path)
    path = writer.write_note("people", "test", FM, "# Test\nv1")
    path.write_text(path.read_text() + "\nMY MANUAL NOTES\n")
    writer.write_note("people", "test", FM, "# Test\nv2")
    text = path.read_text()
    assert "MY MANUAL NOTES" in text
    assert "v2" in text and "v1" not in text
    backups = list((writer.root / ".ri-backups").rglob("*.md"))
    assert len(backups) == 1


def test_manual_edit_inside_markers_replaced_but_backed_up(tmp_path):
    writer = VaultWriter(tmp_path)
    path = writer.write_note("people", "test", FM, "# Test\nv1")
    path.write_text(path.read_text().replace("v1", "v1 HAND-TWEAKED"))
    writer.write_note("people", "test", FM, "# Test\nv2")
    text = path.read_text()
    assert "HAND-TWEAKED" not in text and "v2" in text
    backups = list((writer.root / ".ri-backups").rglob("*.md"))
    assert len(backups) == 1
    assert "HAND-TWEAKED" in backups[0].read_text()


def test_unbalanced_markers_skip_rewrite_with_backup(tmp_path, caplog):
    writer = VaultWriter(tmp_path)
    path = writer.write_note("people", "test", FM, "# Test\nv1")
    mangled = path.read_text().replace(END, "")
    path.write_text(mangled)
    with caplog.at_level(logging.WARNING):
        writer.write_note("people", "test", FM, "# Test\nv2")
    assert path.read_text() == mangled  # never rewritten
    assert any("Unbalanced" in r.message for r in caplog.records)
    assert list((writer.root / ".ri-backups").rglob("*.md"))


def test_store_raw_transcripts_false_omits_body_keeps_evidence(tmp_path, samples_dir):
    settings = Settings(
        obsidian_vault_path=tmp_path / "vault",
        db_path=tmp_path / "ri.db",
        mock_crm_path=tmp_path / "mock_crm",
        store_raw_transcripts=False,
    )
    pipeline.run_ingest(settings, samples_dir)
    root = settings.obsidian_vault_path / "relationship-intelligence"
    transcript = next((root / "transcripts").glob("2026-06-30-bob-smith-*.md")).read_text()
    assert "Twenty-two years running this company" not in transcript
    assert "storage disabled" in transcript
    # Evidence snippets are always kept — they are the audit trail (spec §7).
    bob = (root / "people" / "bob-smith.md").read_text()
    assert "next chapter" in bob


def test_literal_marker_text_in_content_cannot_freeze_note(tmp_path):
    """A transcript quoting the ri: markers must not corrupt marker parsing."""
    writer = VaultWriter(tmp_path)
    hostile = f"# Test\nquoting {BEGIN} and {END} literally\nv1"
    path = writer.write_note("transcripts", "hostile", FM, hostile)
    text = path.read_text()
    assert text.count(BEGIN) == 1 and text.count(END) == 1
    # The note must remain updatable on a subsequent changed write.
    writer.write_note("transcripts", "hostile", FM, hostile.replace("v1", "v2"))
    updated = path.read_text()
    assert "v2" in updated and "v1" not in updated


def test_same_name_people_get_distinct_notes(tmp_path, settings):
    """Two real people sharing a name must never collide on one note path."""
    from relationship_intel import pipeline
    from relationship_intel.extraction.schemas import Company, Person
    from relationship_intel.obsidian.writer import VaultWriter as VW
    from relationship_intel.store.db import connect
    from relationship_intel.store.repository import Repository

    repo = Repository(connect(tmp_path / "t.db"))
    acme, _ = repo.resolve_company(Company(name="Acme"))
    globex, _ = repo.resolve_company(Company(name="Globex"))
    repo.resolve_person(Person(name="Jane Doe"), acme)
    repo.resolve_person(Person(name="Jane Doe"), globex)

    writer = VW(tmp_path / "vault")
    pipeline._write_entity_notes(repo, writer, "mock")
    notes = sorted(p.name for p in (writer.root / "people").glob("jane-doe*.md"))
    assert len(notes) == 2


def test_person_owner_reflects_latest_opportunity_not_oldest(tmp_path):
    """A handoff — new opportunity with a new owner — must flow through to
    the person note's owner FM. (Verified finding from /code-review round 2.)"""
    from relationship_intel.extraction.schemas import Company, Person
    from relationship_intel.store.db import connect
    from relationship_intel.store.repository import Repository

    repo = Repository(connect(tmp_path / "handoff.db"))
    company_id, _ = repo.resolve_company(Company(name="Smith HVAC"))
    person_id, _ = repo.resolve_person(Person(name="Bob Smith"), company_id)
    # First (oldest) opportunity owned by mitch.
    repo.upsert_opportunity(
        "Smith HVAC — Bob Smith — Succession",
        person_id,
        company_id,
        {"stage": "closed_lost", "lead_type": "cold", "succession_signal_score": 10},
        "mitch@nine80.ai",
    )
    # Second (latest) opportunity — Bob was handed to alice.
    repo.upsert_opportunity(
        "Smith HVAC — Bob Smith — Round 2",
        person_id,
        company_id,
        {"stage": "discovery", "lead_type": "warm", "succession_signal_score": 60},
        "alice@nine80.ai",
    )
    (person,) = [p for p in repo.people_records() if p.id == person_id]
    assert person.owner == "alice@nine80.ai"

    (company,) = [c for c in repo.company_records() if c.id == company_id]
    assert company.owner == "alice@nine80.ai"


def test_yaml_value_escapes_newlines_and_backslashes():
    from relationship_intel.util.markdown import yaml_value

    assert yaml_value("a\nb") == '"a\\nb"'
    assert yaml_value("back\\slash") == '"back\\\\slash"'
    assert "\n" not in yaml_value("multi\nline\nvalue")


def test_jsonl_indexes_are_valid(settings, samples_dir):
    pipeline.run_ingest(settings, samples_dir)
    index_dir = settings.obsidian_vault_path / "relationship-intelligence" / "indexes"
    for name in ("people", "companies", "opportunities", "transcript-index"):
        lines = (index_dir / f"{name}.jsonl").read_text().strip().splitlines()
        assert lines
        for line in lines:
            json.loads(line)


def test_cairns_mode_routes_writer_artifacts(tmp_path):
    writer = VaultWriter(tmp_path, mode="cairns")

    note = writer.write_note("people", "test-person", FM, "# Test\ncontent")
    index = writer.write_jsonl_index("people", ['{"name":"Test Person"}'])
    report = writer.write_report("CRM-2026-07-04.json", "{}\n")
    plan_json = writer.write_json_artifact("weekly-plans", "2026-W27-james.json", "{}\n")
    writer.ensure_readme()

    assert note == tmp_path / "card-catalog/L2/relationships/people/test-person.md"
    assert index == tmp_path / "manifests/relationship-intelligence/indexes/people.jsonl"
    assert report == tmp_path / "manifests/relationship-intelligence/reports/CRM-2026-07-04.json"
    assert plan_json == tmp_path / "card-catalog/L2/relationships/weekly-plans/2026-W27-james.json"
    assert (tmp_path / "card-catalog/L2/relationships/README.md").exists()


def test_cairns_mode_pipeline_writes_reviewable_l2_and_raw_artifacts(tmp_path, samples_dir):
    settings = Settings(
        obsidian_vault_path=tmp_path / "vault",
        obsidian_mode="cairns",
        db_path=tmp_path / "ri.db",
        mock_crm_path=tmp_path / "mock_crm",
    )

    pipeline.run_ingest(settings, samples_dir)
    plan = pipeline.run_weekly_plan(settings, run_date=date(2026, 7, 4))
    root = settings.obsidian_vault_path

    assert list((root / "raw/relationships/transcripts").glob("*.md"))
    assert (root / "card-catalog/L2/relationships/people/bob-smith.md").exists()
    assert list((root / "card-catalog/L2/relationships/weekly-plans").glob("*.md"))
    assert list((root / "manifests/relationship-intelligence/promotion-proposals").glob("*.md"))
    proposal = next(
        (root / "manifests/relationship-intelligence/promotion-proposals").glob("*.md")
    ).read_text()
    assert "Approval status: `proposed`" in proposal
    assert "cairns/L1/succession-pipeline.md" in proposal
    assert (
        root / "manifests/relationship-intelligence/reports" / f"CRM-{plan['generated_at']}.json"
    ).exists()
    assert not (root / "cairns/L1/succession-pipeline.md").exists()
