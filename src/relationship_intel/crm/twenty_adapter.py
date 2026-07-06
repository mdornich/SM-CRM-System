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
  second POST using target-prefixed FKs (targetPersonId, ...) — verified live
  against the running fork (Phase 2, 2026-07-04).
- Custom-field provisioning: REST metadata surface at /rest/metadata/objects and
  /rest/metadata/fields, same Bearer auth (key role needs the DATA_MODEL settings
  permission). List envelope is {data: [...], pageInfo, totalCount}; each object
  embeds its fields. Created fields are immediately writable via /rest — the
  metadata mutation invalidates the workspace schema cache automatically
  (workspace-migration-runner.service.ts). SELECT option values must match
  /^[_A-Za-z][_0-9A-Za-z]*$/, field names /^[a-z][a-zA-Z0-9]*$/.

Secrets never reach logs; requests are logged as method+path only."""

from __future__ import annotations

import logging
import re
from copy import deepcopy

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

_LEAD_TYPE_OPTIONS = [
    ("Cold", "COLD", "gray"),
    ("Warm", "WARM", "orange"),
    ("Active", "ACTIVE", "green"),
    ("Referral source", "REFERRAL_SOURCE", "blue"),
    ("Partner", "PARTNER", "purple"),
    ("Not fit", "NOT_FIT", "red"),
    ("Unknown", "UNKNOWN", "gray"),
]
_TIMING_WINDOW_OPTIONS = [
    ("Immediate", "IMMEDIATE", "red"),
    ("0-3 months", "MONTHS_0_3", "orange"),
    ("3-6 months", "MONTHS_3_6", "yellow"),
    ("6-12 months", "MONTHS_6_12", "blue"),
    ("Long term", "LONG_TERM", "gray"),
    ("Unknown", "UNKNOWN", "gray"),
]

_LEAD_TYPE_TO_TWENTY = {
    "cold": "COLD",
    "warm": "WARM",
    "active": "ACTIVE",
    "referral_source": "REFERRAL_SOURCE",
    "partner": "PARTNER",
    "not_fit": "NOT_FIT",
    "unknown": "UNKNOWN",
}
_LEAD_TYPE_FROM_TWENTY = {value: key for key, value in _LEAD_TYPE_TO_TWENTY.items()}
_TIMING_WINDOW_TO_TWENTY = {
    "immediate": "IMMEDIATE",
    "0_3_months": "MONTHS_0_3",
    "3_6_months": "MONTHS_3_6",
    "6_12_months": "MONTHS_6_12",
    "long_term": "LONG_TERM",
    "unknown": "UNKNOWN",
}
_TIMING_WINDOW_FROM_TWENTY = {value: key for key, value in _TIMING_WINDOW_TO_TWENTY.items()}


def _select_options(values: list[tuple[str, str, str]]) -> list[dict]:
    return [
        {"label": label, "value": value, "color": color, "position": index}
        for index, (label, value, color) in enumerate(values)
    ]


OPPORTUNITY_CUSTOM_FIELDS = [
    {
        "name": "successionSignalScore",
        "label": "Succession signal score",
        "description": "Relationship-intel succession score from 0 to 100.",
        "type": "NUMBER",
        "isNullable": True,
        "settings": {"dataType": "int", "decimals": 0, "type": "number"},
    },
    {
        "name": "leadType",
        "label": "Lead type",
        "description": "Relationship-intel lead classification.",
        "type": "SELECT",
        "isNullable": True,
        "options": _select_options(_LEAD_TYPE_OPTIONS),
    },
    {
        "name": "timingWindow",
        "label": "Timing window",
        "description": "Relationship-intel estimated timing window.",
        "type": "SELECT",
        "isNullable": True,
        "options": _select_options(_TIMING_WINDOW_OPTIONS),
    },
]


def _filter_safe(value: str | None) -> str | None:
    if not value or _DSL_UNSAFE.search(value):
        return None
    return value


def _to_twenty_select(value: str | None, mapping: dict[str, str]) -> str | None:
    if value is None:
        return None
    return mapping.get(value, mapping["unknown"])


def _from_twenty_select(value: str | None, mapping: dict[str, str]) -> str:
    if not value:
        return "unknown"
    return mapping.get(value, value.lower())


def _target_link(ref: CRMRef) -> dict:
    """noteTargets/taskTargets FK payload. The join tables use target-prefixed
    relation fields (targetPersonId, targetCompanyId, targetOpportunityId) —
    verified live against the running fork and note-target.workspace-entity.ts."""
    field = f"target{ref.object_type[0].upper()}{ref.object_type[1:]}Id"
    return {field: ref.crm_id}


# Spec stage vocabulary -> Twenty default pipeline stages. Twenty's default board
# has no Lost / Stalled / Not-fit column, so those stages do not create Twenty
# opportunities — they're filtered upstream in sync.py (see NO_OPP_STAGES) and
# reported under stats["skipped_by_stage"] rather than crashing the sync.
STAGE_MAP = {
    "new": "NEW",
    "nurture": "NEW",
    "discovery": "SCREENING",
    "qualified": "MEETING",
    "active_opportunity": "PROPOSAL",
    "closed_won": "CUSTOMER",
}
NO_OPP_STAGES = frozenset({"not_fit", "stalled", "closed_lost"})


class TwentyCRMAdapter(CRMAdapter):
    provider = "twenty"

    def __init__(self, api_url: str, api_key: str, transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise NotConfiguredError(
                "TWENTY_API_KEY is not set. Create one in Twenty at Settings -> Developers "
                "(local fork frontend: http://localhost:3001; backend API: http://localhost:3002) "
                "and export it; see docs/twenty-setup.md."
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

    def _opportunity_metadata(self) -> dict:
        payload = self._request("GET", "/metadata/objects", params={"limit": 1000})
        for record in payload.get("data", []):
            if record.get("nameSingular") == "opportunity":
                return record
        raise RuntimeError("Twenty metadata object 'opportunity' not found")

    # -- interface ---------------------------------------------------------------

    def ensure_schema(self) -> dict:
        opportunity = self._opportunity_metadata()
        fields_by_name = {field.get("name"): field for field in opportunity.get("fields", [])}
        created: list[str] = []
        existing: list[str] = []
        for field in OPPORTUNITY_CUSTOM_FIELDS:
            if field["name"] in fields_by_name:
                existing.append(field["name"])
                continue
            body = deepcopy(field)
            body["objectMetadataId"] = opportunity["id"]
            self._request("POST", "/metadata/fields", json=body)
            created.append(field["name"])
        return {"created": created, "existing": existing}

    def find_or_create_contact(self, person: dict) -> CRMRef:
        email = (person.get("email") or "").lower()
        safe_email = _filter_safe(email)
        if safe_email:
            existing = self._find_one("people", f"emails.primaryEmail[eq]:{safe_email}")
            if existing:
                return self._ref("person", existing)
        first, _, last = person["name"].partition(" ")
        safe_first, safe_last = _filter_safe(first), _filter_safe(last)
        if safe_first and safe_last:
            existing = self._find_one(
                "people",
                f"and(name.firstName[eq]:{safe_first},name.lastName[eq]:{safe_last})",
            )
            if existing:
                return self._ref("person", existing)
        body: dict = {"name": {"firstName": first, "lastName": last}}
        if email:
            body["emails"] = {"primaryEmail": email}
        if person.get("title"):
            body["jobTitle"] = person["title"]
        if person.get("company_crm_id"):
            body["companyId"] = person["company_crm_id"]
        return self._ref("person", self._create("people", "person", body))

    def find_or_create_company(self, company: dict) -> CRMRef:
        domain = _filter_safe(company.get("domain"))
        if domain:
            existing = self._find_one(
                "companies", f"domainName.primaryLinkUrl[eq]:https://{domain}"
            )
            if existing:
                return self._ref("company", existing)
        safe_name = _filter_safe(company["name"])
        if safe_name:
            existing = self._find_one("companies", f"name[eq]:{safe_name}")
            if existing:
                return self._ref("company", existing)
        body: dict = {"name": company["name"]}
        if domain:
            body["domainName"] = {"primaryLinkUrl": f"https://{domain}"}
        return self._ref("company", self._create("companies", "company", body))

    def create_or_update_opportunity(self, opportunity: dict) -> CRMRef:
        stage_key = opportunity.get("stage", "new")
        if stage_key in NO_OPP_STAGES:
            # Filtered upstream in sync.py; this is a defensive guard for direct callers.
            raise ValueError(
                f"Stage {stage_key!r} does not create a Twenty opportunity — "
                "sync.py must filter NO_OPP_STAGES before calling."
            )
        stage = STAGE_MAP.get(stage_key)
        if stage is None:
            raise ValueError(
                f"Unknown spec stage {stage_key!r}; extend STAGE_MAP or add to NO_OPP_STAGES."
            )
        safe_name = _filter_safe(opportunity["name"])
        existing = self._find_one("opportunities", f"name[eq]:{safe_name}") if safe_name else None
        body: dict = {"name": opportunity["name"], "stage": stage}
        if opportunity.get("person_crm_id"):
            body["pointOfContactId"] = opportunity["person_crm_id"]
        if opportunity.get("company_crm_id"):
            body["companyId"] = opportunity["company_crm_id"]
        if "lead_type" in opportunity:
            body["leadType"] = _to_twenty_select(opportunity["lead_type"], _LEAD_TYPE_TO_TWENTY)
        if "succession_signal_score" in opportunity:
            body["successionSignalScore"] = opportunity["succession_signal_score"]
        if "timing_window" in opportunity:
            body["timingWindow"] = _to_twenty_select(
                opportunity["timing_window"], _TIMING_WINDOW_TO_TWENTY
            )
        if existing:
            self._request("PATCH", f"/opportunities/{existing['id']}", json=body)
            return self._ref("opportunity", existing)
        return self._ref("opportunity", self._create("opportunities", "opportunity", body))

    def attach_note(self, ref: CRMRef, note: NotePayload) -> CRMRef:
        # Retry-safe two-phase create+link: reuse an existing same-title note
        # (a prior run may have created it but crashed before linking), refresh
        # its body, and only link when no target row exists yet — otherwise a
        # crash between create and link duplicates the note on every retry.
        existing = self._find_by_title("notes", note.title)
        if existing:
            self._request(
                "PATCH", f"/notes/{existing['id']}", json={"bodyV2": {"markdown": note.body}}
            )
            self._ensure_target("noteTargets", "noteId", existing["id"], ref)
            return self._ref("note", existing)
        created = self._create(
            "notes", "note", {"title": note.title, "bodyV2": {"markdown": note.body}}
        )
        # Linking via join table — least-verified path until Phase 2 integration test.
        self._request(
            "POST",
            "/noteTargets",
            json={"noteId": created["id"], **_target_link(ref)},
        )
        return self._ref("note", created)

    def create_task(self, ref: CRMRef, task: TaskPayload) -> CRMRef:
        existing = self._find_by_title("tasks", task.title)
        if existing:
            self._request(
                "PATCH", f"/tasks/{existing['id']}", json={"bodyV2": {"markdown": task.body}}
            )
            self._ensure_target("taskTargets", "taskId", existing["id"], ref)
            return self._ref("task", existing)
        created = self._create(
            "tasks",
            "task",
            {"title": task.title, "bodyV2": {"markdown": task.body}, "status": "TODO"},
        )
        self._request(
            "POST",
            "/taskTargets",
            json={"taskId": created["id"], **_target_link(ref)},
        )
        return self._ref("task", created)

    def _find_by_title(self, objects: str, title: str) -> dict | None:
        safe_title = _filter_safe(title)
        if not safe_title:
            return None
        return self._find_one(objects, f"title[eq]:{safe_title}")

    def _ensure_target(self, objects: str, id_field: str, record_id: str, ref: CRMRef) -> None:
        payload = self._request(
            "GET", f"/{objects}", params={"filter": f"{id_field}[eq]:{record_id}", "limit": 1}
        )
        if not payload.get("data", {}).get(objects, []):
            self._request("POST", f"/{objects}", json={id_field: record_id, **_target_link(ref)})

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
                    lead_type=_from_twenty_select(record.get("leadType"), _LEAD_TYPE_FROM_TWENTY),
                    succession_signal_score=int(record.get("successionSignalScore") or 0),
                    urgency="unknown",
                    timing_window=_from_twenty_select(
                        record.get("timingWindow"), _TIMING_WINDOW_FROM_TWENTY
                    ),
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
