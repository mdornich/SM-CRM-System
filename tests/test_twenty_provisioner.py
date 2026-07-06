"""Idempotency + shape tests for the Twenty schema provisioner. Uses
httpx.MockTransport so the tests never touch a live Twenty."""

from __future__ import annotations

import json

import httpx
import pytest

from relationship_intel.crm.twenty_provisioner import (
    KANBAN_VIEW_NAME,
    REVIEW_STATUS_FIELD_NAME,
    REVIEW_STATUS_TARGET_OBJECTS,
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

    Only models the pieces the provisioner actually reads and writes:
    objects (with fields), views (per object), view filters (per view).
    """

    def __init__(self, *, include_weekly_plan: bool = False):
        self._next_id = 1
        # Seed the three standard objects the review-status field targets.
        self.objects: list[dict] = [
            self._seed_object("person", "people"),
            self._seed_object("company", "companies"),
            self._seed_object("opportunity", "opportunities"),
        ]
        if include_weekly_plan:
            self.objects.append(self._seed_object(WEEKLY_PLAN_OBJECT_NAME, "weeklyPlans"))
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
        self.request_log: list[tuple[str, str]] = []

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

    def object_by_singular(self, name: str) -> dict | None:
        for obj in self.objects:
            if obj["nameSingular"] == name:
                return obj
        return None

    def add_field(self, object_id: str, spec: dict) -> dict:
        for obj in self.objects:
            if obj["id"] == object_id:
                field = {"id": self._id(), **spec}
                obj["fields"].append(field)
                return field
        raise KeyError(object_id)

    def add_object(self, spec: dict) -> dict:
        obj = {
            "id": self._id(),
            "nameSingular": spec["nameSingular"],
            "namePlural": spec["namePlural"],
            "labelSingular": spec.get("labelSingular", spec["nameSingular"].capitalize()),
            "labelPlural": spec.get("labelPlural", spec["namePlural"].capitalize()),
            "fields": [],
        }
        self.objects.append(obj)
        # Twenty auto-creates the default TABLE view on custom object creation.
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

    def add_view(self, spec: dict) -> dict:
        view = {"id": self._id(), **spec}
        self.views.setdefault(spec["objectMetadataId"], []).append(view)
        return view

    def add_filter(self, spec: dict) -> dict:
        view_filter = {"id": self._id(), **spec}
        self.filters.setdefault(spec["viewId"], []).append(view_filter)
        return view_filter

    def handler(self):
        def _handler(request: httpx.Request) -> httpx.Response:
            self.request_log.append((request.method, request.url.path))
            path = request.url.path

            if request.method == "GET" and path == "/rest/metadata/objects":
                return httpx.Response(200, json={"data": self.objects})
            if request.method == "GET" and path == "/rest/metadata/views":
                object_id = request.url.params.get("objectMetadataId")
                return httpx.Response(200, json=self.views.get(object_id, []))
            if request.method == "GET" and path == "/rest/metadata/viewFilters":
                view_id = request.url.params.get("viewId")
                return httpx.Response(200, json=self.filters.get(view_id, []))
            if request.method == "POST" and path == "/rest/metadata/fields":
                body = json.loads(request.content)
                self.add_field(body["objectMetadataId"], body)
                return httpx.Response(201, json={"data": {"createField": {"id": "new"}}})
            if request.method == "POST" and path == "/rest/metadata/objects":
                body = json.loads(request.content)
                self.add_object(body)
                return httpx.Response(201, json={"data": {"createObject": {"id": "new"}}})
            if request.method == "POST" and path == "/rest/metadata/views":
                body = json.loads(request.content)
                self.add_view(body)
                return httpx.Response(201, json={})
            if request.method == "POST" and path == "/rest/metadata/viewFilters":
                body = json.loads(request.content)
                self.add_filter(body)
                return httpx.Response(201, json={})
            return httpx.Response(404, json={"error": f"unhandled {request.method} {path}"})

        return _handler


# --- tests -------------------------------------------------------------------


def test_missing_api_key_raises_before_any_request():
    with pytest.raises(NotConfiguredError):
        TwentyProvisioner("http://localhost:3002", "")


def test_provision_all_from_empty_workspace_creates_everything():
    state = _State()
    result = _provisioner(state.handler()).provision_all()

    # Every object got the reviewStatus SELECT field.
    assert [e["object"] for e in result["review_status_fields"]] == list(
        REVIEW_STATUS_TARGET_OBJECTS
    )
    assert all(e["action"] == "created" for e in result["review_status_fields"])
    for object_name in REVIEW_STATUS_TARGET_OBJECTS:
        obj = state.object_by_singular(object_name)
        names = {f.get("name") for f in obj["fields"]}
        assert REVIEW_STATUS_FIELD_NAME in names

    # Weekly plan object + all three fields materialized.
    assert result["weekly_plan"]["object_action"] == "created"
    assert [f["field"] for f in result["weekly_plan"]["fields"]] == [
        "weekStart",
        "owner",
        "body",
    ]
    assert all(f["action"] == "created" for f in result["weekly_plan"]["fields"])
    assert state.object_by_singular(WEEKLY_PLAN_OBJECT_NAME) is not None

    # Each target object got a Kanban view named "Review queue".
    for object_name, view_result in zip(
        REVIEW_STATUS_TARGET_OBJECTS, result["kanban_views"], strict=True
    ):
        assert view_result["object"] == object_name
        assert view_result["view"] == KANBAN_VIEW_NAME
        assert view_result["action"] == "created"
        obj = state.object_by_singular(object_name)
        kanban = [v for v in state.views[obj["id"]] if v.get("type") == "KANBAN"]
        assert len(kanban) == 1
        assert kanban[0]["mainGroupByFieldMetadataId"]  # grouped on the review field
        assert kanban[0]["icon"]  # Twenty's CreateViewInput requires it

    # Default TABLE view got the IS_NOT PENDING filter.
    for object_name, filter_result in zip(
        REVIEW_STATUS_TARGET_OBJECTS, result["default_view_filters"], strict=True
    ):
        assert filter_result["object"] == object_name
        assert filter_result["action"] == "created"


def test_provision_all_is_idempotent():
    """Second run must not attempt any additional writes."""
    state = _State()
    prov = _provisioner(state.handler())
    prov.provision_all()

    # Snapshot how many POSTs happened on the first run and reset the log.
    first_run_posts = [(m, p) for m, p in state.request_log if m == "POST"]
    assert first_run_posts  # sanity — first run did do writes
    state.request_log.clear()

    second = prov.provision_all()

    assert [(m, p) for m, p in state.request_log if m == "POST"] == []
    # Second run reports every step as 'existing'.
    assert all(e["action"] == "existing" for e in second["review_status_fields"])
    assert second["weekly_plan"]["object_action"] == "existing"
    assert all(f["action"] == "existing" for f in second["weekly_plan"]["fields"])
    assert all(v["action"] == "existing" for v in second["kanban_views"])
    assert all(v["action"] == "existing" for v in second["default_view_filters"])


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
            return httpx.Response(201, json={"data": {"createField": {"id": "new"}}})
        return state.handler()(request)

    _provisioner(handler).ensure_review_status_field("person")

    body = captured["body"]
    assert body["type"] == "SELECT"
    assert body["name"] == REVIEW_STATUS_FIELD_NAME
    values = [opt["value"] for opt in body["options"]]
    assert set(values) == set(tp.REVIEW_STATUS_VALUES.values())
