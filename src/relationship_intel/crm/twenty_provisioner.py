"""Twenty schema provisioner — Phase 1.5 of the review-in-Twenty consolidation.

Ensures Twenty has the metadata surface James needs to triage the pipeline's
review queue AND read the current weekly plan from Twenty's own UI, WITHOUT
modifying Twenty source code:

- `reviewStatus` SELECT field (pending/approved/rejected/obsidian_only) on
  Person, Company, Opportunity. (Phase 1's only durable output.)
- A single "Home" dashboard, pinned to sidebar position 0, containing:
    * a RECORD_TABLE widget backed by a "Pending review" View on Person
      (filter: reviewStatus IS PENDING),
    * a STANDALONE_RICH_TEXT widget carrying the current weekly plan.
- Opt-in cleanup that removes Phase 1's dead artifacts (weeklyPlan custom
  object, its manually-published record, three "Review queue" Kanban views).

All ensure_* operations are idempotent — re-running is a no-op. Only uses
Twenty's public metadata REST API. Never modifies Twenty source.
"""

from __future__ import annotations

import json
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

# Phase 1 dead-artifact names — retained so cleanup and tests share vocabulary.
WEEKLY_PLAN_OBJECT_NAME = "weeklyPlan"
KANBAN_VIEW_NAME = "Review queue"
# The manually-published WeeklyPlan record from Phase 1 sits at a fixed uuid
# (see RESUME.md); cleanup best-efforts a DELETE for it.
LEGACY_WEEKLY_PLAN_RECORD_ID = "06ea9cbf-23c9-44d5-8327-6c7a8d3ca63d"

# Phase 1.5 vocabulary.
PENDING_PERSON_VIEW_NAME = "Pending review"
HOME_DASHBOARD_NAME = "Home"
HOME_DASHBOARD_ICON = "IconLayoutDashboard"
IFRAME_WIDGET_TITLE = "Pending review"
RICH_TEXT_WIDGET_TITLE = "Weekly plan"
# The local review UI (served by `smcrm review-ui`). Embedded inside the
# Home dashboard as an IFRAME widget so James reviews candidates in
# Twenty's chrome without polluting Twenty's People/Companies/Opportunities
# with unapproved extraction data — the local UI only pushes to Twenty on
# explicit approval.
# Use 127.0.0.1 explicitly — Twenty's CreatePageLayoutWidgetInput uses
# class-validator's `@IsUrl()`, which requires a TLD by default and
# rejects `http://localhost:8765` outright.
DEFAULT_REVIEW_UI_URL = "http://127.0.0.1:8765"


# --- Field spec ---------------------------------------------------------------

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


