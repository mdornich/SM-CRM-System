"""Idempotency + shape tests for the Twenty schema provisioner. Uses
httpx.MockTransport so the tests never touch a live Twenty."""

from __future__ import annotations

import json

import httpx
import pytest

from relationship_intel.crm.twenty_provisioner import (
    DEFAULT_REVIEW_UI_URL,
    HOME_DASHBOARD_NAME,
    IFRAME_WIDGET_TITLE,
    KANBAN_VIEW_NAME,
    LEGACY_WEEKLY_PLAN_RECORD_ID,
    PENDING_PERSON_VIEW_NAME,
    REVIEW_STATUS_FIELD_NAME,
    REVIEW_STATUS_TARGET_OBJECTS,
    RICH_TEXT_WIDGET_TITLE,
    WEEKLY_PLAN_OBJECT_NAME,
    TwentyProvisioner,
)
from relationship_intel.errors import NotConfiguredError

KEY = "test-jwt-key"


def _provisioner(handler) -> TwentyProvisioner:
    return TwentyProvisioner("http://localhost:3002", KEY, transport=httpx.MockTransport(handler))


class _State:
    """In-memory stand-in for a Twenty workspace so tests can drive
    provisioning end-to-end without mocking each request individually.

    Models: objects (with fields), views (per object), view filters,
    view fields, page layouts + tabs + widgets, navigation menu items,
    dashboards, and the legacy weeklyPlan record."""

    def __init__(
        self,
        *,
        include_weekly_plan_object: bool = False,
        include_legacy_kanban_views: bool = False,
        include_legacy_weekly_plan_record: bool = False,
    ):
        self._next_id = 1
        # Seed the three standard objects the review-status field targets.
        self.objects: list[dict] = [
            self._seed_object("person", "people"),
            self._seed_object("company", "companies"),
            self._seed_object("opportunity", "opportunities"),
        ]
        # views keyed by object id
        self.views: dict[str, list[dict]] = {
            obj["id"]: [
                {
                    "id": self._id(),
                    "name": obj["labelPlural"],
                    "type": "TABLE",
                    "key": "INDEX",
                    "objectMetadataId": obj["id"],
                }
            ]
            for obj in self.objects
        }
        # filters keyed by view id
        self.filters: dict[str, list[dict]] = {}
        # viewFields keyed by view id — Twenty auto-creates one per column
        self.view_fields: dict[str, list[dict]] = {}
        # dashboard-related state
        self.page_layouts: list[dict] = []
        self.page_layout_tabs: list[dict] = []
        self.page_layout_widgets: list[dict] = []
        self.navigation_menu_items: list[dict] = []
        self.dashboards: list[dict] = []
        # legacy weeklyPlan record — a bare record id we honor on DELETE
        self.weekly_plan_records: set[str] = set()

        if include_weekly_plan_object:
            self._seed_and_track_object(WEEKLY_PLAN_OBJECT_NAME, "weeklyPlans")
        if include_legacy_weekly_plan_record:
            self.weekly_plan_records.add(LEGACY_WEEKLY_PLAN_RECORD_ID)
        if include_legacy_kanban_views:
            # Simulate the shape Phase 1 left behind: a KANBAN view named
            # "Review queue" on each target object.
            for obj in self.objects:
                if obj["nameSingular"] in REVIEW_STATUS_TARGET_OBJECTS:
                    self.views[obj["id"]].append(
                        {
                            "id": self._id(),
                            "name": KANBAN_VIEW_NAME,
                            "type": "KANBAN",
                            "objectMetadataId": obj["id"],
                        }
                    )

        self.request_log: list[tuple[str, str]] = []

    # -- helpers --------------------------------------------------------------

    def _id(self) -> str:
        val = f"id-{self._next_id}"
        self._next_id += 1
        return val

    def _seed_object(self, name_singular: str, name_plural: str) -> dict:
        return {
            "id": self._id(),
            "nameSingular": name_singular,
            "namePlural": name_plural,
            "labelSingular": name_singular.capitalize(),
            "labelPlural": name_plural.capitalize(),
            "fields": [],
        }

    def _seed_and_track_object(self, name_singular: str, name_plural: str) -> dict:
        obj = self._seed_object(name_singular, name_plural)
        self.objects.append(obj)
        self.views[obj["id"]] = [
            {
                "id": self._id(),
                "name": obj["labelPlural"],
                "type": "TABLE",
                "key": "INDEX",
                "objectMetadataId": obj["id"],
            }
        ]
        return obj

    def object_by_singular(self, name: str) -> dict | None:
        for obj in self.objects:
            if obj["nameSingular"] == name:
                return obj
        return None

    # -- mutators exercised by the mock handler ------------------------------

    def add_field(self, object_id: str, spec: dict) -> dict:
        for obj in self.objects:
            if obj["id"] == object_id:
                field = {"id": self._id(), **spec}
                obj["fields"].append(field)
                return field
        raise KeyError(object_id)

    def add_object(self, spec: dict) -> dict:
        return self._seed_and_track_object(spec["nameSingular"], spec["namePlural"])

    def add_view(self, spec: dict) -> dict:
        view = {"id": self._id(), **spec}
        self.views.setdefault(spec["objectMetadataId"], []).append(view)
        # Fields added AFTER the object was seeded land with isVisible=false
        # on any freshly-created TABLE view — that's exactly the gotcha
        # ensure_visible_view_fields exists to fix.
        if spec.get("type") in ("TABLE", "TABLE_WIDGET"):
            obj = next((o for o in self.objects if o["id"] == spec["objectMetadataId"]), None)
            if obj:
                for f in obj["fields"]:
                    self.view_fields.setdefault(view["id"], []).append(
                        {
                            "id": self._id(),
                            "viewId": view["id"],
                            "fieldMetadataId": f["id"],
                            "isVisible": False,
                        }
                    )
        return view

    def add_filter(self, spec: dict) -> dict:
        view_filter = {"id": self._id(), **spec}
        self.filters.setdefault(spec["viewId"], []).append(view_filter)
        return view_filter

    def patch_view_field(self, vf_id: str, patch: dict) -> dict | None:
        for rows in self.view_fields.values():
            for row in rows:
                if row["id"] == vf_id:
                    row.update(patch)
                    return row
        return None

    def add_page_layout(self, spec: dict) -> dict:
        layout = {"id": self._id(), **spec}
        self.page_layouts.append(layout)
        return layout

    def add_page_layout_tab(self, spec: dict) -> dict:
        tab = {"id": self._id(), **spec}
        self.page_layout_tabs.append(tab)
        return tab

    def add_page_layout_widget(self, spec: dict) -> dict:
        widget = {"id": self._id(), **spec}
        self.page_layout_widgets.append(widget)
        return widget

    def add_navigation_menu_item(self, spec: dict) -> dict:
        item = {"id": self._id(), **spec}
        self.navigation_menu_items.append(item)
        return item

    def add_dashboard(self, spec: dict) -> dict:
        dashboard = {"id": self._id(), **spec}
        self.dashboards.append(dashboard)
        return dashboard

    def delete_object(self, object_id: str) -> bool:
        for i, obj in enumerate(self.objects):
            if obj["id"] == object_id:
                del self.objects[i]
                self.views.pop(object_id, None)
                return True
        return False

    def delete_view(self, view_id: str) -> bool:
        for rows in self.views.values():
            for i, view in enumerate(rows):
                if view["id"] == view_id:
                    del rows[i]
                    self.filters.pop(view_id, None)
                    self.view_fields.pop(view_id, None)
                    return True
        return False

    # -- handler --------------------------------------------------------------

    def handler(self):
        def _handler(request: httpx.Request) -> httpx.Response:
            self.request_log.append((request.method, request.url.path))
            path = request.url.path
            method = request.method

            # -- metadata GraphQL (used for navigationMenuItems only) -----
            # Route both queries and mutations through POST /metadata, but
            # log them with a synthetic path so the write-count assertion
            # can still tell a mutation (write) from a query (read).
            if method == "POST" and path == "/metadata":
                body = json.loads(request.content)
                query = body.get("query", "")
                if "createNavigationMenuItem" in query:
                    # Overwrite the naive log entry with a mutation-tagged one
                    self.request_log[-1] = ("POST", "/metadata#createNavigationMenuItem")
                    input_obj = (body.get("variables") or {}).get("input", {})
                    created = self.add_navigation_menu_item(input_obj)
                    return httpx.Response(200, json={"data": {"createNavigationMenuItem": created}})
                if "navigationMenuItems" in query:
                    self.request_log[-1] = ("GET", "/metadata#navigationMenuItems")
                    return httpx.Response(
                        200, json={"data": {"navigationMenuItems": self.navigation_menu_items}}
                    )
                return httpx.Response(
                    200,
                    json={"errors": [{"message": f"unhandled graphql: {query[:60]}"}]},
                )

            # -- metadata reads ------------------------------------------
            if method == "GET" and path == "/rest/metadata/objects":
                return httpx.Response(200, json={"data": self.objects})
            if method == "GET" and path == "/rest/metadata/views":
                object_id = request.url.params.get("objectMetadataId")
                return httpx.Response(200, json=self.views.get(object_id, []))
            if method == "GET" and path == "/rest/metadata/viewFilters":
                view_id = request.url.params.get("viewId")
                return httpx.Response(200, json=self.filters.get(view_id, []))
            if method == "GET" and path == "/rest/metadata/viewFields":
                view_id = request.url.params.get("viewId")
                return httpx.Response(200, json=self.view_fields.get(view_id, []))
            if method == "GET" and path == "/rest/metadata/pageLayouts":
                return httpx.Response(200, json=self.page_layouts)
            if method == "GET" and path == "/rest/metadata/pageLayoutTabs":
                pl_id = request.url.params.get("pageLayoutId")
                return httpx.Response(
                    200, json=[t for t in self.page_layout_tabs if t.get("pageLayoutId") == pl_id]
                )
            if method == "GET" and path == "/rest/metadata/pageLayoutWidgets":
                tab_id = request.url.params.get("pageLayoutTabId")
                return httpx.Response(
                    200,
                    json=[
                        w for w in self.page_layout_widgets if w.get("pageLayoutTabId") == tab_id
                    ],
                )
            if method == "GET" and path == "/rest/dashboards":
                return httpx.Response(200, json=self.dashboards)

            # -- metadata writes -----------------------------------------
            if method == "POST" and path == "/rest/metadata/fields":
                body = json.loads(request.content)
                created = self.add_field(body["objectMetadataId"], body)
                return httpx.Response(201, json={"id": created["id"]})
            if method == "POST" and path == "/rest/metadata/objects":
                body = json.loads(request.content)
                created = self.add_object(body)
                return httpx.Response(201, json={"id": created["id"]})
            if method == "POST" and path == "/rest/metadata/views":
                body = json.loads(request.content)
                created = self.add_view(body)
                return httpx.Response(201, json={"id": created["id"]})
            if method == "POST" and path == "/rest/metadata/viewFilters":
                body = json.loads(request.content)
                self.add_filter(body)
                return httpx.Response(201, json={})
            if method == "POST" and path == "/rest/metadata/pageLayouts":
                body = json.loads(request.content)
                created = self.add_page_layout(body)
                return httpx.Response(201, json={"id": created["id"]})
            if method == "POST" and path == "/rest/metadata/pageLayoutTabs":
                body = json.loads(request.content)
                created = self.add_page_layout_tab(body)
                return httpx.Response(201, json={"id": created["id"]})
            if method == "POST" and path == "/rest/metadata/pageLayoutWidgets":
                body = json.loads(request.content)
                created = self.add_page_layout_widget(body)
                return httpx.Response(201, json={"id": created["id"]})
            if method == "POST" and path == "/rest/dashboards":
                body = json.loads(request.content)
                created = self.add_dashboard(body)
                return httpx.Response(201, json={"id": created["id"]})

            # -- patch -----------------------------------------------------
            if method == "PATCH" and path.startswith("/rest/metadata/viewFields/"):
                vf_id = path.rsplit("/", 1)[-1]
                patch = json.loads(request.content)
                updated = self.patch_view_field(vf_id, patch)
                if updated is None:
                    return httpx.Response(404, json={"error": "viewField not found"})
                return httpx.Response(200, json=updated)
            if method == "PATCH" and path.startswith("/rest/metadata/pageLayoutTabs/"):
                tid = path.rsplit("/", 1)[-1]
                patch = json.loads(request.content)
                for t in self.page_layout_tabs:
                    if t["id"] == tid:
                        t.update(patch)
                        return httpx.Response(200, json=t)
                return httpx.Response(404, json={"error": "tab not found"})
            if method == "PATCH" and path.startswith("/rest/metadata/pageLayoutWidgets/"):
                wid = path.rsplit("/", 1)[-1]
                patch = json.loads(request.content)
                for w in self.page_layout_widgets:
                    if w["id"] == wid:
                        w.update(patch)
                        return httpx.Response(200, json=w)
                return httpx.Response(404, json={"error": "widget not found"})

            # -- deletes ---------------------------------------------------
            if method == "DELETE" and path.startswith("/rest/metadata/pageLayoutWidgets/"):
                wid = path.rsplit("/", 1)[-1]
                for i, w in enumerate(self.page_layout_widgets):
                    if w["id"] == wid:
                        del self.page_layout_widgets[i]
                        return httpx.Response(200, json={})
                return httpx.Response(404, json={"error": "widget not found"})
            if method == "DELETE" and path.startswith("/rest/weeklyPlans/"):
                record_id = path.rsplit("/", 1)[-1]
                if record_id in self.weekly_plan_records:
                    self.weekly_plan_records.discard(record_id)
                    return httpx.Response(200, json={})
                return httpx.Response(404, json={"error": "weeklyPlan not found"})
            if method == "DELETE" and path.startswith("/rest/metadata/objects/"):
                object_id = path.rsplit("/", 1)[-1]
                if self.delete_object(object_id):
                    return httpx.Response(200, json={})
                return httpx.Response(404, json={"error": "object not found"})
            if method == "DELETE" and path.startswith("/rest/metadata/views/"):
                view_id = path.rsplit("/", 1)[-1]
                if self.delete_view(view_id):
                    return httpx.Response(200, json={})
                return httpx.Response(404, json={"error": "view not found"})

            return httpx.Response(404, json={"error": f"unhandled {method} {path}"})

        return _handler


