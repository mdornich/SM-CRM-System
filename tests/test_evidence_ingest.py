from __future__ import annotations

import copy
import json
import sqlite3
from hashlib import sha256
from pathlib import Path

import pytest

from relationship_intel.cli import main
from relationship_intel.extraction.schemas import Company, Person
from relationship_intel.opportunity_engine.ingest import (
    ingest_drop_file,
    map_drop_file,
    resolve_twenty_subject,
)
from relationship_intel.opportunity_engine.models import Observation
from relationship_intel.opportunity_engine.repository import OpportunityRepository
from relationship_intel.opportunity_engine.succession_cold import SuccessionColdPack
from relationship_intel.store.db import SCHEMA, connect
from relationship_intel.store.repository import Repository

FIXTURE = Path("tests/fixtures/phase13a/contracts/succession-enrichment-v0-output.json")


@pytest.fixture
def record():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def store(tmp_path):
    conn = connect(tmp_path / "test.db")
    legacy = Repository(conn)
    company, _ = legacy.resolve_company(Company(name="Synthetic Practice"))
    person, _ = legacy.resolve_person(
        Person(name="Synthetic Practitioner"),
        company,
        external_ids={"twenty": "person-fetchable"},
    )
    yield OpportunityRepository(conn), legacy, (person, company)
    conn.close()


def ingest(repo, legacy, tmp_path, record):
    path = tmp_path / "drop.json"
    path.write_text(json.dumps(record))
    return ingest_drop_file(repo, path, lambda key: resolve_twenty_subject(legacy, key))


def legacy_snapshot(conn):
    tables = [line.split()[5] for line in SCHEMA.splitlines() if line.startswith("CREATE TABLE")]
    return {
        table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table}")] for table in tables
    }


@pytest.mark.parametrize(
    "label,score", [("high", 0.9), ("medium", 0.6), ("low", 0.3), ("unknown", 0.0)]
)
def test_pure_mapping_confidence_and_locator(record, monkeypatch, label, score):
    def forbidden(*args, **kwargs):
        pytest.fail("pure mapper attempted sqlite I/O")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    record["evidence"][0]["confidence"] = label
    original = copy.deepcopy(record)
    evidence, observations = map_drop_file(record, {"person-fetchable": (7, None)})
    assert len(evidence) == len(observations) == 1
    assert evidence[0].locator == "page"
    assert evidence[0].occurred_at is None
    assert observations[0].person_id == 7
    assert observations[0].account_id is None
    assert observations[0].confidence == score
    assert observations[0].value == {
        "present": True,
        "url": record["evidence"][0]["source_ref"],
        "confidence_label": label,
    }
    assert record == original


def test_fixture_replay_changed_content_hash_and_legacy_unchanged(store, tmp_path, record):
    repo, legacy, subject = store
    before = legacy_snapshot(repo.conn)
    first = ingest(repo, legacy, tmp_path, record)
    assert first == dict(
        evidence_created=1,
        evidence_existing=0,
        observations_created=1,
        observations_existing=0,
        blocked_receipts_carried=1,
        **{"skipped:unresolved": 0},
    )
    second = ingest(repo, legacy, tmp_path, record)
    assert second["evidence_created"] == second["observations_created"] == 0
    assert second["evidence_existing"] == second["observations_existing"] == 1
    original = dict(repo.conn.execute("SELECT * FROM oe_evidence").fetchone())
    item = record["evidence"][0]
    item["excerpt"] = "Changed public evidence"
    item["content_hash"] = sha256(item["excerpt"].encode()).hexdigest()
    third = ingest(repo, legacy, tmp_path, record)
    assert third["evidence_created"] == third["observations_created"] == 1
    assert (
        dict(
            repo.conn.execute("SELECT * FROM oe_evidence WHERE id=?", (original["id"],)).fetchone()
        )
        == original
    )
    assert legacy_snapshot(repo.conn) == before
    row = repo.conn.execute("SELECT * FROM oe_observations LIMIT 1").fetchone()
    assert (row["person_id"], row["account_id"]) == subject


def test_unresolved_count_is_per_item_and_null_account(store, tmp_path, record):
    repo, legacy, subject = store
    repo.conn.execute("UPDATE people SET company_id=NULL WHERE id=?", (subject[0],))
    repo.conn.commit()
    record["evidence"] += [dict(record["evidence"][0], person_id="missing") for _ in range(2)]
    counts = ingest(repo, legacy, tmp_path, record)
    assert counts["skipped:unresolved"] == 2
    assert counts["evidence_created"] == 1
    assert repo.conn.execute("SELECT account_id FROM oe_observations").fetchone()[0] is None
    assert resolve_twenty_subject(legacy, "missing") is None


