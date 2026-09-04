"""Twenty CRM adapter — targets the local fork at ~/Documents/GitHub/twenty
(pin: commit 1a60d4ea / v0.2.1, backend on http://localhost:3002).

API facts verified against the fork source on 2026-07-04 (docs/twenty-setup.md):
- REST base path /rest; plural object routes (/rest/people, /rest/companies, ...)
- Auth: `Authorization: Bearer <api-key-jwt>` (key from Settings -> Developers)
- Composite request fields: name {firstName,lastName}, emails {primaryEmail},
  domainName {primaryLinkUrl}, bodyV2 {markdown}
- Filter DSL: filter=emails.primaryEmail[eq]:x@y.com ; response envelopes
  data.<plural> (list), data.create<Object> (create) and data.<singular> for a
  by-id read GET /rest/people/{id} (verified read-only on the mini, 2026-09-03)
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
from relationship_intel.crm.twenty_provisioner import (
    REVIEW_STATUS_FIELD_NAME,
    REVIEW_STATUS_VALUES,
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

# --- Person GTM fields (Succession gtm-crm-architecture.md §4) ------------------
# Option labels/values/colors/positions below were read live (GET only) from the
# running Twenty on the mini via /rest/metadata/objects, so PERSON_CUSTOM_FIELDS
# provisions exactly what already exists there and ensure_schema stays a no-op
# against that workspace. Re-verified 2026-09-03 after Mitch removed a stray
# live-only `NA` wedge option: `wedge` and `wedgePrimary` now carry exactly the
# five §4 values, so `NA` fails closed like any other unknown value.
_WEDGE_OPTIONS = [
    ("EOS Practitioner", "EOS_PRACTITIONER", "green"),
    ("Acquirer", "ACQUIRER", "jade"),
    ("Exit Planner", "EXIT_PLANNER", "mint"),
    ("XPX", "XPX", "turquoise"),
    ("Other", "OTHER", "cyan"),
]
# Wedge-Primary is single-valued over the same §4 value set.
_WEDGE_PRIMARY_OPTIONS = list(_WEDGE_OPTIONS)
# §4 order: Cold -> Contacted -> Engaged -> Meeting -> Opportunity -> Customer /
# Lost / Nurture. This list is the single source of truth for both the field's
# option set AND the forward-only write guard: LIFECYCLE_STAGE_ORDER and the
# progression below are derived from it, so adding a stage here automatically
# extends the guard instead of silently opening a hole in it.
_LIFECYCLE_STAGE_OPTIONS = [
    ("Cold", "COLD", "green"),
    ("Contacted", "CONTACTED", "jade"),
    ("Engaged", "ENGAGED", "mint"),
    ("Meeting", "MEETING", "turquoise"),
    ("Opportunity", "OPPORTUNITY", "cyan"),
    ("Customer", "CUSTOMER", "sky"),
    ("Lost", "LOST", "blue"),
    ("Nurture", "NURTURE", "iris"),
]

WEDGE_VALUES = [value for _, value, _ in _WEDGE_OPTIONS]
WEDGE_PRIMARY_VALUES = [value for _, value, _ in _WEDGE_PRIMARY_OPTIONS]
LIFECYCLE_STAGE_VALUES = [value for _, value, _ in _LIFECYCLE_STAGE_OPTIONS]
# §4's ordered stage vocabulary, exported for callers that reason about it and
# used by `lifecycle_is_forward` below — there is no second copy of the order.
LIFECYCLE_STAGE_ORDER = tuple(LIFECYCLE_STAGE_VALUES)
# "Any -> Lost" and "Any -> Nurture" (§4): reachable from anywhere, so they sit
# outside the progression rather than at the end of it.
LIFECYCLE_TERMINAL_STAGES = frozenset({"LOST", "NURTURE"})
LIFECYCLE_PROGRESSION = tuple(
    stage for stage in LIFECYCLE_STAGE_ORDER if stage not in LIFECYCLE_TERMINAL_STAGES
)


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


PERSON_CUSTOM_FIELDS = [
    {
        "name": "wedge",
        "label": "Wedge",
        "description": "GTM wedge tags; a person may belong to more than one campaign.",
        "type": "MULTI_SELECT",
        "isNullable": True,
        "options": _select_options(_WEDGE_OPTIONS),
    },
    {
        "name": "wedgePrimary",
        "label": "Wedge-Primary",
        "description": "Single primary wedge designation for filtered views and reporting.",
        "type": "SELECT",
        "isNullable": True,
        "options": _select_options(_WEDGE_PRIMARY_OPTIONS),
    },
    {
        "name": "source",
        "label": "Source",
        "description": "Acquisition source for attribution (e.g. warm-james, cold-eos-list).",
        "type": "TEXT",
        "isNullable": True,
    },
    {
        "name": "lifecycleStage",
        "label": "Lifecycle Stage",
        "description": "GTM lifecycle stage: Cold -> Contacted -> Engaged -> Meeting -> "
        "Opportunity -> Customer / Lost / Nurture.",
        "type": "SELECT",
        "isNullable": True,
        "options": _select_options(_LIFECYCLE_STAGE_OPTIONS),
    },
]

# Person-dict key (pipeline vocabulary) -> Twenty field name + allowed values.
PERSON_SELECT_FIELDS = {
    "wedge_primary": ("wedgePrimary", WEDGE_PRIMARY_VALUES),
    "lifecycle_stage": ("lifecycleStage", LIFECYCLE_STAGE_VALUES),
}
PERSON_MULTI_SELECT_FIELDS = {"wedge": ("wedge", WEDGE_VALUES)}
PERSON_TEXT_FIELDS = {"source": "source"}

_NON_IDENT = re.compile(r"[^0-9A-Za-z]+")


def _normalize_option(value: str) -> str:
    """Accept the Twenty option value, the human label, or a snake/space
    variant ('EOS Practitioner', 'eos_practitioner') and fold them onto the
    canonical Twenty value."""
    return _NON_IDENT.sub("_", value.strip()).strip("_").upper()


def _coerce_option(value, field_label: str, allowed: list[str]) -> str:
    if not isinstance(value, str):
        raise ValueError(
            f"{field_label} must be a string option value, got {type(value).__name__}; "
            f"allowed: {', '.join(allowed)}"
        )
    normalized = _normalize_option(value)
    if normalized not in allowed:
        # Fail closed: an unknown option must never be silently dropped, nor
        # written (Twenty would 400 mid-sync, or worse, scope the write oddly).
        raise ValueError(f"Unknown {field_label} value {value!r}; allowed: {', '.join(allowed)}")
    return normalized


def person_custom_field_body(person: dict) -> dict:
    """Validate and translate the four GTM Person custom fields into a Twenty
    REST body fragment. Raises ValueError before any request is issued when a
    select/multi-select value is not in the field's option list.

    A key that is absent — OR explicitly None — is absent from the result. The
    adapter has NO clearing semantics for these fields (matching base.py's
    additive/update-safe contract): an explicit None used to PATCH
    `lifecycleStage: null`, which wiped a human-set stage and bypassed the §4
    forward-only guard entirely. Clearing a GTM field is a human action in the
    Twenty UI, never a sync side effect."""
    body: dict = {}
    for key, (field_name, allowed) in PERSON_SELECT_FIELDS.items():
        if person.get(key) is None:
            continue
        body[field_name] = _coerce_option(person[key], key, allowed)
    for key, (field_name, allowed) in PERSON_MULTI_SELECT_FIELDS.items():
        if person.get(key) is None:
            continue
        value = person[key]
        if isinstance(value, str) or not isinstance(value, (list, tuple)):
            raise ValueError(f"{key} must be a list of option values, got {value!r}")
        # Normalisation collapses variants onto one canonical value, so
        # ["Other", "other"] would otherwise send a duplicate. De-duplicate
        # while preserving the caller's order.
        seen: dict[str, None] = {}
        for item in value:
            seen.setdefault(_coerce_option(item, key, allowed), None)
        body[field_name] = list(seen)
    for key, field_name in PERSON_TEXT_FIELDS.items():
        if person.get(key) is None:
            continue
        value = person[key]
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string, got {type(value).__name__}")
        body[field_name] = value
    return body


PERSON_GTM_KEYS = (
    frozenset(PERSON_SELECT_FIELDS)
    | frozenset(PERSON_MULTI_SELECT_FIELDS)
    | frozenset(PERSON_TEXT_FIELDS)
)


def has_person_gtm_fields(person: dict) -> bool:
    """True when the payload carries at least one of the four GTM Person keys."""
    return not PERSON_GTM_KEYS.isdisjoint(person)


def lifecycle_is_forward(current: str | None, proposed: str) -> bool:
    """§4 transition guard. A sync may only move a person forward along the
    progression, or park them in a terminal stage (Lost / Nurture). It may
    never regress a stage, re-write the same stage, or auto-revive someone a
    human parked in Lost / Nurture — same "manual Twenty edits win" rule the
    opportunity PATCH path applies to reviewStatus."""
    if not current or (
        current not in LIFECYCLE_PROGRESSION and current not in LIFECYCLE_TERMINAL_STAGES
    ):
        return True  # nothing known to protect
    if current == proposed:
        return False
    if current in LIFECYCLE_TERMINAL_STAGES:
        return False
    if proposed in LIFECYCLE_TERMINAL_STAGES:
        return True
    if proposed not in LIFECYCLE_PROGRESSION:
        return True
    return LIFECYCLE_PROGRESSION.index(proposed) > LIFECYCLE_PROGRESSION.index(current)


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

    def _objects_metadata(self) -> dict[str, dict]:
        payload = self._request("GET", "/metadata/objects", params={"limit": 1000})
        return {
            record.get("nameSingular"): record
            for record in payload.get("data", [])
            if record.get("nameSingular")
        }

    # -- interface ---------------------------------------------------------------

    def ensure_schema(self) -> dict:
        objects = self._objects_metadata()
        created: list[str] = []
        existing: list[str] = []
        for object_name, specs in (
            ("opportunity", OPPORTUNITY_CUSTOM_FIELDS),
            ("person", PERSON_CUSTOM_FIELDS),
        ):
            record = objects.get(object_name)
            if record is None:
                raise RuntimeError(f"Twenty metadata object {object_name!r} not found")
            names = {field.get("name") for field in record.get("fields", [])}
            for field in specs:
                if field["name"] in names:
                    existing.append(field["name"])
                    continue
                body = deepcopy(field)
                body["objectMetadataId"] = record["id"]
                self._request("POST", "/metadata/fields", json=body)
                created.append(field["name"])
        return {"created": created, "existing": existing}

    def find_contact(self, person: dict) -> dict | None:
        # Read-only dedup for the review UI (gh #15). Never creates. Errors are
        # swallowed and logged so a Twenty outage degrades gracefully — the
        # review UI still renders, just without the "already in CRM" badge.
        try:
            email = (person.get("email") or "").lower()
            safe_email = _filter_safe(email)
            if safe_email:
                record = self._find_one("people", f"emails.primaryEmail[eq]:{safe_email}")
                if record:
                    return self._twenty_person_dict(record)
            first, _, last = (person.get("name") or "").partition(" ")
            safe_first, safe_last = _filter_safe(first), _filter_safe(last)
            if safe_first and safe_last:
                record = self._find_one(
                    "people",
                    f"and(name.firstName[eq]:{safe_first},name.lastName[eq]:{safe_last})",
                )
                if record:
                    return self._twenty_person_dict(record)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.info("twenty find_contact skipped: %s", type(exc).__name__)
        return None

    def find_company(self, company: dict) -> dict | None:
        try:
            domain = _filter_safe(company.get("domain"))
            if domain:
                record = self._find_one(
                    "companies", f"domainName.primaryLinkUrl[eq]:https://{domain}"
                )
                if record:
                    return self._twenty_company_dict(record)
            safe_name = _filter_safe(company.get("name"))
            if safe_name:
                record = self._find_one("companies", f"name[eq]:{safe_name}")
                if record:
                    return self._twenty_company_dict(record)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.info("twenty find_company skipped: %s", type(exc).__name__)
        return None

    def _twenty_person_dict(self, record: dict) -> dict:
        name_obj = record.get("name") or {}
        emails_obj = record.get("emails") or {}
        result = {
            "crm_id": str(record["id"]),
            "url": None,
            "name": f"{name_obj.get('firstName', '')} {name_obj.get('lastName', '')}".strip(),
            "email": emails_obj.get("primaryEmail"),
            "company_name": (record.get("company") or {}).get("name"),
        }
        # GTM Person custom fields (gtm-crm-architecture.md §4), as canonical
        # Twenty option values so a read/write round-trip is value-stable.
        # A field Twenty has UNSET is omitted entirely rather than reported as
        # None/[] — the write path treats a present key as "write this", so
        # emitting unset fields would turn a round-trip into a clearing write.
        if record.get("wedge"):
            result["wedge"] = list(record["wedge"])
        if record.get("wedgePrimary"):
            result["wedge_primary"] = record["wedgePrimary"]
        if record.get("source"):
            result["source"] = record["source"]
        if record.get("lifecycleStage"):
            result["lifecycle_stage"] = record["lifecycleStage"]
        return result

    def _twenty_company_dict(self, record: dict) -> dict:
        domain_obj = record.get("domainName") or {}
        return {
            "crm_id": str(record["id"]),
            "url": None,
            "name": record.get("name"),
            "domain": domain_obj.get("primaryLinkUrl"),
        }

    def find_or_create_contact(self, person: dict) -> CRMRef:
        # Validate the GTM custom fields FIRST: an unknown select value must
        # fail before any lookup or write, so a bad value can never leave a
        # half-written person behind.
        custom_fields = person_custom_field_body(person)
        email = (person.get("email") or "").lower()
        safe_email = _filter_safe(email)
        if safe_email:
            existing = self._find_one("people", f"emails.primaryEmail[eq]:{safe_email}")
            if existing:
                return self._update_person_custom_fields(existing, custom_fields)
        first, _, last = person["name"].partition(" ")
        safe_first, safe_last = _filter_safe(first), _filter_safe(last)
        if safe_first and safe_last:
            existing = self._find_one(
                "people",
                f"and(name.firstName[eq]:{safe_first},name.lastName[eq]:{safe_last})",
            )
            if existing:
                # The first+last-name match is a dedup HEURISTIC, not an
                # identity: two different "John Smith" rows are ordinary. It is
                # safe to reuse the ref (worst case we attach a note to the
                # wrong twin, which a human can see and move) but NOT to write
                # GTM fields, which would silently overwrite the other twin's
                # wedge / source / lifecycle stage. Email is the only match
                # strong enough to write on.
                if custom_fields:
                    logger.info(
                        "twenty person GTM write skipped: matched by name heuristic, "
                        "not email — refusing to overwrite fields on a possible namesake"
                    )
                return self._ref("person", existing)
        body: dict = {"name": {"firstName": first, "lastName": last}}
        if email:
            body["emails"] = {"primaryEmail": email}
        if person.get("title"):
            body["jobTitle"] = person["title"]
        if person.get("company_crm_id"):
            body["companyId"] = person["company_crm_id"]
        # Records only reach the Twenty adapter after the local review UI
        # approved them; without an explicit APPROVED tag the schema
        # default ('PENDING') would put every synced record back in the
        # pending-review queue on the Home dashboard.
        body[REVIEW_STATUS_FIELD_NAME] = REVIEW_STATUS_VALUES["approved"]
        body.update(custom_fields)
        return self._ref("person", self._create("people", "person", body))

    def _update_person_custom_fields(self, existing: dict, custom_fields: dict) -> CRMRef:
        """PATCH only the GTM custom fields the caller supplied. Fields the
        caller omitted are never sent, so a manual edit in Twenty survives a
        re-sync — same rule the opportunity PATCH path applies to reviewStatus.

        `lifecycleStage` gets the same protection through §4's ordered
        transitions: only a forward move (or a move into Lost / Nurture, which
        §4 allows from any stage) is written. A regression, a no-op rewrite of
        the current stage, or an auto-revival out of Lost / Nurture is dropped
        and logged, so a repeated sync can never walk a human's manual edit
        backwards.
        """
        body = dict(custom_fields)
        current = self._current_person_state(existing, body)
        proposed = body.get("lifecycleStage")
        if proposed is not None:
            current_stage = current.get("lifecycleStage")
            if not lifecycle_is_forward(current_stage, proposed):
                logger.info(
                    "twenty lifecycleStage write skipped for person %s: %s -> %s is not a "
                    "forward transition (gtm-crm-architecture.md §4)",
                    existing["id"],
                    current_stage,
                    proposed,
                )
                body.pop("lifecycleStage")
        if "wedge" in body:
            # wedge is MULTI_SELECT and a PATCH REPLACES the whole array, so a
            # plain write would silently drop a tag a human added in Twenty.
            # Merge instead: server tags first (order preserved), then anything
            # new. Additive-only matches base.py's contract — removing a wedge
            # tag is a human action in the Twenty UI, never a sync side effect.
            server_tags = list(current.get("wedge") or [])
            preserved = [value for value in server_tags if value not in body["wedge"]]
            merged: dict[str, None] = {}
            for value in server_tags + list(body["wedge"]):
                merged.setdefault(value, None)
            if preserved:
                logger.info(
                    "twenty wedge merged for person %s: %d server tag(s) preserved",
                    existing["id"],
                    len(preserved),
                )
            body["wedge"] = list(merged)
            if body["wedge"] == server_tags:
                body.pop("wedge")  # nothing new to add
        if body:
            self._request("PATCH", f"/people/{existing['id']}", json=body)
        return self._ref("person", existing)

    def _current_person_state(self, existing: dict, body: dict) -> dict:
        """Twenty's current values for the guarded fields. A record read through
        `_find_one` usually carries them; a bare {"id": ...} (the
        update_contact_gtm_fields path) needs one extra read-only lookup — the
        guards must never run blind. Only fetches when a guarded field is being
        written and the record doesn't already carry it."""
        guarded = [name for name in ("lifecycleStage", "wedge") if name in body]
        if not guarded or all(name in existing for name in guarded):
            return existing
        return self._get_person(existing["id"]) or existing

    def _get_person(self, person_id: str) -> dict | None:
        """GET /rest/people/{id}. Envelope is {"data": {"person": {...}}} —
        verified read-only against the running Twenty on the mini (2026-09-03),
        same singular-key shape the create envelope uses."""
        payload = self._request("GET", f"/people/{person_id}")
        return payload.get("data", {}).get("person")

    def update_contact_gtm_fields(self, ref: CRMRef, person: dict) -> CRMRef:
        """Write the four GTM Person custom fields onto an already-known
        person. Validates before writing; keys the caller omitted are left
        untouched. Raises when the payload carries none of the four, rather
        than reporting success for a call that wrote nothing."""
        if ref.object_type != "person":
            raise ValueError(
                f"update_contact_gtm_fields expects a person ref, got {ref.object_type!r}"
            )
        if not has_person_gtm_fields(person):
            raise ValueError(
                "update_contact_gtm_fields called with none of the GTM Person keys "
                f"({', '.join(sorted(PERSON_GTM_KEYS))}); nothing would be written."
            )
        return self._update_person_custom_fields(
            {"id": ref.crm_id}, person_custom_field_body(person)
        )

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
        # See find_or_create_contact — tag as APPROVED so post-review
        # syncs don't reappear in the pending queue.
        body[REVIEW_STATUS_FIELD_NAME] = REVIEW_STATUS_VALUES["approved"]
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
            # PATCH path deliberately does NOT overwrite reviewStatus —
            # any manual change made in Twenty (e.g. James marking a real
            # opportunity as REJECTED) must survive a re-sync.
            self._request("PATCH", f"/opportunities/{existing['id']}", json=body)
            return self._ref("opportunity", existing)
        body[REVIEW_STATUS_FIELD_NAME] = REVIEW_STATUS_VALUES["approved"]
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
        # Twenty has no first-class tag object on core records. Modelling tags
        # as a custom multi-select field is a Phase 2 decision (see gh #14).
        # Raise instead of silently swallowing so a future caller learns the
        # method is unimplemented at write time, not by wondering why a tag
        # never showed up in the CRM.
        raise NotImplementedError(
            f"TwentyCRMAdapter.tag_record is not implemented — Twenty has no "
            f"native tags on {ref.object_type}. Track gh #14 for the custom-"
            f"multi-select-field decision. Attempted tags: {sorted(tags)}"
        )

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
