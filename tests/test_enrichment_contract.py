"""Shared offline contracts, real OE persistence and scratch CLI intake."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from relationship_intel import cli
from relationship_intel.cold_intake import QualifiedLead
from relationship_intel.opportunity_engine.enrichment_contract import map_enrichment_evidence
from relationship_intel.opportunity_engine.models import Evidence, Observation
from relationship_intel.opportunity_engine.repository import OpportunityRepository
from relationship_intel.store.db import connect
from relationship_intel.store.repository import Repository

FIXTURES = Path(__file__).parent / "fixtures/phase13a/contracts"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_shared_fixture_hashes():
    hashes = load("SHA256SUMS.json")
    assert set(hashes) == {p.name for p in FIXTURES.glob("*.json")} - {"SHA256SUMS.json"}
    for name, digest in hashes.items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == digest


def test_c4_cli_and_c3b_persist_and_replay(settings, monkeypatch):
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    path = FIXTURES / "c4-qualified-lead.json"
    lead = QualifiedLead.model_validate_json(path.read_text())
    assert cli.main(["intake-lead", str(path), "--json"]) == 0
    conn = connect(settings.db_path)
    repo = Repository(conn)
    person_id = repo.people_for_external_ids({"twenty": lead.twenty_person_id})[0]
    evidence, observation = map_enrichment_evidence(
        load("c3-output.json")["evidence"][0],
        twenty_person_id=lead.twenty_person_id,
        person_id=person_id,
    )
    assert {"evidence": evidence, "observation": observation} == load("c3b-proposal.json")
    oe = OpportunityRepository(conn)
    for _ in range(2):
        with oe.transaction():
            oe.put(Evidence.model_validate(evidence))
            oe.put(Observation.model_validate(observation))
    before = list(conn.iterdump())
    assert cli.main(["intake-lead", str(path), "--json"]) == 0
    assert list(conn.iterdump()) == before
    assert conn.execute("SELECT count(*) FROM oe_evidence").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM oe_observations").fetchone()[0] == 1
    assert repo.review_item("person", person_id).status == "pending"
    assert oe.get(Evidence, evidence["id"]).occurred_at is None
    conn.close()


@pytest.mark.parametrize(
    "label,number", [("high", 0.9), ("medium", 0.6), ("low", 0.3), ("unknown", None)]
)
def test_confidence_policy_preserves_unknown_without_changing_model(label, number):
    row = load("c3-output.json")["evidence"][0]
    row["confidence"] = label
    _, observation = map_enrichment_evidence(row, twenty_person_id=row["person_id"], person_id=1)
    assert observation["confidence"] == number
    assert observation["value"]["confidence_label"] == label
    if number is None:
        with pytest.raises(ValidationError):
            Observation.model_validate(observation)
    else:
        assert Observation.model_validate(observation).confidence == number


@pytest.mark.parametrize(
    "source,predicate",
    [
        ("eos_profile", "eos_directory_listed"),
        ("firm_website", "firm_website_present"),
        ("linkedin", "linkedin_public_present"),
    ],
)
def test_presence_vocabulary(source, predicate):
    row = load("c3-output.json")["evidence"][0]
    row["source_type"] = source
    _, observation = map_enrichment_evidence(row, twenty_person_id=row["person_id"], person_id=1)
    assert observation["predicate"] == predicate


def test_rejects_mismatched_subject_or_evidence_key():
    row = load("c3-output.json")["evidence"][0]
    with pytest.raises(ValueError, match="crosswalk"):
        map_enrichment_evidence(row, twenty_person_id="different", person_id=1)
    row["idempotency_key"] = "wrong"
    with pytest.raises(ValueError, match="idempotency"):
        map_enrichment_evidence(row, twenty_person_id=row["person_id"], person_id=1)


def test_presence_metadata_does_not_claim_cold_qualification():
    from relationship_intel.opportunity_engine.succession_cold import SuccessionColdPack

    row = load("c3-output.json")["evidence"][0]
    _, proposal = map_enrichment_evidence(row, twenty_person_id=row["person_id"], person_id=1)
    assessment = SuccessionColdPack().assess((Observation.model_validate(proposal),))
    assert assessment.classification == "unknown"
    assert assessment.eligible is False
    assert "unreadable proof" in assessment.reason


def test_empty_excerpt_is_a_consumer_mismatch():
    row = load("c3-output.json")["evidence"][0]
    row["excerpt"] = ""
    proposal, _ = map_enrichment_evidence(row, twenty_person_id=row["person_id"], person_id=1)
    with pytest.raises(ValidationError):
        Evidence.model_validate(proposal)
