"""Twenty adapter unit tests over httpx.MockTransport — payload shapes match the
fork-verified composite structure; no key -> clean failure; secrets never logged.
(Live integration against the running fork is Phase 2.)"""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from relationship_intel.crm.base import CRMRef
from relationship_intel.crm.twenty_adapter import TwentyCRMAdapter
from relationship_intel.errors import NotConfiguredError

KEY = "secret-jwt-key-123"


def _adapter(handler) -> TwentyCRMAdapter:
    return TwentyCRMAdapter("http://localhost:3002", KEY, transport=httpx.MockTransport(handler))


def test_missing_api_key_raises_before_any_request():
    with pytest.raises(NotConfiguredError):
        TwentyCRMAdapter("http://localhost:3002", "")


def test_contact_lookup_uses_email_filter_then_creates_composite_payload():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"people": []}})
        return httpx.Response(201, json={"data": {"createPerson": {"id": "p-1"}}})

    ref = _adapter(handler).find_or_create_contact(
        {"name": "Bob Smith", "email": "bob@x.com", "title": "Owner"}
    )
    assert ref == CRMRef("twenty", "person", "p-1")
    assert calls[0].url.params["filter"] == "emails.primaryEmail[eq]:bob@x.com"
    body = json.loads(calls[-1].content)
    assert body["name"] == {"firstName": "Bob", "lastName": "Smith"}
    assert body["emails"] == {"primaryEmail": "bob@x.com"}
    assert body["jobTitle"] == "Owner"
    assert calls[0].headers["Authorization"] == f"Bearer {KEY}"


def test_single_token_contact_does_not_duplicate_last_name():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"people": []}})
        return httpx.Response(201, json={"data": {"createPerson": {"id": "p-1"}}})

    _adapter(handler).find_or_create_contact({"name": "Joe"})

    body = json.loads(calls[-1].content)
    assert body["name"] == {"firstName": "Joe", "lastName": ""}


def test_existing_contact_found_by_email_is_not_recreated():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json={"data": {"people": [{"id": "p-9"}]}})

    ref = _adapter(handler).find_or_create_contact({"name": "Bob Smith", "email": "bob@x.com"})
    assert ref.crm_id == "p-9"


def test_company_domain_filter_and_links_composite():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"companies": []}})
        return httpx.Response(201, json={"data": {"createCompany": {"id": "c-1"}}})

    _adapter(handler).find_or_create_company({"name": "Smith HVAC", "domain": "smithhvac.com"})
    assert calls[0].url.params["filter"] == "domainName.primaryLinkUrl[eq]:https://smithhvac.com"
    body = json.loads(calls[-1].content)
    assert body["domainName"] == {"primaryLinkUrl": "https://smithhvac.com"}


def test_ensure_schema_creates_missing_opportunity_custom_fields():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "object-opportunity",
                            "nameSingular": "opportunity",
                            "fields": [{"name": "leadType"}],
                        }
                    ],
                    "pageInfo": {},
                    "totalCount": 1,
                },
            )
        return httpx.Response(201, json={"id": "field-new"})

    result = _adapter(handler).ensure_schema()
    assert result == {
        "created": ["successionSignalScore", "timingWindow"],
        "existing": ["leadType"],
    }
    posts = [request for request in calls if request.method == "POST"]
    assert [json.loads(request.content)["name"] for request in posts] == [
        "successionSignalScore",
        "timingWindow",
    ]
    score_field = json.loads(posts[0].content)
    assert score_field["objectMetadataId"] == "object-opportunity"
    assert score_field["type"] == "NUMBER"
    assert score_field["settings"] == {"dataType": "int", "decimals": 0, "type": "number"}
    timing_field = json.loads(posts[1].content)
    assert timing_field["type"] == "SELECT"
    assert {option["value"] for option in timing_field["options"]} >= {"MONTHS_3_6", "UNKNOWN"}


def test_ensure_schema_noops_when_fields_exist():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "object-opportunity",
                        "nameSingular": "opportunity",
                        "fields": [
                            {"name": "successionSignalScore"},
                            {"name": "leadType"},
                            {"name": "timingWindow"},
                        ],
                    }
                ],
            },
        )

    result = _adapter(handler).ensure_schema()
    assert result == {
        "created": [],
        "existing": ["successionSignalScore", "leadType", "timingWindow"],
    }
    assert [request.method for request in calls] == ["GET"]


def test_opportunity_stage_mapping_and_unmapped_stage_rejected():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"opportunities": []}})
        return httpx.Response(201, json={"data": {"createOpportunity": {"id": "o-1"}}})

    adapter = _adapter(handler)
    adapter.create_or_update_opportunity(
        {
            "name": "Smith HVAC — Succession",
            "stage": "discovery",
            "lead_type": "warm",
            "succession_signal_score": 72,
            "timing_window": "3_6_months",
        }
    )
    body = json.loads(calls[-1].content)
    assert body["stage"] == "SCREENING"
    assert body["leadType"] == "WARM"
    assert body["successionSignalScore"] == 72
    assert body["timingWindow"] == "MONTHS_3_6"

    with pytest.raises(ValueError, match="not_fit"):
        adapter.create_or_update_opportunity({"name": "X", "stage": "not_fit"})


