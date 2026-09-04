"""Offline shared boundary fixtures; no confidence conversion policy is implied."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from relationship_intel.cold_intake import load_qualified_lead
from relationship_intel.store.db import connect
from relationship_intel.store.repository import Repository

FIXTURES = Path(__file__).parent / "fixtures" / "phase13a" / "contracts"


def test_fixture_byte_hashes():
    expected = json.loads((FIXTURES / "SHA256SUMS.json").read_text())
    assert set(expected) == {
        "succession-enrichment-v0-input.json",
        "succession-enrichment-v0-output.json",
        "qualified-lead-v0.json",
    }
    for name, digest in expected.items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == digest, name


def test_c4_loads_and_links_to_c2_c3():
    lead = load_qualified_lead(FIXTURES / "qualified-lead-v0.json")
    intent = json.loads((FIXTURES / "succession-enrichment-v0-input.json").read_text())
    output = json.loads((FIXTURES / "succession-enrichment-v0-output.json").read_text())
    evidence = output["evidence"][0]
    assert lead.twenty_person_id in intent["intent"]["person_ids"]
    assert lead.twenty_person_id == evidence["person_id"]
    assert evidence["source_ref"] in lead.proof_pointers
    # Independently authored assessment confidence, never a conversion of fetch confidence.
    assert evidence["confidence"] == "high"
    assert lead.confidence == 0.92
    assert lead.pack_version_id is None


def test_intake_lead_accepts_c4_on_scratch_db_and_replays(tmp_path):
    db = tmp_path / "contract.db"
    env = dict(
        os.environ,
        RI_DB_PATH=str(db),
        OBSIDIAN_VAULT_PATH=str(tmp_path / "vault"),
        TRANSCRIPTS_INBOX_DIR=str(tmp_path / "inbox"),
        RI_MOCK_CRM_PATH=str(tmp_path / "mock-crm"),
        LLM_PROVIDER="mock",
        CRM_PROVIDER="mock",
        CRM_REVIEW_REQUIRED="true",
        TWENTY_API_KEY="",
    )
    command = [
        sys.executable,
        "-m",
        "relationship_intel.cli",
        "intake-lead",
        str(FIXTURES / "qualified-lead-v0.json"),
        "--json",
    ]
    results = []
    for _ in range(2):
        result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        results.append(json.loads(result.stdout))
    assert results[0]["person_created"] is True
    assert results[1]["person_created"] is False
    assert results[0]["person_id"] == results[1]["person_id"]
    assert results[1]["review_item"] == "unchanged"
    repo = Repository(connect(db))
    try:
        lead = load_qualified_lead(FIXTURES / "qualified-lead-v0.json")
        item = repo.review_item("person", results[0]["person_id"])
        assert item is not None and item.status == "pending"
        assert item.payload["existing_crm_ref"]["crm_id"] == lead.twenty_person_id
        assert item.payload["proof_pointers"] == lead.proof_pointers
        assert item.payload["confidence"] == lead.confidence
        for key in ("email", "title", "draft_ref", "pack_version_id"):
            assert item.payload[key] is None
        assert repo.conn.execute("SELECT count(*) FROM people_external_ids").fetchone()[0] == 3
        assert repo.conn.execute("SELECT count(*) FROM crm_review_items").fetchone()[0] == 1
    finally:
        repo.conn.close()