# --- tests -------------------------------------------------------------------


def test_missing_api_key_raises_before_any_request():
    with pytest.raises(NotConfiguredError):
        TwentyProvisioner("http://localhost:3002", "")


def test_provision_all_from_empty_workspace_creates_everything():
    state = _State()
    result = _provisioner(state.handler()).provision_all()

    # Every target object got the reviewStatus SELECT field.
    assert [e["object"] for e in result["review_status_fields"]] == list(
        REVIEW_STATUS_TARGET_OBJECTS
    )
    assert all(e["action"] == "created" for e in result["review_status_fields"])
    for object_name in REVIEW_STATUS_TARGET_OBJECTS:
        obj = state.object_by_singular(object_name)
        names = {f.get("name") for f in obj["fields"]}
        assert REVIEW_STATUS_FIELD_NAME in names

    # Phase 1's dead artifacts must NOT be provisioned by default.
    assert state.object_by_singular(WEEKLY_PLAN_OBJECT_NAME) is None
    for object_name in REVIEW_STATUS_TARGET_OBJECTS:
        obj = state.object_by_singular(object_name)
        kanbans = [v for v in state.views[obj["id"]] if v.get("type") == "KANBAN"]
        assert kanbans == []

    # Home dashboard was created with all six pieces.
    hd = result["home_dashboard"]
    assert hd["name"] == HOME_DASHBOARD_NAME
    assert hd["page_layout"]["action"] == "created"
    assert hd["tab"]["action"] == "created"
    assert hd["record_table_widget"]["action"] == "created"
    assert hd["rich_text_widget"]["action"] == "created"
    assert hd["dashboard"]["action"] == "created"
    # PAGE_LAYOUT nav items can only reference STANDALONE_PAGE layouts,
    # not DASHBOARDs — see ensure_home_dashboard for the reasoning. The
    # Dashboard record alone is enough to surface the dashboard in the
    # sidebar.
    assert hd["navigation_menu_item"]["action"] == "skipped_not_supported"

    # PageLayout exists as DASHBOARD.
    layout = next(pl for pl in state.page_layouts if pl["name"] == HOME_DASHBOARD_NAME)
    assert layout["type"] == "DASHBOARD"

    # Two tabs, each holding a single full-width widget. Simultaneous
    # side-by-side isn't useful — review is grind-through-candidates
    # work; the plan is read-once-a-week reference.
    tabs = sorted(
        [t for t in state.page_layout_tabs if t["pageLayoutId"] == layout["id"]],
        key=lambda t: t["position"],
    )
    assert [t["title"] for t in tabs] == [IFRAME_WIDGET_TITLE, RICH_TEXT_WIDGET_TITLE]
    assert all(t["layoutMode"] == "GRID" for t in tabs)

    pending_widgets = [
        w for w in state.page_layout_widgets if w["pageLayoutTabId"] == tabs[0]["id"]
    ]
    assert len(pending_widgets) == 1
    iframe_widget = pending_widgets[0]
    assert iframe_widget["type"] == "IFRAME"
    assert iframe_widget["configuration"]["configurationType"] == "IFRAME"
    assert iframe_widget["configuration"]["url"] == DEFAULT_REVIEW_UI_URL
    # Full-width — no adjacent widget to leave space for.
    assert iframe_widget["gridPosition"]["columnSpan"] == 12

    plan_widgets = [w for w in state.page_layout_widgets if w["pageLayoutTabId"] == tabs[1]["id"]]
    assert len(plan_widgets) == 1
    rich_widget = plan_widgets[0]
    assert rich_widget["type"] == "STANDALONE_RICH_TEXT"
    assert "markdown" in rich_widget["configuration"]["body"]
    assert rich_widget["gridPosition"]["columnSpan"] == 12

    # No nav-menu item is expected — Twenty rejects PAGE_LAYOUT items
    # pointing at DASHBOARD layouts. The Dashboard record alone is what
    # surfaces the dashboard in the sidebar.
    assert state.navigation_menu_items == []

    # Dashboard record was published.
    assert any(d["title"] == HOME_DASHBOARD_NAME for d in state.dashboards)

    # Default TABLE views are NOT filtered by default — the IS_NOT PENDING
    # operand is NULL-unsafe and would hide every legacy record.
    for object_name, filter_result in zip(
        REVIEW_STATUS_TARGET_OBJECTS, result["default_view_filters"], strict=True
    ):
        assert filter_result["object"] == object_name
        assert filter_result["action"] == "skipped_nullsafe"


