"""Validated intake for qualified cold leads that already exist in Twenty."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from relationship_intel.crm.twenty_adapter import LIFECYCLE_STAGE_VALUES, WEDGE_VALUES
from relationship_intel.extraction.schemas import Company, Person
from relationship_intel.store.repository import Repository


def _canonical_option(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", value.strip()).strip("_").upper()


def _canonical_linkedin_url(value: str) -> str:
    canonical = value.strip().split("?", 1)[0].split("#", 1)[0].rstrip("/").lower()
    return canonical.replace("https://www.linkedin.com/", "https://linkedin.com/", 1)


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
    company_id, company_created = repo.resolve_company(Company(name=lead.firm))
    external_ids = {
        "twenty": lead.twenty_person_id,
        "eos-prospect": lead.prospect_id,
        "linkedin": _canonical_linkedin_url(lead.linkedin_url),
    }
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
    if repo.review_item("person", person_id) is None:
        repo.upsert_review_item("person", person_id, lead.name, payload)
    return {
        "company_id": company_id,
        "company_created": company_created,
        "person_id": person_id,
        "person_created": person_created,
    }
