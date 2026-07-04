"""Spec §8 vault-integrity tests (build-prompt tests 7-8) + the KTD-7 managed-section
mechanism edge cases."""

from __future__ import annotations

import json
import logging

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
    transcript = (root / "transcripts" / "2026-06-30-bob-smith-succession-intro.md").read_text()
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
    transcript = (root / "transcripts" / "2026-06-30-bob-smith-succession-intro.md").read_text()
    assert "Twenty-two years running this company" not in transcript
    assert "storage disabled" in transcript
    # Evidence snippets are always kept — they are the audit trail (spec §7).
    bob = (root / "people" / "bob-smith.md").read_text()
    assert "next chapter" in bob


def test_jsonl_indexes_are_valid(settings, samples_dir):
    pipeline.run_ingest(settings, samples_dir)
    index_dir = settings.obsidian_vault_path / "relationship-intelligence" / "indexes"
    for name in ("people", "companies", "opportunities", "transcript-index"):
        lines = (index_dir / f"{name}.jsonl").read_text().strip().splitlines()
        assert lines
        for line in lines:
            json.loads(line)
