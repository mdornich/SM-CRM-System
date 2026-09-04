"""Additive schema v2. Existing tables and row identities are never rewritten."""

SCHEMA_V2 = """
BEGIN;
CREATE TABLE IF NOT EXISTS oe_products (
    id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oe_pack_versions (
    id TEXT PRIMARY KEY NOT NULL,
    product_id TEXT NOT NULL REFERENCES oe_products(id),
    version TEXT NOT NULL, policy TEXT NOT NULL,
    fixture_only INTEGER NOT NULL CHECK(fixture_only IN (0,1)),
    UNIQUE(product_id, version)
);
CREATE TABLE IF NOT EXISTS oe_evidence (
    id TEXT PRIMARY KEY NOT NULL, source_type TEXT NOT NULL, source_ref TEXT NOT NULL,
    content_hash TEXT NOT NULL, locator TEXT NOT NULL, excerpt TEXT NOT NULL,
    captured_at TEXT NOT NULL, occurred_at TEXT,
    UNIQUE(source_type, source_ref, content_hash, locator)
);
CREATE TABLE IF NOT EXISTS oe_observations (
    id TEXT PRIMARY KEY NOT NULL,
    account_id INTEGER REFERENCES companies(id), person_id INTEGER REFERENCES people(id),
    evidence_id TEXT NOT NULL REFERENCES oe_evidence(id),
    predicate TEXT NOT NULL, value TEXT NOT NULL, method TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    CHECK(account_id IS NOT NULL OR person_id IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS oe_signal_definitions (
    id TEXT PRIMARY KEY NOT NULL,
    pack_version_id TEXT NOT NULL REFERENCES oe_pack_versions(id),
    key TEXT NOT NULL, description TEXT NOT NULL,
    UNIQUE(pack_version_id, key)
);
CREATE TABLE IF NOT EXISTS oe_signal_observations (
    id TEXT PRIMARY KEY NOT NULL,
    definition_id TEXT NOT NULL REFERENCES oe_signal_definitions(id),
    observation_id TEXT NOT NULL REFERENCES oe_observations(id),
    strength REAL NOT NULL CHECK(strength BETWEEN 0 AND 100), rationale TEXT NOT NULL,
    UNIQUE(definition_id, observation_id)
);
CREATE TABLE IF NOT EXISTS oe_hypotheses (
    id TEXT PRIMARY KEY NOT NULL,
    account_id INTEGER REFERENCES companies(id), person_id INTEGER REFERENCES people(id),
    pack_version_id TEXT NOT NULL REFERENCES oe_pack_versions(id),
    episode_key TEXT NOT NULL, thesis TEXT NOT NULL, created_at TEXT NOT NULL,
    scores TEXT NOT NULL, scoring_version TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state = 'HYPOTHESIS_CREATED'),
    review_status TEXT NOT NULL CHECK(review_status = 'unreviewed'),
    CHECK(account_id IS NOT NULL OR person_id IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS oe_hypothesis_signals (
    hypothesis_id TEXT NOT NULL REFERENCES oe_hypotheses(id),
    signal_id TEXT NOT NULL REFERENCES oe_signal_observations(id),
    position INTEGER NOT NULL, PRIMARY KEY(hypothesis_id, signal_id),
    UNIQUE(hypothesis_id, position)
);
CREATE TABLE IF NOT EXISTS oe_hypothesis_observations (
    hypothesis_id TEXT NOT NULL REFERENCES oe_hypotheses(id),
    observation_id TEXT NOT NULL REFERENCES oe_observations(id),
    position INTEGER NOT NULL, PRIMARY KEY(hypothesis_id, observation_id),
    UNIQUE(hypothesis_id, position)
);
CREATE INDEX IF NOT EXISTS oe_hypothesis_subject
    ON oe_hypotheses(account_id, person_id, pack_version_id, episode_key);
CREATE INDEX IF NOT EXISTS oe_observation_evidence ON oe_observations(evidence_id);
COMMIT;
"""
