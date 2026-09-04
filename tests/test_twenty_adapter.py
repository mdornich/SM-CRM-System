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


def test_created_person_is_tagged_review_status_approved():
    """Records only reach the Twenty adapter after local review-UI
    approval; without an explicit APPROVED tag the schema default
    'PENDING' would put every synced record back in the Home dashboard's
    pending queue."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"people": []}})
        return httpx.Response(201, json={"data": {"createPerson": {"id": "p-1"}}})

    _adapter(handler).find_or_create_contact({"name": "Bob Smith", "email": "b@x.com"})
    body = json.loads(calls[-1].content)
    assert body["reviewStatus"] == "APPROVED"


def test_created_company_is_tagged_review_status_approved():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"companies": []}})
        return httpx.Response(201, json={"data": {"createCompany": {"id": "c-1"}}})

    _adapter(handler).find_or_create_company({"name": "Smith HVAC", "domain": "smithhvac.com"})
    body = json.loads(calls[-1].content)
    assert body["reviewStatus"] == "APPROVED"


def test_opportunity_create_tags_approved_but_update_does_not():
    """PATCH must NOT force reviewStatus — a manual REJECTED flip in
    Twenty has to survive re-sync."""
    create_calls = []
    update_calls = []

    def create_handler(request: httpx.Request) -> httpx.Response:
        create_calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"opportunities": []}})
        return httpx.Response(201, json={"data": {"createOpportunity": {"id": "o-1"}}})

    _adapter(create_handler).create_or_update_opportunity({"name": "Deal Alpha", "stage": "new"})
    create_body = json.loads(create_calls[-1].content)
    assert create_body["reviewStatus"] == "APPROVED"

    def update_handler(request: httpx.Request) -> httpx.Response:
        update_calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"opportunities": [{"id": "o-9"}]}})
        return httpx.Response(200, json={})

    _adapter(update_handler).create_or_update_opportunity(
        {"name": "Deal Alpha", "stage": "qualified"}
    )
    patch_body = json.loads(update_calls[-1].content)
    assert "reviewStatus" not in patch_body


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
                        },
                        {
                            "id": "object-person",
                            "nameSingular": "person",
                            "fields": [
                                {"name": "wedge"},
                                {"name": "wedgePrimary"},
                                {"name": "source"},
                                {"name": "lifecycleStage"},
                            ],
                        },
                    ],
                    "pageInfo": {},
                    "totalCount": 1,
                },
            )
        return httpx.Response(201, json={"id": "field-new"})

    result = _adapter(handler).ensure_schema()
    assert result == {
        "created": ["successionSignalScore", "timingWindow"],
        "existing": ["leadType", "wedge", "wedgePrimary", "source", "lifecycleStage"],
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
                    },
                    {
                        "id": "object-person",
                        "nameSingular": "person",
                        "fields": [
                            {"name": "wedge"},
                            {"name": "wedgePrimary"},
                            {"name": "source"},
                            {"name": "lifecycleStage"},
                        ],
                    },
                ],
            },
        )

    result = _adapter(handler).ensure_schema()
    assert result == {
        "created": [],
        "existing": [
            "successionSignalScore",
            "leadType",
            "timingWindow",
            "wedge",
            "wedgePrimary",
            "source",
            "lifecycleStage",
        ],
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


def test_tag_record_raises_not_implemented_error():
    """gh #14: tag_record used to silently no-op. Twenty has no native tags on
    core records; raising surfaces the unimplemented method to any future
    caller instead of quietly dropping the tag."""
    ref = CRMRef("twenty", "person", "p-1")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {}})

    adapter = _adapter(handler)
    with pytest.raises(NotImplementedError, match="tag_record"):
        adapter.tag_record(ref, ["prospect", "warm"])


# --- Person GTM custom fields (gtm-crm-architecture.md §4) --------------------


def _people_handler(calls, existing=None, record=None):
    """GET /people returns `existing` (a list); POST creates p-1; PATCH 200."""

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"people": existing or []}})
        if request.method == "PATCH":
            return httpx.Response(200, json={"data": {"updatePerson": record or {"id": "p-9"}}})
        return httpx.Response(201, json={"data": {"createPerson": {"id": "p-1"}}})

    return handler


def test_person_custom_fields_written_on_create():
    calls = []
    _adapter(_people_handler(calls)).find_or_create_contact(
        {
            "name": "Bob Smith",
            "email": "bob@x.com",
            "wedge": ["EOS Practitioner", "Acquirer"],
            "wedge_primary": "EOS Practitioner",
            "source": "cold-eos-list",
            "lifecycle_stage": "Cold",
        }
    )
    body = json.loads(calls[-1].content)
    assert body["wedge"] == ["EOS_PRACTITIONER", "ACQUIRER"]
    assert body["wedgePrimary"] == "EOS_PRACTITIONER"
    assert body["source"] == "cold-eos-list"
    assert body["lifecycleStage"] == "COLD"


def test_person_custom_fields_round_trip_through_find_contact():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "people": [
                        {
                            "id": "p-3",
                            "name": {"firstName": "Bob", "lastName": "Smith"},
                            "emails": {"primaryEmail": "bob@x.com"},
                            "wedge": ["EOS_PRACTITIONER", "XPX"],
                            "wedgePrimary": "EOS_PRACTITIONER",
                            "source": "warm-james",
                            "lifecycleStage": "ENGAGED",
                        }
                    ]
                }
            },
        )

    found = _adapter(handler).find_contact({"email": "bob@x.com"})
    assert found["wedge"] == ["EOS_PRACTITIONER", "XPX"]
    assert found["wedge_primary"] == "EOS_PRACTITIONER"
    assert found["source"] == "warm-james"
    assert found["lifecycle_stage"] == "ENGAGED"


def test_find_contact_omits_gtm_keys_twenty_has_unset():
    """A present key means "write this" on the update path, so an unset field
    must be ABSENT from the read dict — otherwise feeding find_contact's output
    back through update_contact_gtm_fields would clear the record."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "people": [
                        {
                            "id": "p-3",
                            "name": {"firstName": "Bob", "lastName": "Smith"},
                            "emails": {"primaryEmail": "bob@x.com"},
                            "wedge": [],
                            "wedgePrimary": None,
                            "source": "",
                            "lifecycleStage": None,
                        }
                    ]
                }
            },
        )

    found = _adapter(handler).find_contact({"email": "bob@x.com"})
    assert "wedge" not in found
    assert "wedge_primary" not in found
    assert "source" not in found
    assert "lifecycle_stage" not in found
    # Round-trip: nothing to write, so the update path refuses rather than
    # issuing a clearing PATCH.
    with pytest.raises(ValueError):
        _adapter(handler).update_contact_gtm_fields(CRMRef("twenty", "person", "p-3"), found)