def test_provision_all_does_not_create_pending_person_view():
    """The pending-review Person view is obsolete — the IFRAME widget
    embeds the local review UI instead. Provision should not leave a
    Pending review view behind."""
    state = _State()
    _provisioner(state.handler()).provision_all()

    person = state.object_by_singular("person")
    matching = [v for v in state.views[person["id"]] if v["name"] == PENDING_PERSON_VIEW_NAME]
    assert matching == []


def test_provision_all_opt_in_filter_creates_it():
    """The dangerous default-view filter is behind an opt-in flag; when
    passed explicitly it fires the POST /viewFilters call."""
    state = _State()
    result = _provisioner(state.handler()).provision_all(add_default_view_filter=True)
    for filter_result in result["default_view_filters"]:
        assert filter_result["action"] == "created"


def test_provision_all_is_idempotent():
    """Second run must not attempt any additional writes."""
    state = _State()
    prov = _provisioner(state.handler())
    prov.provision_all()

    first_writes = [(m, p) for m, p in state.request_log if m in ("POST", "PATCH", "DELETE")]
    assert first_writes  # sanity — first run did do writes
    state.request_log.clear()

    second = prov.provision_all()

    assert [(m, p) for m, p in state.request_log if m in ("POST", "PATCH", "DELETE")] == []
    assert all(e["action"] == "existing" for e in second["review_status_fields"])
    hd = second["home_dashboard"]
    for piece in (
        "page_layout",
        "tab",
        "record_table_widget",
        "rich_text_widget",
        "dashboard",
    ):
        assert hd[piece]["action"] == "existing", piece
    assert hd["navigation_menu_item"]["action"] == "skipped_not_supported"
    assert all(v["action"] == "skipped_nullsafe" for v in second["default_view_filters"])


