"""Validated intake for qualified cold leads that already exist in Twenty."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from relationship_intel.crm.twenty_adapter import LIFECYCLE_STAGE_VALUES, WEDGE_VALUES
from relationship_intel.extraction.schemas import Company, Person
from relationship_intel.store.repository import Repository

logger = logging.getLogger(__name__)


def _canonical_option(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", value.strip()).strip("_").upper()


def _canonical_linkedin_url(value: str) -> str:
    """Fold the ways one profile URL gets written into a single identity.

    Scheme and `www.` are part of that: `http://www.linkedin.com/in/ada`,
    `linkedin.com/in/ada` and the https form name the same person, and three
    distinct external ids would make Rule 0 miss and silently drop back to the
    name/email fallbacks this path exists to pre-empt.
    """
    canonical = value.strip().split("?", 1)[0].split("#", 1)[0].rstrip("/").lower()
    canonical = re.sub(r"^[a-z][a-z0-9+.-]*://", "", canonical)
    canonical = re.sub(r"^www\.", "", canonical)
    return f"https://{canonical}"


class QualifiedLead(BaseModel):
    twenty_person_id: str = Field(min_length=1)
    prospect_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    firm: str = Field(min_length=1)
    linkedin_url: str = Field(min_length=1)
    wedge: str = Field(min_length=1)
    source: str = Field(min_length=1)
    lifecycle: str = Field(min_length=1)
    proof_pointers: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    email: str | None = None
    title: str | None = None
    draft_ref: str | None = None
    pack_version_id: str | None = None

    @model_validator(mode="after")
    def validate_closed_values(self) -> QualifiedLead:
        wedge = _canonical_option(self.wedge)
        lifecycle = _canonical_option(self.lifecycle)
        if wedge not in WEDGE_VALUES:
            raise ValueError(f"unknown wedge value: {self.wedge!r}")
        if lifecycle not in LIFECYCLE_STAGE_VALUES:
            raise ValueError(f"unknown lifecycle value: {self.lifecycle!r}")
        if any(not pointer.strip() for pointer in self.proof_pointers):
            raise ValueError("proof pointers must not be blank")
        return self


def load_qualified_lead(path: Path) -> QualifiedLead:
    return QualifiedLead.model_validate_json(path.read_text())


def intake_qualified_lead(repo: Repository, lead: QualifiedLead) -> dict:
    """Create the local crosswalk and pending proposal; repeated input is a no-op."""
    external_ids = {
        "twenty": lead.twenty_person_id,
        "eos-prospect": lead.prospect_id,
        "linkedin": _canonical_linkedin_url(lead.linkedin_url),
    }
    # Check for mixed identities BEFORE the first write. `resolve_person`
    # raises on this too, but by then `resolve_company` has already committed
    # a row, leaving an orphan company behind every rejected record.
    if len(repo.people_for_external_ids(external_ids)) > 1:
        raise ValueError(
            f"external ids for {lead.name!r} resolve to different people; "
            "resolve the duplicate before intaking this record"
        )
    company_id, company_created = repo.resolve_company(Company(name=lead.firm))
    person_id, person_created = repo.resolve_person(
        Person(name=lead.name, email=lead.email, title=lead.title), company_id, external_ids
    )
    existing_ref = {
        "provider": "twenty",
        "object_type": "person",
        "crm_id": lead.twenty_person_id,
    }
    sync_state = repo.get_sync_state("twenty", "person", person_id)
    if sync_state is None:
        repo.set_sync_state("twenty", "person", person_id, lead.twenty_person_id, None, "")
    elif sync_state["crm_id"] != lead.twenty_person_id:
        # The record and the crosswalk disagree about which Twenty person this
        # is. Don't pick a winner silently — the operator has to say which one
        # is right, and the existing crosswalk is what sync already trusts.
        logger.warning(
            "cold intake for %r names Twenty person %s but the crosswalk already"
            " points at %s; leaving the crosswalk alone",
            lead.name,
            lead.twenty_person_id,
            sync_state["crm_id"],
        )
    wedge = _canonical_option(lead.wedge)
    payload = {
        "name": lead.name,
        "email": lead.email,
        "title": lead.title,
        "wedge": [wedge],
        "wedge_primary": wedge,
        "source": lead.source,
        "lifecycle_stage": _canonical_option(lead.lifecycle),
        "proof_pointers": lead.proof_pointers,
        "confidence": lead.confidence,
        "draft_ref": lead.draft_ref,
        "pack_version_id": lead.pack_version_id,
        "existing_crm_ref": existing_ref,
    }
    review_state = _queue_review_item(repo, person_id, lead.name, payload)
    return {
        "company_id": company_id,
        "company_created": company_created,
        "person_id": person_id,
        "person_created": person_created,
        "review_item": review_state,
    }


def _queue_review_item(repo: Repository, person_id: int, label: str, payload: dict) -> str:
    """Queue the cold-lead payload without ever clobbering a reviewer's edits.

    A qualified cold lead frequently resolves to somebody the pipeline has
    already queued from a transcript. That row's payload carries none of the
    GTM keys, and `upsert_review_item` deliberately leaves `payload_json`
    alone on conflict — so simply skipping the write dropped `wedge`,
    `lifecycle_stage`, `proof_pointers` AND `existing_crm_ref` on the floor.
    Losing the ref is the damaging half: without it `sync` falls through to
    `find_or_create_contact` and creates a duplicate Twenty person, which is
    the exact outcome this intake path exists to prevent.

    So merge in only the keys the stored payload does not already answer. A
    repeated intake finds every key populated and writes nothing, which keeps
    the operation idempotent and leaves reviewer corrections intact.
    """
    existing = repo.review_item("person", person_id)
    if existing is None:
        repo.upsert_review_item("person", person_id, label, payload)
        return "created"
    updates = {
        key: value
        for key, value in payload.items()
        if value is not None and existing.payload.get(key) is None
    }
    if existing.payload.get("existing_crm_ref") != payload["existing_crm_ref"]:
        # The intake record is the authority on which Twenty person this is, so
        # replace whatever is stored. Two ways the stored value goes wrong: a
        # ref flattened to a string by an older form round-trip, and a ref
        # `rebuild_review_queue` cached from a name/email lookup that matched a
        # stale duplicate contact. Left in place, the second one sends this
        # lead's GTM fields to the wrong Twenty record.
        updates["existing_crm_ref"] = payload["existing_crm_ref"]
    if not updates:
        return "unchanged"
    repo.merge_review_item_payload("person", person_id, updates)
    return "updated"
