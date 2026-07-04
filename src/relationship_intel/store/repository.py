"""Repository — the only access path to the canonical store.

Entity resolution implements architecture.md §3.4 exactly:
  people:    (1) email match  (2) normalized name + company  (3) name-only w/o
             company conflict -> flagged medium  (4) new, flagged needs_review
             when edit-distance <= 2 from an existing name
  companies: normalized name (corporate suffixes stripped); domain match overrides.
Ambiguity surfaces (needs_review / medium confidence) rather than silently merging."""

from __future__ import annotations

import json
import re
import sqlite3

from relationship_intel.extraction.schemas import Company, Person
from relationship_intel.store.models import CompanyRecord, OpportunityRecord, PersonRecord

_HONORIFICS = {"mr", "mrs", "ms", "dr", "prof", "sir"}
_COMPANY_SUFFIXES = {"inc", "llc", "co", "corp", "ltd", "company", "corporation", "group"}


def normalize_person_name(name: str) -> str:
    tokens = re.sub(r"[^\w\s]", "", name.lower()).split()
    return " ".join(t for t in tokens if t not in _HONORIFICS)


def normalize_company_name(name: str) -> str:
    tokens = re.sub(r"[^\w\s]", "", name.lower()).split()
    while tokens and tokens[-1] in _COMPANY_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = curr
    return prev[-1]


