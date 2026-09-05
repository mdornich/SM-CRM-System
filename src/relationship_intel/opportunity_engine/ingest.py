"""Offline C3 ingestion. Identity resolution and persistence stay outside the mapper.

The ratified #1277 brief defines whole-page records. Nonempty observations[] are
rejected until the referenced #1281 wire contract is available for verification.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from relationship_intel.opportunity_engine.models import Evidence, Observation
from relationship_intel.opportunity_engine.repository import OpportunityRepository
from relationship_intel.store.repository import Repository

# drift: ratified #1277 brief §2 — resolved local (person_id, account_id), no identity I/O.
Subject = tuple[int, int | None]
CONFIDENCE = {"high": 0.9, "medium": 0.6, "low": 0.3, "unknown": 0.0}
PRESENCE = {
    "eos_profile": "eos_directory_listed",
    "firm_website": "firm_website_present",
    "linkedin": "linkedin_public_present",
}


def _key(kind: str, value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return f"c3:{kind}:" + sha256(encoded.encode()).hexdigest()


def _evidence_id(item: dict[str, Any]) -> str:
    """Return the producer's own replay key after re-deriving it from the content.

    The C3 contract (980labsOS phase-13a-brief-integration-contracts) defines
    evidence identity as evidence:v1:sha256(source_ref\\ncontent_hash\\nmethod).
    Minting a second, ingest-local identity for the same page would let the same
    capture land twice under different IDs and collide on the schema's
    UNIQUE(source_type, source_ref, content_hash, locator).
    """
    material = f"{item['source_ref']}\n{item['content_hash']}\n{item['method']}"
    expected = "evidence:v1:" + sha256(material.encode()).hexdigest()
    if item["idempotency_key"] != expected:
        raise ValueError("evidence idempotency key does not match content identity")
    return expected


def _items(record: dict[str, Any]) -> list[dict[str, Any]]:
    if record.get("observations"):
        raise ValueError("nonempty observations[] require the verified #1281 wire contract")
    items = record["evidence"]
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError("evidence must be an array of records")
    return items


def resolve_twenty_subject(repo: Repository, external_id: str) -> Subject | None:
    """Read the existing Twenty crosswalk and linked company; never create a person."""
    people = repo.people_for_external_ids({"twenty": external_id})
    if not people:
        return None
    person_id = people[0]
    row = repo.conn.execute("SELECT company_id FROM people WHERE id = ?", (person_id,)).fetchone()
    return person_id, row["company_id"]


def map_drop_file(
    record: dict[str, Any], subject_by_external_id: Mapping[str, Subject | None]
) -> tuple[tuple[Evidence, ...], tuple[Observation, ...]]:
    """Map successful captures with resolved subjects; skip unresolved records.

    Missing/invalid confidence is rejected, never silently relabeled as unknown.
    Evidence IDs follow the schema's unique source/hash/locator tuple. Immutable
    metadata conflicts remain errors; ingestion never overwrites older evidence.
    """
    evidence, observations = [], []
    for item in _items(record):
        subject = subject_by_external_id.get(item["person_id"])
        if subject is None:
            continue
        if type(item["http_status"]) is not int or not 200 <= item["http_status"] < 300:
            raise ValueError("evidence must describe a successful HTTP capture")
        source_type = item["source_type"]
        if source_type not in PRESENCE:
            raise ValueError(f"unsupported whole-page source_type: {source_type}")
        label = item["confidence"]
        if not isinstance(label, str) or label not in CONFIDENCE:
            raise ValueError("confidence must be high, medium, low, or unknown")
        locator = "page"
        source = Evidence(
            id=_evidence_id(item),
            source_type=source_type,
            source_ref=item["source_ref"],
            content_hash=item["content_hash"],
            locator=locator,
            excerpt=item["excerpt"],
            captured_at=item["captured_at"],
            occurred_at=item.get("occurred_at"),
        )
        values = dict(
            evidence_id=source.id,
            person_id=subject[0],
            account_id=subject[1],
            predicate=PRESENCE[source_type],
            value={"present": True, "url": source.source_ref, "confidence_label": label},
            method=item["method"],
            confidence=CONFIDENCE[label],
        )
        evidence.append(source)
        observations.append(
            Observation.model_validate(dict(id=_key("observation", values), **values))
        )
    return tuple(evidence), tuple(observations)


def ingest_drop_file(
    repo: OpportunityRepository, path: str | Path, resolver: Callable[[str], Subject | None]
) -> dict[str, int]:
    """Resolve and write one file atomically, returning only non-sensitive counts.

    Blocked receipts are carried as a count; they are not evidence or stored in a
    new receipt table. Unresolved counts are per evidence item, not unique person.
    Re-capturing unchanged content is idempotent; the first captured_at is kept.
    """
    with Path(path).open() as stream:
        record = json.load(stream)
    if not isinstance(record, dict):
        raise ValueError("drop file must be an object")
    items = _items(record)
    counts = dict(
        evidence_created=0,
        evidence_existing=0,
        observations_created=0,
        observations_existing=0,
        **{"skipped:unresolved": 0, "blocked_receipts_carried": 0},
    )
    counts["blocked_receipts_carried"] = sum(
        receipt["status"] == "blocked" for receipt in record.get("receipts", [])
    )
    with repo.transaction():
        subjects: dict[str, Subject | None] = {item["person_id"]: None for item in items}
        for external_id in subjects:
            subjects[external_id] = resolver(external_id)
        counts["skipped:unresolved"] = sum(subjects[item["person_id"]] is None for item in items)
        evidence, observations = map_drop_file(record, subjects)
        for kind, proposals in (("evidence", evidence), ("observations", observations)):
            for proposal in proposals:
                try:
                    prior = repo.get(type(proposal), proposal.id)
                except KeyError:
                    state = "created"
                else:
                    state = "existing"
                    # Re-crawling an unchanged page yields the same content hash and
                    # a fresh captured_at. That is a replay, not a new fact, so keep
                    # the first-seen capture time; without this every routine re-run
                    # raised an immutable ID conflict and aborted the whole file.
                    # Any other difference (excerpt, occurred_at) still conflicts.
                    if isinstance(proposal, Evidence):
                        proposal = proposal.model_copy(update={"captured_at": prior.captured_at})
                repo.put(proposal)
                counts[f"{kind}_{state}"] += 1
    return counts
