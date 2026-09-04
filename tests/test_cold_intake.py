from __future__ import annotations

import json
import sqlite3

import pytest
from pydantic import ValidationError

from relationship_intel import pipeline
from relationship_intel.cold_intake import (
    QualifiedLead,
    intake_qualified_lead,
    load_qualified_lead,
)
from relationship_intel.crm.base import AdapterStatus, CRMRef
from relationship_intel.crm.sync import sync_to_crm
from relationship_intel.extraction.schemas import Company, Person
from relationship_intel.opportunity_engine.schema import SCHEMA_V2
from relationship_intel.review import _handle_item, _render_payload_fields
from relationship_intel.store.db import SCHEMA, connect
from relationship_intel.store.repository import Repository


def _lead_data(**updates) -> dict:
    data = {
        "twenty_person_id": "twenty-1",
        "prospect_id": "prospect-1",
        "name": "Ada Lovelace",
        "firm": "Analytical Engines LLC",
        "linkedin_url": "https://linkedin.com/in/ada",
        "wedge": "EOS Practitioner",
        "source": "cold-eos-list",
        "lifecycle": "Cold",
        "proof_pointers": ["pack://eos/ada#qualification"],
        "confidence": 0.92,
        "pack_version_id": "pack-v4",
    }
    data.update(updates)
    return data


def _lead(**updates) -> QualifiedLead:
    return QualifiedLead.model_validate(_lead_data(**updates))


def _repo(tmp_path) -> Repository:
    return Repository(connect(tmp_path / "cold.db"))


def _dump(repo: Repository) -> dict[str, list[tuple]]:
    tables = ("companies", "people", "people_external_ids", "crm_sync_state", "crm_review_items")
    return {
        table: [tuple(row) for row in repo.conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
        for table in tables
    }


def test_intake_creates_crosswalk_pending_item_and_is_idempotent(tmp_path):
    repo = _repo(tmp_path)
    result = intake_qualified_lead(repo, _lead())
    first = _dump(repo)
    repeated = intake_qualified_lead(repo, _lead())

    assert repeated["person_id"] == result["person_id"]
    assert _dump(repo) == first
    assert len(first["companies"]) == 1
    assert len(first["people"]) == 1
    assert len(first["people_external_ids"]) == 3
    assert len(first["crm_sync_state"]) == 1
    assert len(first["crm_review_items"]) == 1
    item = repo.review_item("person", result["person_id"])
    assert item is not None and item.status == "pending"
    assert item.payload["pack_version_id"] == "pack-v4"
    assert item.payload["proof_pointers"] == ["pack://eos/ada#qualification"]

    reviewer_payload = dict(item.payload)
    reviewer_payload["source"] = "reviewer-corrected-source"
    repo.set_review_item("person", result["person_id"], "pending", reviewer_payload)
    repo.conn.execute(
        "UPDATE crm_review_items SET updated_at = '2000-01-01 00:00:00' WHERE local_id = ?",
        (result["person_id"],),
    )
    repo.conn.commit()
    reviewed = _dump(repo)
    intake_qualified_lead(repo, _lead())
    assert _dump(repo) == reviewed


def test_intake_migration_preserves_populated_legacy_database_dump(tmp_path):
    path = tmp_path / "legacy.db"
    external_id_ddl = """CREATE TABLE IF NOT EXISTS people_external_ids (
    person_id INTEGER NOT NULL REFERENCES people(id),
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    UNIQUE(provider, external_id)
);

CREATE INDEX IF NOT EXISTS ix_people_external_ids_person
ON people_external_ids(person_id);

"""
    legacy = sqlite3.connect(path)
    legacy.executescript(SCHEMA.replace(external_id_ddl, ""))
    legacy.executescript(SCHEMA_V2)
    legacy.execute("INSERT INTO companies (id, name, normalized_name) VALUES (1, 'Old', 'old')")
    legacy.execute(
        "INSERT INTO people (id, name, normalized_name, company_id) "
        "VALUES (1, 'Old Person', 'old person', 1)"
    )
    legacy.execute(
        "INSERT INTO opportunities (id, name, person_id, company_id, stage, lead_type) "
        "VALUES (1, 'Old Opportunity', 1, 1, 'new', 'warm')"
    )
    legacy.execute(
        "INSERT INTO crm_sync_state "
        "(id, provider, object_type, local_id, crm_id, last_pushed_hash) "
        "VALUES (1, 'mock', 'person', 1, 'mock-1', 'old-hash')"
    )
    legacy.execute(
        "INSERT INTO crm_review_items "
        "(id, object_type, local_id, label, status, payload_json) "
        "VALUES (1, 'person', 1, 'Old Person', 'approved', '{}')"
    )
    legacy.commit()
    before = list(legacy.iterdump())
    legacy.close()

    repo = Repository(connect(path))
    intake_qualified_lead(repo, _lead())
    after = list(repo.conn.iterdump())

    added_row_prefixes = (
        'INSERT INTO "companies" VALUES(2,',
        'INSERT INTO "people" VALUES(2,',
        'INSERT INTO "crm_sync_state" VALUES(2,',
        'INSERT INTO "crm_review_items" VALUES(2,',
    )
    after_without_additions = [
        statement
        for statement in after
        if "people_external_ids" not in statement and not statement.startswith(added_row_prefixes)
    ]
    assert after_without_additions == before
    assert not repo.conn.execute("PRAGMA foreign_key_check").fetchall()


def test_external_id_beats_name_and_email_fallbacks(tmp_path):
    repo = _repo(tmp_path)
    first = intake_qualified_lead(repo, _lead())
    second = intake_qualified_lead(
        repo,
        _lead(
            twenty_person_id="twenty-2",
            prospect_id="prospect-2",
            name="Ada Byron",
            linkedin_url="https://LINKEDIN.com/in/ada/?tracking=ignored",
        ),
    )
    assert second["person_id"] == first["person_id"]
    assert repo.conn.execute("SELECT count(*) FROM people").fetchone()[0] == 1
    assert repo.conn.execute("SELECT count(*) FROM people_external_ids").fetchone()[0] == 5


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"proof_pointers": []}, "proof_pointers"),
        ({"wedge": "Investor"}, "unknown wedge"),
    ],
)
def test_invalid_record_is_rejected_before_any_write(tmp_path, updates, message):
    # Go through the real CLI entry point. Calling `_lead(**updates)` inline
    # would raise while building the argument, so intake would never be
    # reached and the "no writes" assertions below would be vacuous.
    repo = _repo(tmp_path)
    record = tmp_path / "lead.json"
    record.write_text(json.dumps(_lead_data(**updates)))

    with pytest.raises(ValidationError, match=message):
        intake_qualified_lead(repo, load_qualified_lead(record))

    assert repo.conn.execute("SELECT count(*) FROM people").fetchone()[0] == 0
    assert repo.conn.execute("SELECT count(*) FROM companies").fetchone()[0] == 0
    assert repo.conn.execute("SELECT count(*) FROM crm_review_items").fetchone()[0] == 0


