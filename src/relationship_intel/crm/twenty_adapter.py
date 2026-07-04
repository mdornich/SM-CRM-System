"""Twenty CRM adapter — targets the local fork at ~/Documents/GitHub/twenty
(pin: commit 1a60d4ea / v0.2.1, backend on http://localhost:3002).

API facts verified against the fork source on 2026-07-04 (docs/twenty-setup.md):
- REST base path /rest; plural object routes (/rest/people, /rest/companies, ...)
- Auth: `Authorization: Bearer <api-key-jwt>` (key from Settings -> Developers)
- Composite request fields: name {firstName,lastName}, emails {primaryEmail},
  domainName {primaryLinkUrl}, bodyV2 {markdown}
- Filter DSL: filter=emails.primaryEmail[eq]:x@y.com ; response envelopes
  data.<plural> (list) and data.create<Object> (create)
- Default opportunity stages: NEW SCREENING MEETING PROPOSAL CUSTOMER
- Task/note linking goes through join tables (taskTargets/noteTargets) via a
  second POST — the least-verified path until the Phase 2 integration test.

Secrets never reach logs; requests are logged as method+path only."""

from __future__ import annotations

import logging
import re

import httpx

from relationship_intel.crm.base import (
    AdapterStatus,
    CRMAdapter,
    CRMRef,
    NotePayload,
    PipelineItem,
    TaskPayload,
)
from relationship_intel.errors import NotConfiguredError

logger = logging.getLogger(__name__)

# Twenty's filter grammar treats commas as predicate separators inside and()/or()
# wrappers and tracks parens as grouping (verified against the fork's
# parse-filter-content.util.ts). Person-controlled values ("Smith, Jr.",
# "Acme (Holdings)") must never be interpolated into a composite filter — when a
# value can't be expressed safely we skip the lookup and fall through to create.
_DSL_UNSAFE = re.compile(r"[,()\[\]]")


def _filter_safe(value: str | None) -> str | None:
    if not value or _DSL_UNSAFE.search(value):
        return None
    return value


# Spec stage vocabulary -> Twenty default pipeline stages. Unmapped spec stages
# (not_fit, stalled, closed_lost) intentionally do not create opportunities.
STAGE_MAP = {
    "new": "NEW",
    "nurture": "NEW",
    "discovery": "SCREENING",
    "qualified": "MEETING",
    "active_opportunity": "PROPOSAL",
    "closed_won": "CUSTOMER",
}


