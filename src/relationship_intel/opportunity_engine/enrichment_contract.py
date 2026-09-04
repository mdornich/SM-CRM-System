"""Pure C3b fixture mapping; not a live intake or qualification service.

Ratified scope: 980labsOS docs/operations/phase-13a-brief-integration-contracts.md.
Unknown confidence stays null in the proposal; current Observation rejects it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def map_enrichment_evidence(
    record: dict[str, Any], *, twenty_person_id: str, person_id: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Map one captured page with an already resolved subject, without I/O.

    Only presence predicates are proposed. A successful fetch is not proof of
    commercial qualification. The caller must validate models before persisting.
    """
    if record["person_id"] != twenty_person_id or type(person_id) is not int or person_id <= 0:
        raise ValueError("a matching Twenty crosswalk and positive local person ID are required")
    if record["method"] != "anonymous_http_get" or not 200 <= record["http_status"] < 300:
        raise ValueError("only successful anonymous HTTP evidence is supported")
    confidence = {"high": 0.9, "medium": 0.6, "low": 0.3, "unknown": None}[record["confidence"]]
    predicate = {
        "eos_profile": "eos_directory_listed",
        "firm_website": "firm_website_present",
        "linkedin": "linkedin_public_present",
    }[record["source_type"]]
    material = f"{record['source_ref']}\n{record['content_hash']}\n{record['method']}"
    evidence_id = "evidence:v1:" + hashlib.sha256(material.encode()).hexdigest()
    if record["idempotency_key"] != evidence_id:
        raise ValueError("evidence idempotency key does not match content identity")
    evidence = {
        "id": evidence_id,
        "source_type": record["source_type"],
        "source_ref": record["source_ref"],
        "content_hash": record["content_hash"],
        "locator": "excerpt:0",
        "excerpt": record["excerpt"],
        "captured_at": record["captured_at"],
        "occurred_at": None,
    }
    value = {"present": True, "confidence_label": record["confidence"]}
    # Proposed serialization, not a claim that the unavailable #1260 audit was verified.
    key_material = json.dumps(
        [evidence_id, person_id, predicate, value, "fetch"], sort_keys=True, separators=(",", ":")
    )
    observation = {
        "id": "observation:v1:" + hashlib.sha256(key_material.encode()).hexdigest(),
        "person_id": person_id,
        "account_id": None,
        "evidence_id": evidence_id,
        "predicate": predicate,
        "value": value,
        "method": "fetch",
        "confidence": confidence,
    }
    return evidence, observation