def test_home_dashboard_is_idempotent():
    """Calling ensure_home_dashboard twice writes only on the first call."""
    state = _State()
    prov = _provisioner(state.handler())
    # Fields have to exist first so the pending-review view can be built.
    for obj in REVIEW_STATUS_TARGET_OBJECTS:
        prov.ensure_review_status_field(obj)

    first = prov.ensure_home_dashboard()
    assert first["page_layout"]["action"] == "created"

    state.request_log.clear()
    second = prov.ensure_home_dashboard()
    writes = [(m, p) for m, p in state.request_log if m in ("POST", "PATCH", "DELETE")]
    assert writes == []
    for piece in (
        "page_layout",
        "tab",
        "record_table_widget",
        "rich_text_widget",
        "dashboard",
    ):
        assert second[piece]["action"] == "existing"
    assert second["navigation_menu_item"]["action"] == "skipped_not_supported"


def test_cleanup_phase1_artifacts_deletes_dead_pieces():
    """State with the weeklyPlan object, its legacy record, and three
    kanban views → cleanup issues four DELETEs and reports them all."""
    state = _State(
        include_weekly_plan_object=True,
        include_legacy_kanban_views=True,
        include_legacy_weekly_plan_record=True,
    )
    weekly_plan_obj_id = state.object_by_singular(WEEKLY_PLAN_OBJECT_NAME)["id"]

    report = _provisioner(state.handler()).cleanup_phase1_artifacts()

    assert report["legacy_weekly_plan_record"]["action"] == "deleted"
    assert LEGACY_WEEKLY_PLAN_RECORD_ID not in state.weekly_plan_records

    assert report["weekly_plan_object"]["action"] == "deleted"
    assert state.object_by_singular(WEEKLY_PLAN_OBJECT_NAME) is None

    assert [e["object"] for e in report["kanban_views"]] == list(REVIEW_STATUS_TARGET_OBJECTS)
    assert all(e["action"] == "deleted" for e in report["kanban_views"])
    for object_name in REVIEW_STATUS_TARGET_OBJECTS:
        obj = state.object_by_singular(object_name)
        kanbans = [v for v in state.views[obj["id"]] if v.get("type") == "KANBAN"]
        assert kanbans == []

    # Sanity: we did fire the actual DELETE requests.
    deletes = [p for m, p in state.request_log if m == "DELETE"]
    assert any(f"/rest/weeklyPlans/{LEGACY_WEEKLY_PLAN_RECORD_ID}" in p for p in deletes)
    assert any(f"/rest/metadata/objects/{weekly_plan_obj_id}" in p for p in deletes)
    assert sum("/rest/metadata/views/" in p for p in deletes) == 3