def test_multi_select_wedge_accepts_several_values_and_canonical_forms():
    calls = []
    _adapter(_people_handler(calls)).find_or_create_contact(
        {
            "name": "Ann Lee",
            "wedge": ["EOS_PRACTITIONER", "exit planner", "XPX", "Other"],
        }
    )
    body = json.loads(calls[-1].content)
    assert body["wedge"] == ["EOS_PRACTITIONER", "EXIT_PLANNER", "XPX", "OTHER"]


@pytest.mark.parametrize(
    "person",
    [
        {"name": "Bad One", "wedge_primary": "Investor"},
        {"name": "Bad Two", "lifecycle_stage": "Won"},
        {"name": "Bad Three", "wedge": ["EOS Practitioner", "Investor"]},
        {"name": "Bad Four", "wedge": "EOS Practitioner"},
    ],
)
def test_invalid_person_select_value_fails_closed_with_nothing_written(person):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise AssertionError("no request may be issued for an invalid option value")

    with pytest.raises(ValueError):
        _adapter(handler).find_or_create_contact(person)
    assert calls == []


def test_existing_person_patches_only_supplied_custom_fields():
    calls = []
    ref = _adapter(
        _people_handler(calls, existing=[{"id": "p-9", "lifecycleStage": "COLD"}])
    ).find_or_create_contact(
        {"name": "Bob Smith", "email": "bob@x.com", "lifecycle_stage": "Meeting"}
    )
    assert ref.crm_id == "p-9"
    patch = next(c for c in calls if c.method == "PATCH")
    assert patch.url.path == "/rest/people/p-9"
    assert json.loads(patch.content) == {"lifecycleStage": "MEETING"}


