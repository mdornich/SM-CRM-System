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
from relationship_intel.intake.local_folder import NotConfiguredError

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


def test_opportunity_stage_mapping_and_unmapped_stage_rejected():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"opportunities": []}})
        return httpx.Response(201, json={"data": {"createOpportunity": {"id": "o-1"}}})

    adapter = _adapter(handler)
    adapter.create_or_update_opportunity({"name": "Smith HVAC — Succession", "stage": "discovery"})
    assert json.loads(calls[-1].content)["stage"] == "SCREENING"

    with pytest.raises(ValueError, match="not_fit"):
        adapter.create_or_update_opportunity({"name": "X", "stage": "not_fit"})


def test_note_uses_bodyv2_markdown_and_note_target_link():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/notes"):
            return httpx.Response(201, json={"data": {"createNote": {"id": "n-1"}}})
        return httpx.Response(201, json={"data": {"createNoteTarget": {"id": "nt-1"}}})

    from relationship_intel.crm.base import NotePayload

    _adapter(handler).attach_note(
        CRMRef("twenty", "person", "p-1"), NotePayload(title="T", body="summary text")
    )
    note_body = json.loads(calls[0].content)
    assert note_body["bodyV2"] == {"markdown": "summary text"}
    target_body = json.loads(calls[1].content)
    assert target_body == {"noteId": "n-1", "personId": "p-1"}


def test_api_key_never_appears_in_logs(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"people": []}})

    with caplog.at_level(logging.DEBUG):
        _adapter(handler).health_check()
    for record in caplog.records:
        assert KEY not in record.getMessage()
