"""Spec §8 identity tests (build-prompt tests 4-6): duplicate transcripts and the
§3.4 entity-resolution rules."""

from __future__ import annotations

from relationship_intel import pipeline
from relationship_intel.extraction.schemas import Company, Person
from relationship_intel.store.db import connect
from relationship_intel.store.repository import Repository


def _repo(tmp_path) -> Repository:
    return Repository(connect(tmp_path / "test.db"))


def test_duplicate_transcript_is_skipped_entirely(settings, samples_dir):
    first = pipeline.run_ingest(settings, samples_dir)
    counts_before = pipeline.open_repo(settings).counts()
    second = pipeline.run_ingest(settings, samples_dir)
    counts_after = pipeline.open_repo(settings).counts()

    assert first["ingested"] == 3
    assert second["ingested"] == 0
    assert second["skipped_duplicates"] == 3
    assert counts_before == counts_after


def test_email_match_wins_over_name_spelling(tmp_path):
    repo = _repo(tmp_path)
    id1, created1 = repo.resolve_person(Person(name="Bob Smith", email="bob@x.com"), None)
    id2, created2 = repo.resolve_person(Person(name="Robert Smith", email="BOB@X.COM"), None)
    assert created1 and not created2
    assert id1 == id2


def test_name_plus_company_match(tmp_path):
    repo = _repo(tmp_path)
    company_id, _ = repo.resolve_company(Company(name="Acme Inc."))
    id1, _ = repo.resolve_person(Person(name="Jane Doe"), company_id)
    id2, created = repo.resolve_person(Person(name="jane doe"), company_id)
    assert id1 == id2 and not created


def test_name_only_match_flags_medium_confidence(tmp_path):
    repo = _repo(tmp_path)
    id1, _ = repo.resolve_person(Person(name="Jane Doe"), None)
    company_id, _ = repo.resolve_company(Company(name="Acme"))
    id2, created = repo.resolve_person(Person(name="Jane Doe"), company_id)
    assert id1 == id2 and not created
    row = repo.conn.execute(
        "SELECT identity_confidence FROM people WHERE id = ?", (id1,)
    ).fetchone()
    assert row["identity_confidence"] == "medium"


def test_company_conflict_creates_new_person_with_review_flag(tmp_path):
    repo = _repo(tmp_path)
    acme, _ = repo.resolve_company(Company(name="Acme"))
    globex, _ = repo.resolve_company(Company(name="Globex"))
    id1, _ = repo.resolve_person(Person(name="Jane Doe"), acme)
    id2, created = repo.resolve_person(Person(name="Jane Doe"), globex)
    assert created and id1 != id2
    # Identical name at a conflicting company is exactly what review must catch
    # (rule 4 includes edit-distance 0).
    row = repo.conn.execute("SELECT needs_review FROM people WHERE id = ?", (id2,)).fetchone()
    assert row["needs_review"] == 1
    # And the two people must never share a vault note slug.
    slugs = repo.person_slugs()
    assert slugs[id1] != slugs[id2]
    assert slugs[id1] == "jane-doe"  # first keeps the stable base slug


def test_learning_company_later_upgrades_opportunity_instead_of_duplicating(tmp_path):
    repo = _repo(tmp_path)
    person_id, _ = repo.resolve_person(Person(name="Bob Smith"), None)
    profile = {"stage": "discovery", "lead_type": "warm", "succession_signal_score": 60}
    first = repo.upsert_opportunity("Bob Smith — Succession", person_id, None, profile, "James")
    company_id, _ = repo.resolve_company(Company(name="Smith HVAC"))
    second = repo.upsert_opportunity(
        "Smith HVAC — Bob Smith — Succession", person_id, company_id, profile, "James"
    )
    assert first == second
    rows = repo.conn.execute("SELECT company_id FROM opportunities").fetchall()
    assert len(rows) == 1
    assert rows[0]["company_id"] == company_id


def test_near_duplicate_name_flagged_needs_review(tmp_path):
    repo = _repo(tmp_path)
    repo.resolve_person(Person(name="Bob Smith"), None)
    new_id, created = repo.resolve_person(Person(name="Rob Smith"), None)
    assert created
    row = repo.conn.execute("SELECT needs_review FROM people WHERE id = ?", (new_id,)).fetchone()
    assert row["needs_review"] == 1


def test_company_suffix_normalization_merges(tmp_path):
    repo = _repo(tmp_path)
    id1, _ = repo.resolve_company(Company(name="Acme Inc."))
    id2, created = repo.resolve_company(Company(name="Acme"))
    assert id1 == id2 and not created


def test_company_domain_match_overrides_name(tmp_path):
    repo = _repo(tmp_path)
    id1, _ = repo.resolve_company(Company(name="Acme", website="https://acme.com"))
    id2, created = repo.resolve_company(
        Company(name="Acme Holdings International", website="https://www.acme.com/about")
    )
    assert id1 == id2 and not created
