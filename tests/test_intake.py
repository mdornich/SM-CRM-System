"""Intake layer: frontmatter parsing, filename fallback, hash stability,
malformed-frontmatter resilience (plan U3 scenarios)."""

from __future__ import annotations

from datetime import date

from relationship_intel.intake.local_folder import LocalFolderSource
from relationship_intel.util.hashing import content_hash


def _load_one(tmp_path, filename: str, text: str):
    (tmp_path / filename).write_text(text, encoding="utf-8")
    transcripts = LocalFolderSource(tmp_path).iter_transcripts()
    assert len(transcripts) == 1
    return transcripts[0]


def test_frontmatter_metadata_parsed(tmp_path):
    raw = _load_one(
        tmp_path,
        "meeting.md",
        "---\ntitle: Big Meeting\ndate: 2026-06-30\nowner: James\n"
        "source_id: g-1\nattendees: [A One, B Two]\n---\nBody text.\n",
    )
    assert raw.title == "Big Meeting"
    assert raw.meeting_date == date(2026, 6, 30)
    assert raw.owner == "James"
    assert raw.source_id == "g-1"
    assert raw.attendees == ["A One", "B Two"]
    assert raw.raw_text.strip() == "Body text."


def test_filename_fallback_supplies_date_and_title(tmp_path):
    raw = _load_one(tmp_path, "2026-07-01-coffee-with-sam.md", "Just dialogue.\n")
    assert raw.meeting_date == date(2026, 7, 1)
    assert raw.title == "coffee with sam"


def test_hash_stable_across_newline_and_trailing_whitespace_variants(tmp_path):
    assert content_hash("a\nb\n") == content_hash("a  \r\nb\r\n")
    assert content_hash("a\nb") != content_hash("a\nc")


def test_malformed_frontmatter_degrades_to_filename_metadata(tmp_path):
    raw = _load_one(
        tmp_path,
        "2026-07-02-broken-meta.md",
        "---\ntitle: [unclosed\n  bad: : yaml\n---\nStill readable body.\n",
    )
    assert raw.title == "broken meta"
    assert raw.meeting_date == date(2026, 7, 2)
    assert "Still readable body." in raw.raw_text


def test_non_transcript_files_ignored(tmp_path):
    (tmp_path / "notes.pdf").write_text("binaryish")
    (tmp_path / "real.md").write_text("Hello.")
    assert len(LocalFolderSource(tmp_path).iter_transcripts()) == 1