def _domain_of(website: str | None) -> str | None:
    if not website:
        return None
    domain = re.sub(r"^https?://", "", website.strip().lower()).split("/")[0]
    return domain.removeprefix("www.") or None


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # -- transcripts ---------------------------------------------------------

    def register_transcript(self, raw, store_raw: bool = True) -> tuple[int, bool]:
        row = self.conn.execute(
            "SELECT id FROM transcripts WHERE transcript_hash = ?", (raw.transcript_hash,)
        ).fetchone()
        if row:
            return row["id"], False
        cur = self.conn.execute(
            "INSERT INTO transcripts (source_system, source_id, title, meeting_date, owner,"
            " transcript_hash, raw_stored, source_path) VALUES (?,?,?,?,?,?,?,?)",
            (
                raw.source_system,
                raw.source_id,
                raw.title,
                raw.meeting_date.isoformat() if raw.meeting_date else None,
                raw.owner,
                raw.transcript_hash,
                1 if store_raw else 0,
                str(raw.source_path) if raw.source_path else None,
            ),
        )
        self.conn.commit()
        return cur.lastrowid, True

    # -- companies -----------------------------------------------------------

    def resolve_company(self, company: Company) -> tuple[int, bool]:
        domain = _domain_of(company.website)
        if domain:
            row = self.conn.execute(
                "SELECT id FROM companies WHERE domain = ?", (domain,)
            ).fetchone()
            if row:
                return row["id"], False
        normalized = normalize_company_name(company.name)
        row = self.conn.execute(
            "SELECT id, domain FROM companies WHERE normalized_name = ?", (normalized,)
        ).fetchone()
        if row:
            if domain and not row["domain"]:
                self.conn.execute(
                    "UPDATE companies SET domain = ?, website = ? WHERE id = ?",
                    (domain, company.website, row["id"]),
                )
                self.conn.commit()
            return row["id"], False
        cur = self.conn.execute(
            "INSERT INTO companies (name, normalized_name, domain, website, industry,"
            " location, ownership_context) VALUES (?,?,?,?,?,?,?)",
            (
                company.name,
                normalized,
                domain,
                company.website,
                company.industry,
                company.location,
                company.ownership_context,
            ),
        )
        self.conn.commit()
        return cur.lastrowid, True

    # -- people --------------------------------------------------------------

    def resolve_person(self, person: Person, company_id: int | None) -> tuple[int, bool]:
        # Rule 1: email match (case-insensitive, exact) — highest authority.
        if person.email:
            row = self.conn.execute(
                "SELECT id FROM people WHERE lower(email) = lower(?)", (person.email,)
            ).fetchone()
            if row:
                self._backfill_person(row["id"], person, company_id)
                return row["id"], False

        normalized = normalize_person_name(person.name)

        # Rule 2: normalized name + company match.
        if company_id is not None:
            row = self.conn.execute(
                "SELECT id FROM people WHERE normalized_name = ? AND company_id = ?",
                (normalized, company_id),
            ).fetchone()
            if row:
                self._backfill_person(row["id"], person, company_id)
                return row["id"], False

        # Rule 3: name-only match with no company conflict -> medium confidence.
        rows = self.conn.execute(
            "SELECT id, company_id FROM people WHERE normalized_name = ?", (normalized,)
        ).fetchall()
        for row in rows:
            conflict = (
                company_id is not None
                and row["company_id"] is not None
                and row["company_id"] != company_id
            )
            if not conflict:
                self.conn.execute(
                    "UPDATE people SET identity_confidence = 'medium' WHERE id = ?",
                    (row["id"],),
                )
                self._backfill_person(row["id"], person, company_id)
                return row["id"], False

        # Rule 4: new person; flag near-duplicates (edit distance <= 2) for review.
        needs_review = any(
            0 < edit_distance(normalized, existing["normalized_name"]) <= 2
            for existing in self.conn.execute("SELECT normalized_name FROM people").fetchall()
        )
        cur = self.conn.execute(
            "INSERT INTO people (name, normalized_name, email, phone, title,"
            " relationship_to_owner, company_id, identity_confidence, needs_review)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                person.name,
                normalized,
                person.email,
                person.phone,
                person.title,
                person.relationship_to_owner,
                company_id,
                person.identity_confidence.value,
                1 if needs_review else 0,
            ),
        )
        self.conn.commit()
        return cur.lastrowid, True

    def _backfill_person(self, person_id: int, person: Person, company_id: int | None) -> None:
        """Fill missing fields on match; never overwrite existing values."""
        row = self.conn.execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()
        updates, params = [], []
        for column, value in (
            ("email", person.email),
            ("phone", person.phone),
            ("title", person.title),
            ("company_id", company_id),
        ):
            if value is not None and row[column] is None:
                updates.append(f"{column} = ?")
                params.append(value)
        if updates:
            self.conn.execute(
                f"UPDATE people SET {', '.join(updates)} WHERE id = ?", (*params, person_id)
            )
            self.conn.commit()

    # -- profiles / interactions / opportunities ------------------------------

    def add_lead_profile(
        self,
        person_id: int,
        transcript_id: int,
        profile_json: str,
        lens_version: str,
        llm_provider: str,
    ) -> None:
        exists = self.conn.execute(
            "SELECT 1 FROM lead_profiles WHERE person_id = ? AND transcript_id = ?",
            (person_id, transcript_id),
        ).fetchone()
        if exists:
            return
        self.conn.execute(
            "INSERT INTO lead_profiles (person_id, transcript_id, profile_json, lens_version,"
            " llm_provider) VALUES (?,?,?,?,?)",
            (person_id, transcript_id, profile_json, lens_version, llm_provider),
        )
        self.conn.commit()

    def add_interaction(
        self, person_id: int, transcript_id: int, meeting_date: str | None, evidence: list[str]
    ) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO interactions (person_id, transcript_id, meeting_date,"
            " evidence_json) VALUES (?,?,?,?)",
            (person_id, transcript_id, meeting_date, json.dumps(evidence)),
        )
        self.conn.commit()

    def upsert_opportunity(
        self,
        name: str,
        person_id: int | None,
        company_id: int | None,
        profile: dict,
        owner: str | None,
    ) -> int:
        row = self.conn.execute(
            "SELECT id FROM opportunities WHERE person_id IS ? AND company_id IS ?",
            (person_id, company_id),
        ).fetchone()
        values = (
            profile.get("stage", "new"),
            profile.get("lead_type", "unknown"),
            int(profile.get("succession_signal_score", 0)),
            profile.get("urgency", "unknown"),
            profile.get("timing_window", "unknown"),
            owner,
            profile.get("next_best_action"),
            profile.get("next_action_due_window"),
        )
        if row:
            self.conn.execute(
                "UPDATE opportunities SET name=?, stage=?, lead_type=?,"
                " succession_signal_score=?, urgency=?, timing_window=?, owner=?,"
                " next_action=?, next_action_due=? WHERE id=?",
                (name, *values, row["id"]),
            )
            self.conn.commit()
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO opportunities (name, person_id, company_id, stage, lead_type,"
            " succession_signal_score, urgency, timing_window, owner, next_action,"
            " next_action_due) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (name, person_id, company_id, *values),
        )
        self.conn.commit()
        return cur.lastrowid

    # -- crm sync state --------------------------------------------------------

    def get_sync_state(self, provider: str, object_type: str, local_id: int):
        return self.conn.execute(
            "SELECT crm_id, url, last_pushed_hash FROM crm_sync_state"
            " WHERE provider=? AND object_type=? AND local_id=?",
            (provider, object_type, local_id),
        ).fetchone()

    def set_sync_state(
        self,
        provider: str,
        object_type: str,
        local_id: int,
        crm_id: str,
        url: str | None,
        pushed_hash: str,
    ) -> None:
        self.conn.execute(
            "INSERT INTO crm_sync_state (provider, object_type, local_id, crm_id, url,"
            " last_pushed_hash) VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(provider, object_type, local_id)"
            " DO UPDATE SET crm_id=excluded.crm_id, url=excluded.url,"
            " last_pushed_hash=excluded.last_pushed_hash",
            (provider, object_type, local_id, crm_id, url, pushed_hash),
        )
        self.conn.commit()

    # -- plans -----------------------------------------------------------------

    def save_plan(self, owner: str, week_start: str, plan_json: str) -> None:
        self.conn.execute(
            "INSERT INTO plans (owner, week_start, plan_json) VALUES (?,?,?)"
            " ON CONFLICT(owner, week_start) DO UPDATE SET plan_json=excluded.plan_json",
            (owner, week_start, plan_json),
        )
        self.conn.commit()

    # -- read side for writer/planner -------------------------------------------

    def people_records(self) -> list[PersonRecord]:
        records = []
        for row in self.conn.execute(
            "SELECT p.*, c.name AS company_name FROM people p"
            " LEFT JOIN companies c ON c.id = p.company_id ORDER BY p.id"
        ).fetchall():
            profile_row = self.conn.execute(
                "SELECT profile_json FROM lead_profiles WHERE person_id = ?"
                " ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            last = self.conn.execute(
                "SELECT max(meeting_date) AS d FROM interactions WHERE person_id = ?",
                (row["id"],),
            ).fetchone()
            evidence: list[str] = []
            transcripts: list[tuple[str | None, str]] = []
            for i_row in self.conn.execute(
                "SELECT i.evidence_json, t.title, t.meeting_date FROM interactions i"
                " JOIN transcripts t ON t.id = i.transcript_id"
                " WHERE i.person_id = ? ORDER BY i.id",
                (row["id"],),
            ).fetchall():
                evidence.extend(json.loads(i_row["evidence_json"]))
                transcripts.append((i_row["meeting_date"], i_row["title"]))
            records.append(
                PersonRecord(
                    id=row["id"],
                    name=row["name"],
                    email=row["email"],
                    title=row["title"],
                    company_id=row["company_id"],
                    company_name=row["company_name"],
                    identity_confidence=row["identity_confidence"],
                    needs_review=bool(row["needs_review"]),
                    last_interaction=last["d"] if last else None,
                    profile=json.loads(profile_row["profile_json"]) if profile_row else None,
                    evidence=evidence,
                    transcripts=transcripts,
                )
            )
        return records

    def company_records(self) -> list[CompanyRecord]:
        records = []
        for row in self.conn.execute("SELECT * FROM companies ORDER BY id").fetchall():
            names = [
                r["name"]
                for r in self.conn.execute(
                    "SELECT name FROM people WHERE company_id = ? ORDER BY id", (row["id"],)
                ).fetchall()
            ]
            records.append(
                CompanyRecord(
                    id=row["id"],
                    name=row["name"],
                    domain=row["domain"],
                    website=row["website"],
                    industry=row["industry"],
                    location=row["location"],
                    ownership_context=row["ownership_context"],
                    people_names=names,
                )
            )
        return records

    def opportunity_records(self) -> list[OpportunityRecord]:
        records = []
        for row in self.conn.execute(
            "SELECT o.*, p.name AS person_name, c.name AS company_name FROM opportunities o"
            " LEFT JOIN people p ON p.id = o.person_id"
            " LEFT JOIN companies c ON c.id = o.company_id ORDER BY o.id"
        ).fetchall():
            records.append(
                OpportunityRecord(
                    id=row["id"],
                    name=row["name"],
                    person_id=row["person_id"],
                    person_name=row["person_name"],
                    company_id=row["company_id"],
                    company_name=row["company_name"],
                    stage=row["stage"],
                    lead_type=row["lead_type"],
                    succession_signal_score=row["succession_signal_score"],
                    urgency=row["urgency"],
                    timing_window=row["timing_window"],
                    owner=row["owner"],
                    next_action=row["next_action"],
                    next_action_due=row["next_action_due"],
                )
            )
        return records

    def transcript_records(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM transcripts ORDER BY id").fetchall()

    def counts(self) -> dict[str, int]:
        return {
            table: self.conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
            for table in (
                "transcripts",
                "people",
                "companies",
                "opportunities",
                "lead_profiles",
                "interactions",
            )
        }
