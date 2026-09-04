from __future__ import annotations

import pytest
from pydantic import ValidationError

from relationship_intel.cold_intake import QualifiedLead, intake_qualified_lead
from relationship_intel.crm.base import AdapterStatus, CRMRef
from relationship_intel.crm.sync import sync_to_crm
from relationship_intel.store.db import connect
from relationship_intel.store.repository import Repository


def _lead(**updates) -> QualifiedLead:
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
    return QualifiedLead.model_validate(data)


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
    repo = _repo(tmp_path)
    with pytest.raises(ValidationError, match=message):
        intake_qualified_lead(repo, _lead(**updates))
    assert repo.conn.execute("SELECT count(*) FROM people").fetchone()[0] == 0
    assert repo.conn.execute("SELECT count(*) FROM companies").fetchone()[0] == 0


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


def test_approved_cold_lead_updates_existing_twenty_person_never_creates(tmp_path):
    repo = _repo(tmp_path)
    result = intake_qualified_lead(repo, _lead())
    item = repo.review_item("person", result["person_id"])
    assert item is not None
    repo.set_review_item("person", result["person_id"], "approved", item.payload)
    adapter = _UpdateOnlyAdapter()

    stats = sync_to_crm(repo, adapter, "James", approved_only=True)

    assert stats["people"] == 1
    assert adapter.creates == []
    assert len(adapter.updates) == 1
    assert adapter.updates[0][0] == CRMRef("twenty", "person", "twenty-1")