DEFAULT_RICH_TEXT_BODY = (
    "# Weekly plan\n\n"
    "The pipeline will render this widget's contents each Monday. "
    "Until then, run `smcrm weekly-plan` to populate it.\n"
)


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
        self.metadata_graphql_url = api_url.rstrip("/") + "/metadata"
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

    def _metadata_graphql(self, query: str, variables: dict | None = None) -> dict:
        """POST a GraphQL query/mutation to the metadata GraphQL endpoint
        (/metadata). Twenty exposes some metadata surfaces — most notably
        navigationMenuItems — via GraphQL only, not via /rest."""
        logger.info("twenty-provisioner GRAPHQL /metadata")
        response = self.client.post(
            self.metadata_graphql_url,
            json={"query": query, "variables": variables or {}},
        )
        response.raise_for_status()
        payload = response.json() if response.content else {}
        if payload.get("errors"):
            raise RuntimeError(
                "twenty metadata GraphQL error: "
                + "; ".join(err.get("message", "?") for err in payload["errors"])
            )
        return payload.get("data", {})

    def _request_tolerant(
        self, method: str, path: str, *, tolerate: tuple[int, ...] = (404,), **kwargs
    ) -> tuple[int, dict]:
        """Same as _request but returns (status_code, body) and swallows the
        given HTTP codes instead of raising. Used by cleanup, where a 404 on
        DELETE means "already gone, that's the goal"."""
        logger.info("twenty-provisioner %s %s", method, path)
        response = self.client.request(method, path, **kwargs)
        if response.status_code in tolerate:
            return response.status_code, {}
        response.raise_for_status()
        body = response.json() if response.content else {}
        return response.status_code, body

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

    def _view_fields_for_view(self, view_id: str) -> list[dict]:
        payload = self._request("GET", "/metadata/viewFields", params={"viewId": view_id})
        return payload if isinstance(payload, list) else payload.get("data", [])

    def _list_page_layouts(self) -> list[dict]:
        payload = self._request("GET", "/metadata/pageLayouts", params={"limit": 1000})
        return payload if isinstance(payload, list) else payload.get("data", [])

    def _list_page_layout_tabs(self, page_layout_id: str) -> list[dict]:
        payload = self._request(
            "GET",
            "/metadata/pageLayoutTabs",
            params={"pageLayoutId": page_layout_id},
        )
        return payload if isinstance(payload, list) else payload.get("data", [])

    def _list_page_layout_widgets(self, page_layout_tab_id: str) -> list[dict]:
        payload = self._request(
            "GET",
            "/metadata/pageLayoutWidgets",
            params={"pageLayoutTabId": page_layout_tab_id},
        )
        return payload if isinstance(payload, list) else payload.get("data", [])

    def _list_navigation_menu_items(self) -> list[dict]:
        # NavigationMenuItem is exposed via the metadata GraphQL endpoint
        # only (no /rest controller). See navigation-menu-item.resolver.ts.
        data = self._metadata_graphql(
            "query { navigationMenuItems { id name type pageLayoutId position icon } }"
        )
        return data.get("navigationMenuItems", [])

    def _create_navigation_menu_item(self, input_obj: dict) -> dict:
        data = self._metadata_graphql(
            """
            mutation Create($input: CreateNavigationMenuItemInput!) {
              createNavigationMenuItem(input: $input) {
                id name type pageLayoutId position icon
              }
            }
            """,
            variables={"input": input_obj},
        )
        return data.get("createNavigationMenuItem", {})

    def _list_dashboards(self) -> list[dict]:
        payload = self._request("GET", "/dashboards", params={"limit": 1000})
        if isinstance(payload, list):
            return payload
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("dashboards", [])
        return []

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

    def ensure_pending_person_view(self) -> dict:
        """Ensure a TABLE view "Pending review" exists on Person, with an
        `IS PENDING` viewFilter on `reviewStatus`. Returns view id + action.

        `IS PENDING` is intentionally NULL-unsafe here — the intent is
        exactly "pending records only", so records with reviewStatus = NULL
        (legacy rows never touched by the pipeline) SHOULD be hidden."""
        person = self._object_by_name("person")
        if not person:
            raise RuntimeError("Twenty object 'person' not found")
        fields_by_name = {f.get("name"): f for f in person.get("fields", [])}
        review_field = fields_by_name.get(REVIEW_STATUS_FIELD_NAME)
        if not review_field:
            raise RuntimeError(
                "reviewStatus field is missing on person; run ensure_review_status_field first."
            )

        # RECORD_TABLE dashboard widgets require the backing view to be
        # ViewType.TABLE_WIDGET, NOT plain TABLE. A regular TABLE view will
        # render as "Invalid Configuration" inside the widget (see
        # RecordTableWidgetViewDraftInitEffect + useViewById on the front).
        # If a prior run created it as TABLE, delete it so we can rebuild.
        existing_view: dict | None = None
        for view in self._views_for_object(person["id"]):
            if view.get("name") != PENDING_PERSON_VIEW_NAME:
                continue
            if view.get("type") == "TABLE_WIDGET":
                existing_view = view
                break
            # Wrong-typed leftover — DELETE and let the create path rebuild.
            self._request_tolerant("DELETE", f"/metadata/views/{view['id']}")

        if existing_view is None:
            body = {
                "name": PENDING_PERSON_VIEW_NAME,
                "objectMetadataId": person["id"],
                "type": "TABLE_WIDGET",
                # CreateViewInput requires an icon — any Tabler name works.
                "icon": "IconClipboardCheck",
            }
            created = self._request("POST", "/metadata/views", json=body)
            view_id = _extract_id(created) or _refetch_view_id(
                self, person["id"], PENDING_PERSON_VIEW_NAME
            )
            view_action = "created"
        else:
            view_id = existing_view["id"]
            view_action = "existing"

        # Ensure the IS PENDING filter is on the view.
        filter_action = "existing"
        already_filtered = any(
            f.get("fieldMetadataId") == review_field["id"] for f in self._filters_for_view(view_id)
        )
        if not already_filtered:
            self._request(
                "POST",
                "/metadata/viewFilters",
                json={
                    "viewId": view_id,
                    "fieldMetadataId": review_field["id"],
                    "operand": "IS",
                    # SELECT viewFilters store `value` as a JSON-encoded
                    # ARRAY of option strings (see
                    # turnRecordFilterIntoGqlOperationFilter.ts's SELECT
                    # branch — it calls
                    # arrayOfStringsOrVariablesSchema.parse on the value).
                    # A raw "PENDING" string trips JSON.parse and the
                    # RECORD_TABLE widget renders "Invalid Configuration".
                    "value": json.dumps([REVIEW_STATUS_VALUES["pending"]]),
                },
            )
            filter_action = "created"

        return {
            "object": "person",
            "view": PENDING_PERSON_VIEW_NAME,
            "view_id": view_id,
            "view_action": view_action,
            "filter_action": filter_action,
        }

    def ensure_visible_view_fields(self, view_id: str) -> dict:
        """Twenty auto-creates a viewField row per column on TABLE views,
        but fields added AFTER the object was seeded (like our reviewStatus)
        land with `isVisible: false`. PATCH any hidden ones to true so the
        column actually appears."""
        patched: list[str] = []
        for vf in self._view_fields_for_view(view_id):
            if not vf.get("isVisible", True):
                self._request(
                    "PATCH",
                    f"/metadata/viewFields/{vf['id']}",
                    json={"isVisible": True},
                )
                patched.append(vf["id"])
        return {"view_id": view_id, "patched_view_field_ids": patched}

    # Column order in the pending-review Person view. Names must match
    # field.name on Person (see the Twenty person entity). We keep it short
    # so the widget fits half a dashboard tab without horizontal scroll.
    PENDING_REVIEW_COLUMNS = ("name", "company", "jobTitle", "emails", REVIEW_STATUS_FIELD_NAME)

    def ensure_pending_review_view_columns(self, view_id: str, person: dict) -> dict:
        """Create viewField rows on the pending-review view for name,
        company, jobTitle, emails, reviewStatus (in that order).

        Twenty does NOT auto-create viewFields for custom TABLE views —
        without this the widget renders as an empty box even when the
        underlying filter matches rows."""
        fields_by_name = {f.get("name"): f for f in person.get("fields", [])}
        existing_by_field = {
            vf.get("fieldMetadataId"): vf for vf in self._view_fields_for_view(view_id)
        }
        actions: list[dict] = []
        for position, name in enumerate(self.PENDING_REVIEW_COLUMNS):
            field = fields_by_name.get(name)
            if not field:
                actions.append({"field": name, "action": "not_found_on_person"})
                continue
            existing = existing_by_field.get(field["id"])
            if existing is not None:
                if not existing.get("isVisible", True):
                    self._request(
                        "PATCH",
                        f"/metadata/viewFields/{existing['id']}",
                        json={"isVisible": True, "position": position},
                    )
                    actions.append({"field": name, "action": "unhidden"})
                else:
                    actions.append({"field": name, "action": "existing"})
                continue
            self._request(
                "POST",
                "/metadata/viewFields",
                json={
                    "viewId": view_id,
                    "fieldMetadataId": field["id"],
                    "isVisible": True,
                    "position": position,
                    "size": 180,
                },
            )
            actions.append({"field": name, "action": "created"})
        return {"view_id": view_id, "columns": actions}

    def ensure_home_dashboard(
        self,
        name: str = HOME_DASHBOARD_NAME,
        *,
        rich_text_body: str | None = None,
        review_ui_url: str = DEFAULT_REVIEW_UI_URL,
    ) -> dict:
        """Ensure the single-dashboard shape exists:

        1. PageLayout (type=DASHBOARD, name=name).
        2. PageLayoutTab (title=name, position=0, layoutMode=GRID).
        3. RECORD_TABLE widget over the pending-review Person view.
        4. STANDALONE_RICH_TEXT widget carrying `rich_text_body` (or a
           placeholder if None — Phase 2's weekly-plan command overwrites it).
        5. Dashboard record via /rest/dashboards, pinned position=0.
        6. NavigationMenuItem (type=PAGE_LAYOUT) at position=0 — this is
           what makes the dashboard the sidebar-clicked-logo landing page
           (see useDefaultHomePagePath.ts).

        Every step is idempotent (GET-list, skip if a matching row exists).
        """
        # -- 1. PageLayout --------------------------------------------------
        layout: dict | None = None
        for candidate in self._list_page_layouts():
            if candidate.get("name") == name and candidate.get("type") == "DASHBOARD":
                layout = candidate
                break
        if layout is None:
            created = self._request(
                "POST",
                "/metadata/pageLayouts",
                json={"name": name, "type": "DASHBOARD"},
            )
            layout_id = _extract_id(created) or _find_by(
                self._list_page_layouts(), name=name, type="DASHBOARD"
            )
            layout = {"id": layout_id, "name": name, "type": "DASHBOARD"}
            layout_action = "created"
        else:
            layout_id = layout["id"]
            layout_action = "existing"

        # Both widgets get their own tab (each full-width) so James can
        # focus on one at a time. Simultaneous side-by-side isn't useful:
        # review is a "sit down and grind through candidates" activity;
        # the weekly plan is read-once-a-week reference.
        person = self._object_by_name("person")
        if not person:
            raise RuntimeError("Twenty object 'person' not found")

        # -- Migration path: drop any single-tab / mis-titled leftover ---
        # Prior provisioner versions created a single tab (titled "Home")
        # holding both widgets side-by-side. If we detect that shape,
        # delete the widgets on it so we can rebuild fresh as two tabs.
        # We DON'T delete the tab itself when its position is 0 — we just
        # re-title it below, keeping the id (Twenty enforces one tab at
        # each position and juggling deletes is racy).
        existing_tabs = sorted(
            self._list_page_layout_tabs(layout_id),
            key=lambda t: t.get("position", 0),
        )
        for old_tab in existing_tabs:
            widgets_here = self._list_page_layout_widgets(old_tab["id"])
            if len(widgets_here) >= 2 or (
                old_tab.get("title") == name and old_tab.get("position") == 0
            ):
                for w in widgets_here:
                    self._request_tolerant("DELETE", f"/metadata/pageLayoutWidgets/{w['id']}")

        # -- Clean up the now-unused Pending review TABLE_WIDGET view -----
        for view in self._views_for_object(person["id"]):
            if view.get("name") == PENDING_PERSON_VIEW_NAME and view.get("type") == "TABLE_WIDGET":
                self._request_tolerant("DELETE", f"/metadata/views/{view['id']}")
                break

        # -- Tab 1: Pending review ---------------------------------------
        pending_tab_id, pending_tab_action = self._ensure_tab(
            layout_id, title=IFRAME_WIDGET_TITLE, position=0
        )
        record_action = self._ensure_iframe_widget(pending_tab_id, person, review_ui_url)

        # -- Tab 2: Weekly plan ------------------------------------------
        plan_tab_id, plan_tab_action = self._ensure_tab(
            layout_id, title=RICH_TEXT_WIDGET_TITLE, position=1
        )
        body_markdown = rich_text_body if rich_text_body is not None else DEFAULT_RICH_TEXT_BODY
        rich_action = self._ensure_rich_text_widget(
            plan_tab_id, person, body_markdown, force_update=rich_text_body is not None
        )

        tab_id = pending_tab_id  # keep for return-value continuity
        tab_action = pending_tab_action
        _ = plan_tab_action  # tracked separately; primary tab id is returned

        # -- 5. Dashboard record -------------------------------------------
        dashboard: dict | None = None
        for candidate in self._list_dashboards():
            if candidate.get("title") == name:
                dashboard = candidate
                break
        if dashboard is None:
            self._request(
                "POST",
                "/dashboards",
                json={"title": name, "pageLayoutId": layout_id, "position": 0},
            )
            dashboard_action = "created"
        else:
            dashboard_action = "existing"

        # -- 6. Navigation menu item ---------------------------------------
        # Skipped. Twenty's validator (validate-navigation-menu-item-
        # page-layout-reference-cross-entity.util.ts) rejects PAGE_LAYOUT
        # nav items that reference a DASHBOARD page layout — they may
        # only point at STANDALONE_PAGE layouts. The RESUME.md recon
        # was wrong on this piece. The Dashboard record itself is what
        # surfaces the dashboard in Twenty's sidebar (under "Dashboards"),
        # so a nav-item entry isn't required.
        nav_action = "skipped_not_supported"

        return {
            "name": name,
            "page_layout": {"id": layout_id, "action": layout_action},
            "tab": {"id": tab_id, "action": tab_action},
            "record_table_widget": {"action": record_action, "url": review_ui_url},
            "rich_text_widget": {"action": rich_action},
            "dashboard": {"action": dashboard_action},
            "navigation_menu_item": {"action": nav_action},
        }

    # --- home-dashboard helpers ----------------------------------------------

    def _ensure_tab(self, layout_id: str, *, title: str, position: int) -> tuple[str, str]:
        """Get or create a PageLayoutTab at the given position. If the tab
        exists but its title differs, PATCH it to match. Returns (tab id,
        action). GRID layout — matches the existing widget grid positions.
        """
        for candidate in self._list_page_layout_tabs(layout_id):
            if candidate.get("position") == position:
                if candidate.get("title") != title:
                    self._request(
                        "PATCH",
                        f"/metadata/pageLayoutTabs/{candidate['id']}",
                        json={"title": title},
                    )
                    return candidate["id"], "updated"
                return candidate["id"], "existing"
        created = self._request(
            "POST",
            "/metadata/pageLayoutTabs",
            json={
                "title": title,
                "position": position,
                "pageLayoutId": layout_id,
                "layoutMode": "GRID",
            },
        )
        tab_id = _extract_id(created)
        if not tab_id:
            tab_id = _find_by(self._list_page_layout_tabs(layout_id), position=position)
        return tab_id, "created"

    def _ensure_iframe_widget(self, tab_id: str, person: dict, review_ui_url: str) -> str:
        """Ensure the pending-review IFRAME widget is on the given tab,
        full-width. Migrates existing RECORD_TABLE-typed leftovers by
        deleting them (widget `type` is top-level and can't be PATCHed)."""
        widgets = self._list_page_layout_widgets(tab_id)
        iframe_widget = next(
            (w for w in widgets if w.get("title") == IFRAME_WIDGET_TITLE),
            None,
        )
        if iframe_widget is not None and iframe_widget.get("type") != "IFRAME":
            self._request_tolerant("DELETE", f"/metadata/pageLayoutWidgets/{iframe_widget['id']}")
            iframe_widget = None
        if iframe_widget is None:
            self._request(
                "POST",
                "/metadata/pageLayoutWidgets",
                json={
                    "pageLayoutTabId": tab_id,
                    "title": IFRAME_WIDGET_TITLE,
                    "type": "IFRAME",
                    # objectMetadataId is required by CreatePageLayoutWidgetInput
                    # even though IFRAME widgets aren't object-scoped.
                    "objectMetadataId": person["id"],
                    # Full width — this is the only widget on its tab now.
                    "gridPosition": {"row": 0, "column": 0, "rowSpan": 12, "columnSpan": 12},
                    "configuration": {
                        "configurationType": "IFRAME",
                        "url": review_ui_url,
                    },
                },
            )
            return "created"
        current_url = (iframe_widget.get("configuration") or {}).get("url")
        current_type = (iframe_widget.get("configuration") or {}).get("configurationType")
        if current_url != review_ui_url or current_type != "IFRAME":
            self._request(
                "PATCH",
                f"/metadata/pageLayoutWidgets/{iframe_widget['id']}",
                json={
                    "configuration": {
                        "configurationType": "IFRAME",
                        "url": review_ui_url,
                    }
                },
            )
            return "updated"
        return "existing"

    def _ensure_rich_text_widget(
        self, tab_id: str, person: dict, body_markdown: str, *, force_update: bool
    ) -> str:
        """Ensure the weekly-plan STANDALONE_RICH_TEXT widget is on the
        given tab, full-width. When `force_update` is True (caller passed
        an explicit body), PATCH the body on existing widgets so Monday's
        weekly-plan run can refresh the markdown in place."""
        widgets = self._list_page_layout_widgets(tab_id)
        rich_widget = next(
            (w for w in widgets if w.get("title") == RICH_TEXT_WIDGET_TITLE),
            None,
        )
        if rich_widget is None:
            self._request(
                "POST",
                "/metadata/pageLayoutWidgets",
                json={
                    "pageLayoutTabId": tab_id,
                    "title": RICH_TEXT_WIDGET_TITLE,
                    "type": "STANDALONE_RICH_TEXT",
                    "objectMetadataId": person["id"],
                    "gridPosition": {"row": 0, "column": 0, "rowSpan": 12, "columnSpan": 12},
                    "configuration": {
                        "configurationType": "STANDALONE_RICH_TEXT",
                        "body": {"markdown": body_markdown},
                    },
                },
            )
            return "created"
        if force_update:
            self._request(
                "PATCH",
                f"/metadata/pageLayoutWidgets/{rich_widget['id']}",
                json={
                    "configuration": {
                        "configurationType": "STANDALONE_RICH_TEXT",
                        "body": {"markdown": body_markdown},
                    }
                },
            )
            return "updated"
        return "existing"

    # --- destructive cleanup --------------------------------------------------

    def cleanup_phase1_artifacts(self) -> dict:
        """Opt-in destructive cleanup for Phase 1's dead pieces. Reports per
        step (`existing`+`deleted` / `not_found`) so the caller can print a
        useful summary."""
        report: dict = {
            "legacy_weekly_plan_record": None,
            "weekly_plan_object": None,
            "kanban_views": [],
        }

        # 1. The manually-published WeeklyPlan record (best-effort; if the
        #    parent object is already gone the 404 is expected).
        status, _ = self._request_tolerant("DELETE", f"/weeklyPlans/{LEGACY_WEEKLY_PLAN_RECORD_ID}")
        report["legacy_weekly_plan_record"] = {
            "id": LEGACY_WEEKLY_PLAN_RECORD_ID,
            "action": "not_found" if status == 404 else "deleted",
        }

        # 2. The custom object itself.
        weekly_plan_obj = self._object_by_name(WEEKLY_PLAN_OBJECT_NAME)
        if weekly_plan_obj is None:
            report["weekly_plan_object"] = {"action": "not_found"}
        else:
            status, _ = self._request_tolerant(
                "DELETE", f"/metadata/objects/{weekly_plan_obj['id']}"
            )
            report["weekly_plan_object"] = {
                "id": weekly_plan_obj["id"],
                "action": "not_found" if status == 404 else "deleted",
            }

        # 3. "Review queue" Kanban views on Person / Company / Opportunity.
        for object_name in REVIEW_STATUS_TARGET_OBJECTS:
            obj = self._object_by_name(object_name)
            entry: dict = {"object": object_name}
            if not obj:
                entry["action"] = "not_found"
                report["kanban_views"].append(entry)
                continue
            hit: dict | None = None
            for view in self._views_for_object(obj["id"]):
                if view.get("name") == KANBAN_VIEW_NAME and view.get("type") == "KANBAN":
                    hit = view
                    break
            if hit is None:
                entry["action"] = "not_found"
            else:
                status, _ = self._request_tolerant("DELETE", f"/metadata/views/{hit['id']}")
                entry["id"] = hit["id"]
                entry["action"] = "not_found" if status == 404 else "deleted"
            report["kanban_views"].append(entry)

        return report

    # --- backfill ------------------------------------------------------------

    _BACKFILL_PLURALS = {
        "person": "people",
        "company": "companies",
        "opportunity": "opportunities",
    }

    def backfill_pending_to_approved(self) -> dict:
        """Flip every existing People/Companies/Opportunities record whose
        `reviewStatus` is PENDING to APPROVED.

        Rationale: when Phase 1 added the SELECT field it declared
        `defaultValue: 'PENDING'`, so every record that existed BEFORE
        the field was created got PENDING at read time. Those records
        were never candidates in the extraction review queue — they're
        stale pre-Phase-1 syncs — and they need to move out of PENDING
        so the queue only reflects actual review work.

        Uses the RESTful workspace endpoints (`/people`, `/companies`,
        `/opportunities`) — NOT the metadata REST — since we're mutating
        record data, not schema."""
        report: dict = {"objects": []}
        pending_value = REVIEW_STATUS_VALUES["pending"]
        approved_value = REVIEW_STATUS_VALUES["approved"]
        for object_name in REVIEW_STATUS_TARGET_OBJECTS:
            plural = self._BACKFILL_PLURALS[object_name]
            patched = 0
            skipped = 0
            errors: list[str] = []
            # Paginate through workspace records. Twenty's REST records
            # endpoint envelope is {data: {<plural>: [...]}}.
            cursor: str | None = None
            while True:
                params: dict = {"limit": 60}
                if cursor:
                    params["starting_after"] = cursor
                payload = self._request("GET", f"/{plural}", params=params)
                data = payload.get("data", {})
                items = data.get(plural, []) if isinstance(data, dict) else []
                if not items:
                    break
                for record in items:
                    status = record.get(REVIEW_STATUS_FIELD_NAME)
                    if status != pending_value:
                        skipped += 1
                        continue
                    try:
                        self._request(
                            "PATCH",
                            f"/{plural}/{record['id']}",
                            json={REVIEW_STATUS_FIELD_NAME: approved_value},
                        )
                        patched += 1
                    except httpx.HTTPStatusError as exc:
                        errors.append(f"{record.get('id')}: {exc.response.status_code}")
                if len(items) < 60:
                    break
                cursor = items[-1].get("id")
                if not cursor:
                    break
            report["objects"].append(
                {
                    "object": object_name,
                    "patched": patched,
                    "skipped": skipped,
                    "errors": errors,
                }
            )
        return report

    # --- top-level entry point -----------------------------------------------

    def provision_all(
        self,
        *,
        add_default_view_filter: bool = False,
        rich_text_body: str | None = None,
    ) -> dict:
        """Run every Phase 1.5 step in the safe order: fields must exist
        before views can reference them; views must exist before their
        widgets can point at them.

        `add_default_view_filter=False` by default because Twenty's
        `IS_NOT PENDING` operand is NULL-unsafe and hides legacy records on
        default views. Only pass True after a reviewStatus backfill has
        eliminated NULL rows, or after the filter has been reworked as a
        NULL-safe combinator.
        """
        results: dict = {
            "review_status_fields": [],
            "home_dashboard": None,
            "default_view_filters": [],
        }
        for object_name in REVIEW_STATUS_TARGET_OBJECTS:
            results["review_status_fields"].append(self.ensure_review_status_field(object_name))
        results["home_dashboard"] = self.ensure_home_dashboard(rich_text_body=rich_text_body)
        for object_name in REVIEW_STATUS_TARGET_OBJECTS:
            if add_default_view_filter:
                results["default_view_filters"].append(
                    self.ensure_pending_filter_on_default_view(object_name)
                )
            else:
                results["default_view_filters"].append(
                    {
                        "object": object_name,
                        "filter": REVIEW_STATUS_FIELD_NAME,
                        "action": "skipped_nullsafe",
                    }
                )
        return results

    # --- opt-in dangerous filter (kept from Phase 1) --------------------------

    def ensure_pending_filter_on_default_view(self, object_name: str) -> dict:
        """Add `reviewStatus IS_NOT PENDING` to the object's default TABLE
        view so unreviewed extractions stay hidden from search / reports
        until James approves them.

        DANGER — NULL semantics: Twenty's `IS_NOT` operand is standard SQL
        `!= 'PENDING'`, which is NULL-unsafe: existing records with
        `reviewStatus = NULL` (never touched by the pipeline) evaluate the
        comparison as NULL/unknown and are EXCLUDED from the view. Applied
        to a workspace that already has records, this filter hides them
        all and breaks the default People / Companies / Opportunities
        views. Skipped by default (`add_default_view_filter=False`)."""
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
            "operand": "IS_NOT",
            # See ensure_pending_person_view for why this is a JSON array.
            "value": json.dumps([REVIEW_STATUS_VALUES["pending"]]),
        }
        self._request("POST", "/metadata/viewFilters", json=body)
        return {"object": object_name, "filter": REVIEW_STATUS_FIELD_NAME, "action": "created"}


# --- helpers ------------------------------------------------------------------


def _extract_id(payload: dict) -> str | None:
    """Twenty's REST create responses are inconsistent — sometimes a bare
    record, sometimes `{data: {createFoo: {id}}}`. Try both."""
    if not isinstance(payload, dict):
        return None
    if "id" in payload:
        return payload["id"]
    data = payload.get("data")
    if isinstance(data, dict):
        if "id" in data:
            return data["id"]
        for value in data.values():
            if isinstance(value, dict) and "id" in value:
                return value["id"]
    return None


def _find_by(records: list[dict], **match) -> str | None:
    for r in records:
        if all(r.get(k) == v for k, v in match.items()):
            return r.get("id")
    return None


def _refetch_view_id(prov: TwentyProvisioner, object_id: str, name: str) -> str | None:
    for view in prov._views_for_object(object_id):
        if view.get("name") == name and view.get("type") == "TABLE_WIDGET":
            return view.get("id")
    return None
