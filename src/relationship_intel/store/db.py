"""SQLite canonical store — pipeline operational state only (entity identity,
idempotency bookkeeping, CRM sync state). Per architecture.md §3.3 this is never
Mitch's canonical knowledge memory; Cairns keeps that role."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY,
    source_system TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    meeting_date TEXT,
    owner TEXT,
    transcript_hash TEXT NOT NULL UNIQUE,
    raw_stored INTEGER NOT NULL DEFAULT 1,
    source_path TEXT
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    domain TEXT,
    website TEXT,
    industry TEXT,
    location TEXT,
    ownership_context TEXT
);

CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    title TEXT,
    relationship_to_owner TEXT,
    company_id INTEGER REFERENCES companies(id),
    identity_confidence TEXT NOT NULL DEFAULT 'high',
    needs_review INTEGER NOT NULL DEFAULT 0,
    review_status TEXT NOT NULL DEFAULT 'unreviewed'
);

CREATE TABLE IF NOT EXISTS lead_profiles (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES people(id),
    transcript_id INTEGER NOT NULL REFERENCES transcripts(id),
    profile_json TEXT NOT NULL,
    lens_version TEXT NOT NULL,
    llm_provider TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    person_id INTEGER REFERENCES people(id),
    company_id INTEGER REFERENCES companies(id),
    stage TEXT NOT NULL,
    lead_type TEXT NOT NULL,
    succession_signal_score INTEGER NOT NULL DEFAULT 0,
    urgency TEXT NOT NULL DEFAULT 'unknown',
    timing_window TEXT NOT NULL DEFAULT 'unknown',
    owner TEXT,
    next_action TEXT,
    next_action_due TEXT,
    UNIQUE(person_id, company_id)
);

CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES people(id),
    transcript_id INTEGER NOT NULL REFERENCES transcripts(id),
    meeting_date TEXT,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE(person_id, transcript_id)
);

CREATE TABLE IF NOT EXISTS crm_sync_state (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    object_type TEXT NOT NULL,
    local_id INTEGER NOT NULL,
    crm_id TEXT NOT NULL,
    url TEXT,
    last_pushed_hash TEXT NOT NULL,
    UNIQUE(provider, object_type, local_id)
);

CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY,
    owner TEXT NOT NULL,
    week_start TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    UNIQUE(owner, week_start)
);

CREATE TABLE IF NOT EXISTS crm_review_items (
    id INTEGER PRIMARY KEY,
    object_type TEXT NOT NULL,
    local_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    payload_json TEXT NOT NULL,
    reason TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(object_type, local_id)
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