class TwentyCRMAdapter(CRMAdapter):
    provider = "twenty"

    def __init__(self, api_url: str, api_key: str, transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise NotConfiguredError(
                "TWENTY_API_KEY is not set. Create one in Twenty at Settings -> Developers "
                "(local fork: http://localhost:3001) and export it; see docs/twenty-setup.md."
            )
        self.base_url = api_url.rstrip("/") + "/rest"
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=30,
            transport=transport,
        )

    # -- request plumbing ------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> dict:
        logger.info("twenty %s %s", method, path)  # never log payloads or headers
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def _find_one(self, objects: str, filter_expr: str) -> dict | None:
        payload = self._request("GET", f"/{objects}", params={"filter": filter_expr, "limit": 1})
        records = payload.get("data", {}).get(objects, [])
        return records[0] if records else None

    def _create(self, objects: str, singular: str, body: dict) -> dict:
        payload = self._request("POST", f"/{objects}", json=body)
        key = f"create{singular[0].upper()}{singular[1:]}"
        return payload.get("data", {}).get(key, payload.get("data", {}))

    def _ref(self, object_type: str, record: dict) -> CRMRef:
        return CRMRef(self.provider, object_type, str(record["id"]))

    # -- interface ---------------------------------------------------------------

    def find_or_create_contact(self, person: dict) -> CRMRef:
        email = (person.get("email") or "").lower()
        safe_email = _filter_safe(email)
        if safe_email:
            existing = self._find_one("people", f"emails.primaryEmail[eq]:{safe_email}")
            if existing:
                return self._ref("person", existing)
        first, _, last = person["name"].partition(" ")
        safe_first, safe_last = _filter_safe(first), _filter_safe(last or first)
        if safe_first and safe_last:
            existing = self._find_one(
                "people",
                f"and(name.firstName[eq]:{safe_first},name.lastName[eq]:{safe_last})",
            )
            if existing:
                return self._ref("person", existing)
        body: dict = {"name": {"firstName": first, "lastName": last or first}}
        if email:
            body["emails"] = {"primaryEmail": email}
        if person.get("title"):
            body["jobTitle"] = person["title"]
        if person.get("company_crm_id"):
            body["companyId"] = person["company_crm_id"]
        return self._ref("person", self._create("people", "person", body))

    def find_or_create_company(self, company: dict) -> CRMRef:
        domain = company.get("domain")
        if domain:
            existing = self._find_one(
                "companies", f"domainName.primaryLinkUrl[eq]:https://{domain}"
            )
            if existing:
                return self._ref("company", existing)
        existing = self._find_one("companies", f"name[eq]:{company['name']}")
        if existing:
            return self._ref("company", existing)
        body: dict = {"name": company["name"]}
        if domain:
            body["domainName"] = {"primaryLinkUrl": f"https://{domain}"}
        return self._ref("company", self._create("companies", "company", body))

    def create_or_update_opportunity(self, opportunity: dict) -> CRMRef:
        stage = STAGE_MAP.get(opportunity.get("stage", "new"))
        if stage is None:
            raise ValueError(
                f"Spec stage {opportunity.get('stage')!r} does not map to a Twenty stage; "
                "unmapped stages intentionally do not create opportunities."
            )
        existing = self._find_one("opportunities", f"name[eq]:{opportunity['name']}")
        body: dict = {"name": opportunity["name"], "stage": stage}
        if opportunity.get("person_crm_id"):
            body["pointOfContactId"] = opportunity["person_crm_id"]
        if opportunity.get("company_crm_id"):
            body["companyId"] = opportunity["company_crm_id"]
        if existing:
            self._request("PATCH", f"/opportunities/{existing['id']}", json=body)
            return self._ref("opportunity", existing)
        return self._ref("opportunity", self._create("opportunities", "opportunity", body))

    def attach_note(self, ref: CRMRef, note: NotePayload) -> CRMRef:
        created = self._create(
            "notes", "note", {"title": note.title, "bodyV2": {"markdown": note.body}}
        )
        # Linking via join table — least-verified path until Phase 2 integration test.
        self._request(
            "POST",
            "/noteTargets",
            json={"noteId": created["id"], f"{ref.object_type}Id": ref.crm_id},
        )
        return self._ref("note", created)

    def create_task(self, ref: CRMRef, task: TaskPayload) -> CRMRef:
        created = self._create(
            "tasks",
            "task",
            {"title": task.title, "bodyV2": {"markdown": task.body}, "status": "TODO"},
        )
        self._request(
            "POST",
            "/taskTargets",
            json={"taskId": created["id"], f"{ref.object_type}Id": ref.crm_id},
        )
        return self._ref("task", created)

    def tag_record(self, ref: CRMRef, tags: list[str]) -> None:
        # Twenty has no first-class tag object on core records; Phase 2 decision is
        # whether to model tags as a custom multi-select field. No-op with a log line.
        logger.info("twenty tag_record skipped (no native tags): %s", ",".join(sorted(tags)))

    def get_pipeline_items(self, owner: str | None = None) -> list[PipelineItem]:
        payload = self._request("GET", "/opportunities", params={"limit": 60, "depth": 1})
        items = []
        for record in payload.get("data", {}).get("opportunities", []):
            items.append(
                PipelineItem(
                    person_name=(record.get("pointOfContact") or {})
                    .get("name", {})
                    .get("firstName", ""),
                    company_name=(record.get("company") or {}).get("name"),
                    stage=record.get("stage", "NEW"),
                    lead_type="unknown",
                    succession_signal_score=0,
                    urgency="unknown",
                    timing_window="unknown",
                    next_action=None,
                    next_action_due=None,
                    crm_ref=self._ref("opportunity", record),
                )
            )
        return items

    def health_check(self) -> AdapterStatus:
        try:
            self._request("GET", "/people", params={"limit": 1})
            return AdapterStatus(ok=True, detail=f"twenty reachable at {self.base_url}")
        except (httpx.HTTPError, KeyError) as exc:
            return AdapterStatus(ok=False, detail=f"twenty unreachable: {type(exc).__name__}")