def test_existing_person_without_custom_fields_is_not_patched():
    calls = []
    _adapter(_people_handler(calls, existing=[{"id": "p-9"}])).find_or_create_contact(
        {"name": "Bob Smith", "email": "bob@x.com"}
    )
    assert [c.method for c in calls] == ["GET"]


def test_update_contact_patches_only_named_fields():
    calls = []
    adapter = _adapter(_people_handler(calls))
    adapter.update_contact_gtm_fields(CRMRef("twenty", "person", "p-4"), {"source": "referral"})
    patch = next(c for c in calls if c.method == "PATCH")
    assert patch.url.path == "/rest/people/p-4"
    assert json.loads(patch.content) == {"source": "referral"}


def test_update_contact_rejects_invalid_value_without_writing():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise AssertionError("no request may be issued for an invalid option value")

    with pytest.raises(ValueError, match="lifecycle_stage"):
        _adapter(handler).update_contact_gtm_fields(
            CRMRef("twenty", "person", "p-4"), {"lifecycle_stage": "Closed"}
        )
    assert calls == []


def test_ensure_schema_creates_missing_person_custom_fields():
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
                            "fields": [
                                {"name": "successionSignalScore"},
                                {"name": "leadType"},
                                {"name": "timingWindow"},
                            ],
                        },
                        {
                            "id": "object-person",
                            "nameSingular": "person",
                            "fields": [{"name": "source"}],
                        },
                    ]
                },
            )
        return httpx.Response(201, json={"id": "field-new"})

    result = _adapter(handler).ensure_schema()
    assert result["created"] == ["wedge", "wedgePrimary", "lifecycleStage"]
    assert "source" in result["existing"]
    posts = [json.loads(c.content) for c in calls if c.method == "POST"]
    assert all(body["objectMetadataId"] == "object-person" for body in posts)
    wedge = posts[0]
    assert wedge["type"] == "MULTI_SELECT"
    assert [option["value"] for option in wedge["options"]] == [
        "EOS_PRACTITIONER",
        "ACQUIRER",
        "EXIT_PLANNER",
        "XPX",
        "OTHER",
    ]
    assert posts[1]["type"] == "SELECT"
    assert [option["value"] for option in posts[1]["options"]] == [
        option["value"] for option in wedge["options"]
    ]
    assert [option["value"] for option in posts[2]["options"]] == [
        "COLD",
        "CONTACTED",
        "ENGAGED",
        "MEETING",
        "OPPORTUNITY",
        "CUSTOMER",
        "LOST",
        "NURTURE",
    ]


# --- PR #18 review findings ---------------------------------------------------


def test_name_matched_person_is_never_gtm_patched(caplog):
    """Finding 1: first+last name is a dedup heuristic, not an identity. Two
    'John Smith' rows means writing GTM fields on a name match would silently
    overwrite the other twin."""
    calls = []
    handler = _people_handler(calls, existing=[{"id": "p-twin", "lifecycleStage": "COLD"}])
    with caplog.at_level(logging.INFO):
        ref = _adapter(handler).find_or_create_contact(
            {
                "name": "John Smith",  # no email -> name-path match
                "wedge": ["Acquirer"],
                "source": "cold-acquirer-list-searchfunder",
                "lifecycle_stage": "Contacted",
            }
        )
    assert ref.crm_id == "p-twin"
    assert [c.method for c in calls] == ["GET"]  # matched, but nothing written
    assert any("name heuristic" in record.getMessage() for record in caplog.records)


def test_email_matched_person_is_still_gtm_patched():
    """The email path is the only match strong enough to write on — finding 1
    must not turn the whole update path off."""
    calls = []
    _adapter(
        _people_handler(calls, existing=[{"id": "p-9", "lifecycleStage": "COLD"}])
    ).find_or_create_contact({"name": "Bob Smith", "email": "bob@x.com", "source": "warm-james"})
    patch = next(c for c in calls if c.method == "PATCH")
    assert json.loads(patch.content) == {"source": "warm-james"}