def test_cleanup_is_tolerant_of_missing_artifacts():
    """Clean workspace → cleanup reports not_found for every step and
    raises no exception."""
    state = _State()
    report = _provisioner(state.handler()).cleanup_phase1_artifacts()
    assert report["legacy_weekly_plan_record"]["action"] == "not_found"
    assert report["weekly_plan_object"]["action"] == "not_found"
    assert [e["action"] for e in report["kanban_views"]] == ["not_found"] * len(
        REVIEW_STATUS_TARGET_OBJECTS
    )


def test_missing_target_object_raises():
    """If Twenty is missing one of Person/Company/Opportunity (e.g. an
    exotic workspace), we surface the mismatch loudly rather than
    silently skipping."""
    state = _State()
    state.objects = [obj for obj in state.objects if obj["nameSingular"] != "opportunity"]

    with pytest.raises(RuntimeError, match="opportunity"):
        _provisioner(state.handler()).provision_all()


def test_review_status_field_uses_declared_options():
    """The SELECT emits pending/approved/rejected/obsidian_only options
    with the enum-valued values the sync path also uses (locks the
    vocabulary against silent drift)."""
    from relationship_intel.crm import twenty_provisioner as tp

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        state = _State()
        if request.method == "POST" and request.url.path == "/rest/metadata/fields":
            captured["body"] = json.loads(request.content)
            return httpx.Response(201, json={"id": "new"})
        return state.handler()(request)

    _provisioner(handler).ensure_review_status_field("person")

    body = captured["body"]
    assert body["type"] == "SELECT"
    assert body["name"] == REVIEW_STATUS_FIELD_NAME
    values = [opt["value"] for opt in body["options"]]
    assert set(values) == set(tp.REVIEW_STATUS_VALUES.values())
