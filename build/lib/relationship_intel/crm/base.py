"""CRM adapter contract (architecture.md §3.6). Deliberately has NO delete methods —
additive/update-safe only, enforced by tests/test_no_send.py.

Twenty gets summaries, not evidence: attach_note bodies are built from
ConversationSummary fields + a vault link, never evidence snippets (KTD-8c)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class CRMRef:
    provider: str
    object_type: str  # person | company | opportunity | task | note
    crm_id: str
    url: str | None = None


@dataclass(frozen=True)
class AdapterStatus:
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class NotePayload:
    title: str
    body: str  # operational summary + vault link only — never transcript evidence


@dataclass(frozen=True)
class TaskPayload:
    title: str
    body: str
    due_window: str | None = None
    assignee: str | None = None


@dataclass(frozen=True)
class PipelineItem:
    person_name: str
    company_name: str | None
    stage: str
    lead_type: str
    succession_signal_score: int
    urgency: str
    timing_window: str
    next_action: str | None
    next_action_due: str | None
    crm_ref: CRMRef | None = None


class CRMAdapter(ABC):
    provider: str

    def ensure_schema(self) -> dict:
        """Additive schema provisioning: create any custom fields the pipeline
        writes that the CRM lacks. Never alters or deletes existing fields.
        Providers with no provisioning needs inherit this no-op."""
        return {"created": [], "existing": []}

    @abstractmethod
    def find_or_create_contact(self, person: dict) -> CRMRef: ...

    @abstractmethod
    def find_or_create_company(self, company: dict) -> CRMRef: ...

    def find_contact(self, person: dict) -> dict | None:
        """Read-only lookup used by the review UI to detect follow-ups against
        contacts already in the CRM (gh #15). Returns an enrichment dict
        (crm_id, url, name, company_name, email) or None. Default: no-op
        returning None; adapters that support lookup should override."""
        return None

    def find_company(self, company: dict) -> dict | None:
        """Read-only lookup counterpart to find_contact (gh #15). Returns an
        enrichment dict (crm_id, url, name, domain) or None."""
        return None

    @abstractmethod
    def create_or_update_opportunity(self, opportunity: dict) -> CRMRef: ...

    @abstractmethod
    def attach_note(self, ref: CRMRef, note: NotePayload) -> CRMRef: ...

    @abstractmethod
    def create_task(self, ref: CRMRef, task: TaskPayload) -> CRMRef: ...

    @abstractmethod
    def tag_record(self, ref: CRMRef, tags: list[str]) -> None: ...

    @abstractmethod
    def get_pipeline_items(self, owner: str | None = None) -> list[PipelineItem]: ...

    @abstractmethod
    def health_check(self) -> AdapterStatus: ...
