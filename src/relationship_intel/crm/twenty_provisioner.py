"""Twenty schema provisioner — Phase 1 of the review-in-Twenty consolidation.

Ensures Twenty has the metadata surface we need to fold the review queue
and weekly plan into its own UI, WITHOUT modifying Twenty source code:

- `reviewStatus` SELECT field (pending/approved/rejected/obsidian_only)
  on Person, Company, Opportunity.
- `weeklyPlan` custom object with weekStart / owner / body fields.
- Per-object Kanban view named "Review queue" grouped on reviewStatus so
  James triages by dragging cards.
- `reviewStatus IS_NOT pending` filter on the default TABLE view of
  Person / Company / Opportunity so unreviewed extractions stay out of
  the CRM's normal search / reports until approved.

All operations are idempotent — re-running is a no-op. Only uses
Twenty's public metadata REST API (see recon findings 1-4 in the
plan doc). Never modifies Twenty source.
"""

from __future__ import annotations

import logging
from copy import deepcopy

import httpx

from relationship_intel.errors import NotConfiguredError

logger = logging.getLogger(__name__)


# --- Constants exported so callers / tests can reference the same vocabulary
# without duplicating string literals ------------------------------------------

REVIEW_STATUS_FIELD_NAME = "reviewStatus"
REVIEW_STATUS_VALUES = {
    "pending": "PENDING",
    "approved": "APPROVED",
    "rejected": "REJECTED",
    "obsidian_only": "OBSIDIAN_ONLY",
}
REVIEW_STATUS_TARGET_OBJECTS = ("person", "company", "opportunity")
WEEKLY_PLAN_OBJECT_NAME = "weeklyPlan"
KANBAN_VIEW_NAME = "Review queue"


# --- Field / object specs ------------------------------------------------------

_REVIEW_STATUS_OPTIONS = [
    ("Pending review", "PENDING", "gray"),
    ("Approved", "APPROVED", "green"),
    ("Rejected", "REJECTED", "red"),
    ("Vault only", "OBSIDIAN_ONLY", "blue"),
]


def _select_options(values: list[tuple[str, str, str]]) -> list[dict]:
    return [
        {"label": label, "value": value, "color": color, "position": index}
        for index, (label, value, color) in enumerate(values)
    ]


_REVIEW_STATUS_FIELD_SPEC = {
    "name": REVIEW_STATUS_FIELD_NAME,
    "label": "Review status",
    "description": (
        "Relationship-intel review gate — pending items await the operator's "
        "approval before they surface in default Twenty views."
    ),
    "type": "SELECT",
    "isNullable": True,
    "defaultValue": "'PENDING'",
    "options": _select_options(_REVIEW_STATUS_OPTIONS),
}

_WEEKLY_PLAN_OBJECT_SPEC = {
    "nameSingular": WEEKLY_PLAN_OBJECT_NAME,
    "namePlural": "weeklyPlans",
    "labelSingular": "Weekly plan",
    "labelPlural": "Weekly plans",
    "description": "Relationship-intel weekly succession follow-up plan.",
    "icon": "IconCalendar",
    "isCustom": True,
    "isActive": True,
}

_WEEKLY_PLAN_FIELDS = [
    {
        "name": "weekStart",
        "label": "Week start",
        "description": "Monday of the plan's ISO week.",
        "type": "DATE",
        "isNullable": True,
    },
    {
        "name": "owner",
        "label": "Owner",
        "description": "Whose plan this is (e.g. James).",
        "type": "TEXT",
        "isNullable": True,
    },
    {
        "name": "body",
        "label": "Plan body",
        "description": "Rendered plan body (Markdown).",
        "type": "RICH_TEXT",
        "isNullable": True,
    },
]