def test_atomic_rollback_on_late_immutable_conflict(store, tmp_path, record):
    repo, legacy, _ = store
    ingest(repo, legacy, tmp_path, record)
    original = copy.deepcopy(record["evidence"][0])
    record["evidence"][0]["source_ref"] = "https://new.example/"
    original["excerpt"] = "Conflicting excerpt under the same source hash"
    record["evidence"].append(original)
    with pytest.raises(ValueError, match="immutable ID conflict"):
        ingest(repo, legacy, tmp_path, record)
    assert repo.conn.execute("SELECT count(*) FROM oe_evidence").fetchone()[0] == 1
    assert repo.conn.execute("SELECT count(*) FROM oe_observations").fetchone()[0] == 1


def test_nonempty_observations_fail_closed_before_resolution(store, tmp_path, record):
    repo, _, _ = store
    record["observations"] = [{"predicate": "firm_description"}]
    path = tmp_path / "drop.json"
    path.write_text(json.dumps(record))

    def forbidden(key):
        pytest.fail("unsupported file must fail before resolution")

    with pytest.raises(ValueError, match="#1281"):
        ingest_drop_file(repo, path, forbidden)
    assert repo.conn.execute("SELECT count(*) FROM oe_evidence").fetchone()[0] == 0


@pytest.mark.parametrize("label", [None, "", "HIGH", 0.9])
def test_invalid_confidence_is_not_unknown(record, label):
    record["evidence"][0]["confidence"] = label
    with pytest.raises(ValueError, match="confidence"):
        map_drop_file(record, {"person-fetchable": (1, None)})


def test_cli_counts_only_replay_and_invalid_input(store, tmp_path, monkeypatch, capsys):
    repo, _, _ = store
    db_path = repo.conn.execute("PRAGMA database_list").fetchone()[2]
    monkeypatch.setenv("RI_DB_PATH", db_path)
    assert main(["ingest-evidence", str(FIXTURE), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["evidence_created"] == 1
    assert main(["ingest-evidence", str(FIXTURE)]) == 0
    output = capsys.readouterr().out
    assert "evidence_existing=1" in output
    assert "person-fetchable" not in output and "https://" not in output
    path = tmp_path / "invalid.json"
    path.write_text("{private text")
    assert main(["ingest-evidence", str(path), "--json"]) == 2
    assert json.loads(capsys.readouterr().out) == {"error": "invalid_drop_file"}


def test_ingest_fit_sources_exposes_pack_contract_blocker(store, tmp_path, record):
    """Real consumer regression: required presence objects cannot currently yield FIT."""
    repo, legacy, subject = store
    fit = json.loads(Path("examples/opportunity-engine/cold/fit.json").read_text())
    original_obs = tuple(Observation.model_validate(item) for item in fit["observations"])
    assert SuccessionColdPack().assess(original_obs).classification == "fit"
    template = record["evidence"][0]
    record["evidence"] = [
        dict(
            template,
            source_type=kind,
            source_ref=source["source_ref"],
            content_hash=source["content_hash"],
            excerpt=source["excerpt"],
            captured_at=source["captured_at"],
        )
        for source, kind in zip(fit["evidence"], ["eos_profile", "firm_website"], strict=True)
    ]
    ingest(repo, legacy, tmp_path, record)
    evidence, observations = map_drop_file(record, {"person-fetchable": subject})
    labels = tuple(
        item.model_copy(
            update={
                "person_id": subject[0],
                "account_id": subject[1],
                "evidence_id": evidence[int(item.evidence_id[-1])].id,
            }
        )
        for item in original_obs
        if item.predicate == "human_label"
    )
    assessment = SuccessionColdPack().assess(observations + labels)
    assert assessment.classification == "unknown"
    assert "unreadable proof" in assessment.reason


@pytest.mark.parametrize(
    "source_type,predicate",
    [
        ("eos_profile", "eos_directory_listed"),
        ("firm_website", "firm_website_present"),
        ("linkedin", "linkedin_public_present"),
    ],
)
def test_producer_source_types(record, source_type, predicate):
    # Synthetic variants using URL_FIELDS in the real v0 producer, not live responses.
    record["evidence"][0]["source_type"] = source_type
    evidence, observations = map_drop_file(record, {"person-fetchable": (1, None)})
    assert evidence[0].source_type == source_type
    assert observations[0].predicate == predicate


def test_excerpt_only_change_preserves_original_and_rejects_conflict(store, tmp_path, record):
    repo, legacy, _ = store
    ingest(repo, legacy, tmp_path, record)
    before = {
        table: [tuple(row) for row in repo.conn.execute(f"SELECT * FROM {table}")]
        for table in ("oe_evidence", "oe_observations")
    }
    record["evidence"][0]["excerpt"] = "Changed excerpt with unchanged producer hash"
    with pytest.raises(ValueError, match="immutable ID conflict"):
        ingest(repo, legacy, tmp_path, record)
    for table, rows in before.items():
        assert [tuple(row) for row in repo.conn.execute(f"SELECT * FROM {table}")] == rows