class _UpdateOnlyAdapter:
    provider = "twenty"

    def __init__(self):
        self.updates = []
        self.creates = []

    def ensure_schema(self):
        return {"created": [], "existing": []}

    def update_contact_gtm_fields(self, ref, payload):
        self.updates.append((ref, payload))
        return ref

    def find_or_create_contact(self, payload):
        self.creates.append(payload)
        raise AssertionError("cold intake must update the pre-seeded Twenty person")

    def find_or_create_company(self, payload):
        raise AssertionError("company is not approved in this test")

    def create_or_update_opportunity(self, payload):
        raise AssertionError

    def attach_note(self, ref, note):
        raise AssertionError

    def create_task(self, ref, task):
        raise AssertionError

    def tag_record(self, ref, tags):
        raise AssertionError

    def get_pipeline_items(self, owner=None):
        return []

    def health_check(self):
        return AdapterStatus(True)


def test_reviewed_cold_lead_updates_existing_twenty_person_never_creates(settings):
    repo = pipeline.open_repo(settings)
    result = intake_qualified_lead(repo, _lead())
    item = repo.review_item("person", result["person_id"])
    assert item is not None
    rendered = _render_payload_fields(item.payload)
    assert 'name="value__wedge"' not in rendered
    assert 'name="value__proof_pointers"' not in rendered

    # Exercise the existing review-UI save path before approval. Structured
    # system payload values must survive rather than flattening to strings.
    _handle_item(
        settings,
        {
            "object_type": ["person"],
            "local_id": [str(result["person_id"])],
            "status": ["approved"],
            "field": ["name", "source", "lifecycle_stage", "wedge_primary"],
            "type__name": ["str"],
            "value__name": [item.payload["name"]],
            "type__source": ["str"],
            "value__source": [item.payload["source"]],
            "type__lifecycle_stage": ["str"],
            "value__lifecycle_stage": [item.payload["lifecycle_stage"]],
            "type__wedge_primary": ["str"],
            "value__wedge_primary": [item.payload["wedge_primary"]],
        },
    )
    reviewed = pipeline.open_repo(settings).review_item("person", result["person_id"])
    assert reviewed is not None
    assert reviewed.payload["wedge"] == ["EOS_PRACTITIONER"]
    assert reviewed.payload["proof_pointers"] == ["pack://eos/ada#qualification"]
    adapter = _UpdateOnlyAdapter()

    stats = sync_to_crm(pipeline.open_repo(settings), adapter, "James", approved_only=True)

    assert stats["people"] == 1
    assert stats["gtm_write_failed"] == 0
    assert adapter.creates == []
    assert len(adapter.updates) == 1
    assert adapter.updates[0][0] == CRMRef("twenty", "person", "twenty-1")
    assert adapter.updates[0][1]["wedge"] == ["EOS_PRACTITIONER"]