@pytest.mark.parametrize(
    "current,proposed,written",
    [
        ("COLD", "Meeting", True),  # forward
        ("COLD", "Contacted", True),  # forward, one step
        (None, "Cold", True),  # nothing known to protect
        ("MEETING", "Cold", False),  # regression
        ("MEETING", "Meeting", False),  # no-op rewrite
        ("CUSTOMER", "Opportunity", False),  # regression from the far end
        ("ENGAGED", "Lost", True),  # §4: Any -> Lost
        ("ENGAGED", "Nurture", True),  # §4: Any -> Nurture
        ("LOST", "Contacted", False),  # never auto-revive a human's Lost
        ("NURTURE", "Engaged", False),  # nor a human's Nurture
    ],
)
def test_lifecycle_stage_only_moves_forward(current, proposed, written):
    """Finding 3: a repeated sync must not walk a manual Twenty edit backwards.
    Same 'manual edits win' rule the opportunity PATCH applies to reviewStatus."""
    calls = []
    _adapter(
        _people_handler(calls, existing=[{"id": "p-9", "lifecycleStage": current}])
    ).find_or_create_contact(
        {"name": "Bob Smith", "email": "bob@x.com", "lifecycle_stage": proposed}
    )
    patches = [c for c in calls if c.method == "PATCH"]
    assert bool(patches) is written
    if written:
        assert json.loads(patches[0].content)["lifecycleStage"] == proposed.upper()


def test_lifecycle_regression_still_writes_the_other_gtm_fields():
    calls = []
    _adapter(
        _people_handler(calls, existing=[{"id": "p-9", "lifecycleStage": "MEETING"}])
    ).find_or_create_contact(
        {
            "name": "Bob Smith",
            "email": "bob@x.com",
            "lifecycle_stage": "Cold",
            "source": "cold-eos-list",
        }
    )
    patch = next(c for c in calls if c.method == "PATCH")
    assert json.loads(patch.content) == {"source": "cold-eos-list"}


def test_update_contact_gtm_fields_reads_current_stage_before_writing():
    """A bare ref carries no stage, so the guard must do one read-only lookup
    rather than run blind."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(
                200, json={"data": {"people": [{"id": "p-4", "lifecycleStage": "CUSTOMER"}]}}
            )
        return httpx.Response(200, json={"data": {"updatePerson": {"id": "p-4"}}})

    _adapter(handler).update_contact_gtm_fields(
        CRMRef("twenty", "person", "p-4"), {"lifecycle_stage": "Cold"}
    )
    assert calls[0].url.params["filter"] == "id[eq]:p-4"
    assert not [c for c in calls if c.method == "PATCH"]


def test_update_contact_gtm_fields_raises_when_no_gtm_key_present():
    """Finding 5: dropping unrecognised keys and returning success hid a
    write that never happened."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise AssertionError("no request may be issued")

    with pytest.raises(ValueError, match="none of the GTM Person keys"):
        _adapter(handler).update_contact_gtm_fields(
            CRMRef("twenty", "person", "p-4"), {"name": "Bob Smith", "email": "b@x.com"}
        )
    assert calls == []


def test_multi_select_variants_are_deduplicated_preserving_order():
    """Finding 6: normalisation collapses variants, so ['Other', 'other'] would
    otherwise post a duplicate option."""
    calls = []
    _adapter(_people_handler(calls)).find_or_create_contact(
        {"name": "Ann Lee", "wedge": ["Other", "other", "XPX", "OTHER", "Acquirer"]}
    )
    body = json.loads(calls[-1].content)
    assert body["wedge"] == ["OTHER", "XPX", "ACQUIRER"]


def test_removed_na_wedge_option_now_fails_closed():
    """Mitch removed the stray live-only `NA` option from Twenty's Wedge field
    (2026-09-03), so §4's five values are the whole vocabulary and NA must be
    rejected like any other unknown value."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise AssertionError("no request may be issued")

    for person in (
        {"name": "Ann Lee", "wedge": ["EOS Practitioner", "NA"]},
        {"name": "Ann Lee", "wedge_primary": "NA"},
    ):
        with pytest.raises(ValueError, match="NA"):
            _adapter(handler).find_or_create_contact(person)
    assert calls == []
