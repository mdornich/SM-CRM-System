from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from hashlib import sha256

import pytest
from pydantic import ValidationError

from relationship_intel.extraction.schemas import Company, Person
from relationship_intel.opportunity_engine.models import (
    Evidence,
    Observation,
    OpportunityHypothesis,
    Product,
    ScoreDimensions,
)
from relationship_intel.opportunity_engine.packs import PackRegistry
from relationship_intel.opportunity_engine.repository import OpportunityRepository
from relationship_intel.opportunity_engine.service import create_hypothesis
from relationship_intel.opportunity_engine.succession import SuccessionPack
from relationship_intel.opportunity_engine.workflow_audit import WorkflowAuditPack
from relationship_intel.store.db import SCHEMA, connect
from relationship_intel.store.repository import Repository

NOW = datetime(2026, 9, 4, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    conn = connect(tmp_path / "test.db")
    legacy = Repository(conn)
    company, _ = legacy.resolve_company(Company(name="Example Services"))
    person, _ = legacy.resolve_person(Person(name="Example Person"), company)
    yield OpportunityRepository(conn), company, person
    conn.close()


def facts(repo, account_id, person_id=None):
    text = "We employ 40 people in professional services and do 12 hours of manual work weekly."
    evidence = Evidence(
        id="source-1",
        source_type="interview",
        source_ref="fixture-1",
        content_hash=sha256(text.encode()).hexdigest(),
        locator="paragraph:1",
        excerpt=text,
        captured_at=NOW,
    )
    repo.put(evidence)
    items = [
        ("employee_count", 40),
        ("industry", "professional_services"),
        ("manual_hours_week", 12),
        ("statement", "I am the owner of this firm, thinking about selling next year."),
    ]
    # Separate source excerpt for the statement; never pretend an extraction is a quote.
    quote = items[-1][1]
    repo.put(
        Evidence(
            id="source-2",
            source_type="interview",
            source_ref="fixture-1",
            content_hash=sha256(quote.encode()).hexdigest(),
            locator="paragraph:2",
            excerpt=quote,
            captured_at=NOW,
        )
    )
    observations = tuple(
        Observation(
            id=f"obs-{i}",
            account_id=account_id,
            person_id=person_id,
            evidence_id="source-2" if key == "statement" else evidence.id,
            predicate=key,
            value=value,
            method="fixture-human-label",
            confidence=1,
        )
        for i, (key, value) in enumerate(items)
    )
    for observation in observations:
        repo.put(observation)
    return observations


def hypothesis(repo, pack, observations, account, person, identifier="h1", episode="2026-Q3"):
    return create_hypothesis(
        repo,
        pack,
        tuple(o.id for o in observations),
        hypothesis_id=identifier,
        episode_key=episode,
        thesis="Evidence supports a reviewable commercial hypothesis",
        created_at=NOW,
        account_id=account,
        person_id=person,
    )


def test_shared_subject_multiple_products_and_episodes_reuses_evidence(store):
    repo, account, person = store
    observations = facts(repo, account, person)
    a = hypothesis(repo, WorkflowAuditPack(), observations, account, person)
    b = hypothesis(repo, SuccessionPack(), observations, account, person, "h2")
    c = hypothesis(repo, WorkflowAuditPack(), observations, account, person, "h3", "2027-Q1")
    assert [h.id for h in repo.hypotheses(account_id=account, person_id=person)] == [
        a.id,
        b.id,
        c.id,
    ]
    assert repo.get(OpportunityHypothesis, a.id) == a
    assert repo.conn.execute("SELECT COUNT(*) FROM oe_evidence").fetchone()[0] == 2
    assert repo.conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 0
    assert all(h.review_status == "unreviewed" for h in (a, b, c))


def test_replays_noop_conflicts_fail_and_batch_rolls_back(store):
    repo, account, person = store
    observations = facts(repo, account, person)
    a = hypothesis(repo, WorkflowAuditPack(), observations, account, person)
    changes = repo.conn.total_changes
    assert hypothesis(repo, WorkflowAuditPack(), observations, account, person) == a
    assert repo.conn.total_changes == changes
    with pytest.raises(ValueError, match="immutable"):
        repo.put(a.model_copy(update={"thesis": "Changed interpretation"}))
    with pytest.raises(ValueError):
        with repo.transaction():
            repo.put(Product(id="temporary", name="Temporary", description="Rollback test"))
            repo.put(a.model_copy(update={"thesis": "Changed"}))
    with pytest.raises(KeyError):
        repo.get(Product, "temporary")


def test_foreign_keys_subject_isolation_and_atomic_service(store):
    repo, account, person = store
    observations = facts(repo, account, person)
    with pytest.raises(KeyError):
        repo.put(observations[0].model_copy(update={"id": "bad", "evidence_id": "missing"}))
    other, _ = Repository(repo.conn).resolve_person(Person(name="Another Person"), account)
    with pytest.raises(ValueError, match="subject"):
        hypothesis(repo, WorkflowAuditPack(), observations, account, other)
    assert repo.conn.execute("SELECT COUNT(*) FROM oe_products").fetchone()[0] == 0
    assert repo.hypotheses() == []


def test_cross_pack_signal_and_unsupported_signal_rejected(store):
    repo, account, person = store
    observations = facts(repo, account, person)
    a = hypothesis(repo, WorkflowAuditPack(), observations, account, person)
    pack = SuccessionPack()
    repo.put(pack.product)
    repo.put(pack.version)
    with pytest.raises(ValueError, match="different Product Pack"):
        repo.put(a.model_copy(update={"id": "cross-product", "pack_version_id": pack.version.id}))
    with pytest.raises(ValueError, match="supporting observation"):
        repo.put(a.model_copy(update={"id": "missing-support", "observation_ids": ("obs-0",)}))


def test_account_only_hypothesis_and_nullable_person(store):
    repo, account, _ = store
    observations = facts(repo, account)
    hypothesis(repo, WorkflowAuditPack(), observations, account, None)
    assert repo.hypotheses(account_id=account)[0].person_id is None


def test_upgrade_existing_db_twice_preserves_old_rows(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO companies (id, name, normalized_name) VALUES (1, 'Old', 'old')")
    conn.execute(
        "INSERT INTO people (id, name, normalized_name, company_id) "
        "VALUES (1, 'Old Person', 'old person', 1)"
    )
    conn.execute(
        "INSERT INTO opportunities (id, name, person_id, company_id, stage, lead_type) "
        "VALUES (1, 'Old Opportunity', 1, 1, 'new', 'warm')"
    )
    conn.commit()
    before = list(conn.iterdump())
    conn.close()
    for _ in range(2):
        conn = connect(path)
        assert conn.execute("SELECT name FROM opportunities").fetchone()[0] == "Old Opportunity"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        after = list(conn.iterdump())
        assert set(before) <= set(after)
        conn.close()


def test_required_evidence_scores_state_and_immutable_versions(store):
    repo, account, person = store
    with pytest.raises(ValidationError):
        ScoreDimensions(fit=float("nan"))
    observations = facts(repo, account, person)
    h = hypothesis(repo, WorkflowAuditPack(), observations, account, person)
    for updates in ({"signal_ids": ()}, {"state": "APPROVED"}, {"review_status": "confirmed"}):
        with pytest.raises(ValidationError):
            repo.put(h.model_copy(update=updates))
    version = WorkflowAuditPack.version
    with pytest.raises(ValueError, match="immutable"):
        repo.put(version.model_copy(update={"policy": {"changed": True}}))
    with pytest.raises(sqlite3.IntegrityError):
        repo.put(version.model_copy(update={"id": "alias-version"}))


def test_registry_is_explicit_and_rejects_duplicate_versions():
    registry = PackRegistry()
    registry.register(SuccessionPack())
    registry.register(WorkflowAuditPack())
    assert registry.get(WorkflowAuditPack.version.id).version.fixture_only
    with pytest.raises(ValueError, match="already registered"):
        registry.register(SuccessionPack())
    with pytest.raises(KeyError):
        registry.get("unknown")


@pytest.mark.parametrize(
    "predicate,value,classification",
    [
        ("employee_count", 19, "rejected_fit"),
        ("employee_count", 251, "rejected_fit"),
        ("industry", "retail", "rejected_fit"),
        ("manual_hours_week", 1, "no_signal"),
        ("employee_count", True, "insufficient_evidence"),
    ],
)
def test_workflow_gates(store, predicate, value, classification):
    repo, account, person = store
    observations = tuple(
        o.model_copy(update={"value": value}) if o.predicate == predicate else o
        for o in facts(repo, account, person)
    )
    assessment = WorkflowAuditPack().assess(observations)
    assert assessment.classification == classification
    assert not assessment.eligible


def test_workflow_missing_conflicting_and_mixed_subjects(store):
    repo, account, person = store
    observations = facts(repo, account, person)
    assert not WorkflowAuditPack().assess(observations[1:]).eligible
    conflict = observations[0].model_copy(update={"id": "conflict", "value": 1000})
    assert WorkflowAuditPack().assess((*observations, conflict)).classification == "contradiction"
    with pytest.raises(ValueError, match="one resolved subject"):
        WorkflowAuditPack().assess((*observations, conflict.model_copy(update={"account_id": 999})))


def test_succession_compatibility_preserves_all_sample_profiles(settings, samples_dir, store):
    from relationship_intel.extraction.extractor import Extractor
    from relationship_intel.intake.local_folder import LocalFolderSource

    repo, account, person = store
    pack = SuccessionPack()
    classifications = set()
    for raw in LocalFolderSource(samples_dir).iter_transcripts():
        eri = Extractor(settings).extract(raw)
        for profile in eri.lead_profiles:
            observations = tuple(
                Observation(
                    id=f"legacy-{i}",
                    account_id=account,
                    person_id=person,
                    evidence_id="fixture-source",
                    predicate="statement",
                    value=quote,
                    method=f"legacy-extraction:{eri.llm_provider}:{eri.lens_version}",
                    confidence=profile.confidence,
                )
                for i, quote in enumerate(dict.fromkeys(profile.evidence_snippets))
            )
            assessment = pack.from_profile(profile, observations)
            assert assessment.classification == profile.lead_type
            assert assessment.scores.timing_signal == profile.succession_signal_score
            assert assessment.scores.fit is None
            classifications.add(assessment.classification)
            if profile.evidence_snippets:
                with pytest.raises(ValueError, match="registered"):
                    pack.from_profile(profile, ())
    assert {"warm", "referral_source", "not_fit"} <= classifications


def test_referral_cannot_become_succession_prospect(store):
    repo, account, person = store
    observation = facts(repo, account, person)[-1].model_copy(
        update={
            "value": (
                "I can connect you to clients thinking about selling next year; owner of a firm."
            )
        }
    )
    assessment = SuccessionPack().assess((observation,))
    assert assessment.classification == "referral_source"
    assert not assessment.eligible
    assert assessment.scores.timing_signal == 0


def test_legacy_projection_is_opt_in_replayable_and_preserves_old_state(settings, samples_dir):
    from relationship_intel import pipeline
    from relationship_intel.extraction.extractor import Extractor
    from relationship_intel.intake.local_folder import LocalFolderSource
    from relationship_intel.opportunity_engine.compatibility import project_legacy_profile

    pipeline.run_ingest(settings, samples_dir)
    conn = connect(settings.db_path)
    before = [line for line in conn.iterdump() if "oe_" not in line]
    repo = OpportunityRepository(conn)
    projected = []
    for raw in LocalFolderSource(samples_dir).iter_transcripts():
        eri = Extractor(settings).extract(raw)
        for profile in eri.lead_profiles:
            # Sample identities are unique. Production callers must supply canonical IDs.
            row = conn.execute(
                "SELECT id, company_id FROM people WHERE name = ?", (profile.person_name,)
            ).fetchone()
            kwargs = dict(
                account_id=row["company_id"],
                person_id=row["id"],
                lens_version=eri.lens_version,
                llm_provider=eri.llm_provider,
                captured_at=NOW,
            )
            first = project_legacy_profile(repo, raw, profile, **kwargs)
            changes = conn.total_changes
            assert project_legacy_profile(repo, raw, profile, **kwargs) == first
            assert conn.total_changes == changes
            if first:
                projected.append(first)
    assert len(projected) == 1
    assert projected[0].scores.timing_signal > 0
    after = [line for line in conn.iterdump() if "oe_" not in line]
    assert before == after
    conn.close()