def test_intake_fills_gtm_keys_on_a_person_the_pipeline_already_queued(tmp_path):
    """A qualified cold lead usually resolves to somebody already in the queue.

    That pre-existing row's payload has no GTM keys and no `existing_crm_ref`.
    Skipping the write dropped all of them, so approval fell through to
    `find_or_create_contact` and created a duplicate Twenty person — the exact
    outcome this intake path exists to prevent.
    """
    repo = _repo(tmp_path)
    company_id, _ = repo.resolve_company(Company(name="Analytical Engines LLC"))
    person_id, _ = repo.resolve_person(
        Person(name="Ada Lovelace", email="ada@analyticalengines.example"), company_id
    )
    repo.upsert_review_item(
        "person",
        person_id,
        "Ada Lovelace",
        {"name": "Ada Lovelace", "email": "ada@analyticalengines.example", "title": None},
    )

    result = intake_qualified_lead(repo, _lead(email="ada@analyticalengines.example"))

    assert result["person_id"] == person_id
    assert result["review_item"] == "updated"
    item = repo.review_item("person", person_id)
    assert item is not None
    assert item.payload["wedge"] == ["EOS_PRACTITIONER"]
    assert item.payload["lifecycle_stage"] == "COLD"
    assert item.payload["proof_pointers"] == ["pack://eos/ada#qualification"]
    assert item.payload["existing_crm_ref"]["crm_id"] == "twenty-1"
    # Pre-existing reviewer-visible values are never overwritten.
    assert item.payload["email"] == "ada@analyticalengines.example"

    # ...and the merge stays idempotent on a repeat intake.
    before = _dump(repo)
    assert (
        intake_qualified_lead(repo, _lead(email="ada@analyticalengines.example"))["review_item"]
        == "unchanged"
    )
    assert _dump(repo) == before


def test_intake_replaces_a_crm_ref_flattened_by_an_older_form_round_trip(tmp_path):
    repo = _repo(tmp_path)
    company_id, _ = repo.resolve_company(Company(name="Analytical Engines LLC"))
    person_id, _ = repo.resolve_person(Person(name="Ada Lovelace"), company_id)
    repo.upsert_review_item(
        "person",
        person_id,
        "Ada Lovelace",
        {"name": "Ada Lovelace", "existing_crm_ref": "{'crm_id': 'stale'}"},
    )

    intake_qualified_lead(repo, _lead())

    item = repo.review_item("person", person_id)
    assert item is not None
    assert item.payload["existing_crm_ref"] == {
        "provider": "twenty",
        "object_type": "person",
        "crm_id": "twenty-1",
    }


def test_review_form_shows_wedge_and_proof_without_offering_them_back(tmp_path):
    repo = _repo(tmp_path)
    result = intake_qualified_lead(repo, _lead())
    item = repo.review_item("person", result["person_id"])
    assert item is not None

    rendered = _render_payload_fields(item.payload)

    # Visible to the human gate...
    assert "EOS_PRACTITIONER" in rendered
    assert "pack://eos/ada#qualification" in rendered
    # ...but never as form inputs that would flatten on save.
    assert 'name="value__wedge"' not in rendered
    assert 'name="value__proof_pointers"' not in rendered
    assert 'value="wedge"' not in rendered
    assert 'value="proof_pointers"' not in rendered