def test_note_uses_bodyv2_markdown_and_note_target_link():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"notes": []}})
        if request.url.path.endswith("/notes"):
            return httpx.Response(201, json={"data": {"createNote": {"id": "n-1"}}})
        return httpx.Response(201, json={"data": {"createNoteTarget": {"id": "nt-1"}}})

    from relationship_intel.crm.base import NotePayload

    _adapter(handler).attach_note(
        CRMRef("twenty", "person", "p-1"), NotePayload(title="T", body="summary text")
    )
    posts = [c for c in calls if c.method == "POST"]
    note_body = json.loads(posts[0].content)
    assert note_body["bodyV2"] == {"markdown": "summary text"}
    assert json.loads(posts[1].content) == {"noteId": "n-1", "targetPersonId": "p-1"}


def test_attach_note_retry_reuses_orphaned_note_and_links_it():
    """Create-then-link retry safety: an existing same-title (orphaned) note is
    reused, its body refreshed, and it is linked only because no target exists."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET" and request.url.path.endswith("/notes"):
            return httpx.Response(200, json={"data": {"notes": [{"id": "n-9"}]}})
        if request.method == "GET" and request.url.path.endswith("/noteTargets"):
            return httpx.Response(200, json={"data": {"noteTargets": []}})
        if request.method == "PATCH":
            return httpx.Response(200, json={"data": {"updateNote": {"id": "n-9"}}})
        return httpx.Response(201, json={"data": {"createNoteTarget": {"id": "nt-1"}}})

    from relationship_intel.crm.base import NotePayload

    ref = _adapter(handler).attach_note(
        CRMRef("twenty", "person", "p-1"), NotePayload(title="T", body="new body")
    )
    assert ref.crm_id == "n-9"
    methods = [(c.method, c.url.path) for c in calls]
    assert ("PATCH", "/rest/notes/n-9") in methods
    assert ("POST", "/rest/notes") not in methods  # no duplicate note created
    link_posts = [c for c in calls if c.method == "POST"]
    assert json.loads(link_posts[0].content) == {"noteId": "n-9", "targetPersonId": "p-1"}


def test_attach_note_skips_relink_when_target_exists():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET" and request.url.path.endswith("/notes"):
            return httpx.Response(200, json={"data": {"notes": [{"id": "n-9"}]}})
        if request.method == "GET" and request.url.path.endswith("/noteTargets"):
            return httpx.Response(200, json={"data": {"noteTargets": [{"id": "nt-1"}]}})
        return httpx.Response(200, json={"data": {"updateNote": {"id": "n-9"}}})

    from relationship_intel.crm.base import NotePayload

    _adapter(handler).attach_note(
        CRMRef("twenty", "person", "p-1"), NotePayload(title="T", body="b")
    )
    assert not [c for c in calls if c.method == "POST"]  # no duplicate link row


def test_opportunity_update_patches_existing_record():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"opportunities": [{"id": "o-7"}]}})
        return httpx.Response(200, json={"data": {"updateOpportunity": {"id": "o-7"}}})

    ref = _adapter(handler).create_or_update_opportunity({"name": "Deal", "stage": "qualified"})
    assert ref.crm_id == "o-7"
    patch = next(c for c in calls if c.method == "PATCH")
    assert patch.url.path == "/rest/opportunities/o-7"
    assert json.loads(patch.content)["stage"] == "MEETING"


def test_get_pipeline_items_reads_opportunity_custom_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "data": {
                    "opportunities": [
                        {
                            "id": "o-1",
                            "stage": "SCREENING",
                            "leadType": "WARM",
                            "successionSignalScore": 63,
                            "timingWindow": "MONTHS_6_12",
                            "pointOfContact": {"name": {"firstName": "Bob"}},
                            "company": {"name": "Smith HVAC"},
                        }
                    ]
                }
            },
        )

    items = _adapter(handler).get_pipeline_items()
    assert len(items) == 1
    assert items[0].lead_type == "warm"
    assert items[0].succession_signal_score == 63
    assert items[0].timing_window == "6_12_months"


def test_task_uses_bodyv2_markdown_and_task_target_link():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"tasks": []}})
        if request.url.path.endswith("/tasks"):
            return httpx.Response(201, json={"data": {"createTask": {"id": "t-1"}}})
        return httpx.Response(201, json={"data": {"createTaskTarget": {"id": "tt-1"}}})

    from relationship_intel.crm.base import TaskPayload

    _adapter(handler).create_task(
        CRMRef("twenty", "person", "p-1"), TaskPayload(title="Call Bob", body="do it")
    )
    posts = [c for c in calls if c.method == "POST"]
    task_body = json.loads(posts[0].content)
    assert task_body["title"] == "Call Bob"
    assert task_body["bodyV2"] == {"markdown": "do it"}
    assert task_body["status"] == "TODO"
    assert json.loads(posts[1].content) == {"taskId": "t-1", "targetPersonId": "p-1"}


def test_dsl_metacharacters_skip_filter_lookup_and_create_directly():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(201, json={"data": {"createPerson": {"id": "p-1"}}})

    ref = _adapter(handler).find_or_create_contact({"name": "Smith, Jr. (Bob)", "email": None})
    assert ref.crm_id == "p-1"
    # No GET lookup was attempted — unsafe operands skip straight to create.
    assert all(request.method == "POST" for request in calls)
    for request in calls:
        assert "filter" not in dict(request.url.params)


def test_api_key_never_appears_in_logs(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"people": []}})

    with caplog.at_level(logging.DEBUG):
        _adapter(handler).health_check()
    for record in caplog.records:
        assert KEY not in record.getMessage()