class TwentyProvisioner:
    """Idempotent Twenty metadata provisioner. Construct with the same
    api_url / api_key you use for the runtime adapter."""

    def __init__(
        self,
        api_url: str,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
    ):
        if not api_key:
            raise NotConfiguredError(
                "TWENTY_API_KEY is not set. Provisioning requires an API key "
                "with the DATA_MODEL settings permission — see "
                "docs/twenty-setup.md."
            )
        self.base_url = api_url.rstrip("/") + "/rest"
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30,
            transport=transport,
        )

    # --- request plumbing -----------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> dict:
        logger.info("twenty-provisioner %s %s", method, path)  # never log payloads
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    def _all_objects(self) -> list[dict]:
        payload = self._request("GET", "/metadata/objects", params={"limit": 1000})
        return payload.get("data", [])

    def _object_by_name(self, name_singular: str) -> dict | None:
        for record in self._all_objects():
            if record.get("nameSingular") == name_singular:
                return record
        return None

    def _views_for_object(self, object_metadata_id: str) -> list[dict]:
        payload = self._request(
            "GET",
            "/metadata/views",
            params={"objectMetadataId": object_metadata_id},
        )
        # Twenty's REST view endpoint returns a bare list, not a {data:…}
        # envelope (see view.controller.ts findMany return type).
        return payload if isinstance(payload, list) else payload.get("data", [])

    def _filters_for_view(self, view_id: str) -> list[dict]:
        payload = self._request("GET", "/metadata/viewFilters", params={"viewId": view_id})
        return payload if isinstance(payload, list) else payload.get("data", [])

    # --- individual ensure-* steps -------------------------------------------

    def ensure_review_status_field(self, object_name: str) -> dict:
        """Add reviewStatus SELECT to the named standard object if missing."""
        obj = self._object_by_name(object_name)
        if not obj:
            raise RuntimeError(f"Twenty object {object_name!r} not found")
        existing_fields = {f.get("name") for f in obj.get("fields", [])}
        if REVIEW_STATUS_FIELD_NAME in existing_fields:
            return {"object": object_name, "field": REVIEW_STATUS_FIELD_NAME, "action": "existing"}
        body = deepcopy(_REVIEW_STATUS_FIELD_SPEC)
        body["objectMetadataId"] = obj["id"]
        self._request("POST", "/metadata/fields", json=body)
        return {"object": object_name, "field": REVIEW_STATUS_FIELD_NAME, "action": "created"}

    def ensure_weekly_plan_object(self) -> dict:
        """Create the WeeklyPlan custom object + its fields if missing."""
        obj = self._object_by_name(WEEKLY_PLAN_OBJECT_NAME)
        actions: dict = {
            "object": WEEKLY_PLAN_OBJECT_NAME,
            "object_action": "existing",
            "fields": [],
        }
        if not obj:
            self._request("POST", "/metadata/objects", json=_WEEKLY_PLAN_OBJECT_SPEC)
            obj = self._object_by_name(WEEKLY_PLAN_OBJECT_NAME)
            if not obj:
                raise RuntimeError("weeklyPlan creation succeeded but the object is not queryable")
            actions["object_action"] = "created"
        existing_fields = {f.get("name") for f in obj.get("fields", [])}
        for spec in _WEEKLY_PLAN_FIELDS:
            if spec["name"] in existing_fields:
                actions["fields"].append({"field": spec["name"], "action": "existing"})
                continue
            body = deepcopy(spec)
            body["objectMetadataId"] = obj["id"]
            self._request("POST", "/metadata/fields", json=body)
            actions["fields"].append({"field": spec["name"], "action": "created"})
        return actions

    def ensure_kanban_view(self, object_name: str) -> dict:
        """Ensure a Kanban view named "Review queue" exists on the given
        object, grouped on reviewStatus. Skips if a view with the same name
        already exists (no shape re-check — the user may have tweaked it)."""
        obj = self._object_by_name(object_name)
        if not obj:
            raise RuntimeError(f"Twenty object {object_name!r} not found")
        fields_by_name = {f.get("name"): f for f in obj.get("fields", [])}
        review_field = fields_by_name.get(REVIEW_STATUS_FIELD_NAME)
        if not review_field:
            raise RuntimeError(
                f"reviewStatus field is missing on {object_name}; run "
                "ensure_review_status_field first."
            )
        for view in self._views_for_object(obj["id"]):
            if view.get("name") == KANBAN_VIEW_NAME and view.get("type") == "KANBAN":
                return {"object": object_name, "view": KANBAN_VIEW_NAME, "action": "existing"}
        body = {
            "name": KANBAN_VIEW_NAME,
            "objectMetadataId": obj["id"],
            "type": "KANBAN",
            # Twenty's CreateViewInput calls this `mainGroupByFieldMetadataId`
            # for Kanban and Calendar alike (view-tools.factory.ts and
            # create-view.input.ts confirm — it must point at a SELECT field).
            "mainGroupByFieldMetadataId": review_field["id"],
            # `icon` is required by CreateViewInput even though it defaults
            # sensibly in Twenty's own UI-driven creation path.
            "icon": "IconLayoutKanban",
        }
        self._request("POST", "/metadata/views", json=body)
        return {"object": object_name, "view": KANBAN_VIEW_NAME, "action": "created"}

    def ensure_pending_filter_on_default_view(self, object_name: str) -> dict:
        """Add `reviewStatus != PENDING` to the object's default TABLE view
        so unreviewed extractions stay hidden from search / reports until
        James approves them."""
        obj = self._object_by_name(object_name)
        if not obj:
            raise RuntimeError(f"Twenty object {object_name!r} not found")
        fields_by_name = {f.get("name"): f for f in obj.get("fields", [])}
        review_field = fields_by_name.get(REVIEW_STATUS_FIELD_NAME)
        if not review_field:
            raise RuntimeError(
                f"reviewStatus field is missing on {object_name}; run "
                "ensure_review_status_field first."
            )
        # The default TABLE view is the first one created and is the only
        # one whose name matches the object's plural label (Twenty seeds
        # "All <objects>" as the default). We accept any TABLE view whose
        # `key` is DEFAULT if present — falls back to first TABLE view.
        default_view: dict | None = None
        for view in self._views_for_object(obj["id"]):
            if view.get("type") != "TABLE":
                continue
            if view.get("key") == "INDEX":
                default_view = view
                break
            if default_view is None:
                default_view = view
        if not default_view:
            return {
                "object": object_name,
                "filter": REVIEW_STATUS_FIELD_NAME,
                "action": "no_default_view",
            }
        for existing in self._filters_for_view(default_view["id"]):
            if existing.get("fieldMetadataId") == review_field["id"]:
                return {
                    "object": object_name,
                    "filter": REVIEW_STATUS_FIELD_NAME,
                    "action": "existing",
                }
        body = {
            "viewId": default_view["id"],
            "fieldMetadataId": review_field["id"],
            # Operand values are uppercase-with-underscores in the Twenty
            # ViewFilterOperand enum (twenty-shared/src/types/ViewFilterOperand.ts).
            "operand": "IS_NOT",
            "value": REVIEW_STATUS_VALUES["pending"],
        }
        self._request("POST", "/metadata/viewFilters", json=body)
        return {"object": object_name, "filter": REVIEW_STATUS_FIELD_NAME, "action": "created"}

    # --- top-level entry point -----------------------------------------------

    def provision_all(self) -> dict:
        """Run every Phase 1 step in the safe order: fields must exist
        before views can reference them; views must exist before their
        filters."""
        results: dict = {
            "review_status_fields": [],
            "weekly_plan": None,
            "kanban_views": [],
            "default_view_filters": [],
        }
        for object_name in REVIEW_STATUS_TARGET_OBJECTS:
            results["review_status_fields"].append(self.ensure_review_status_field(object_name))
        results["weekly_plan"] = self.ensure_weekly_plan_object()
        for object_name in REVIEW_STATUS_TARGET_OBJECTS:
            results["kanban_views"].append(self.ensure_kanban_view(object_name))
            results["default_view_filters"].append(
                self.ensure_pending_filter_on_default_view(object_name)
            )
        return results
