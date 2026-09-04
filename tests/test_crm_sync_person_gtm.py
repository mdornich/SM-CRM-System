"""sync._resolve_person_ref must write the GTM Person custom fields on the
reviewer-confirmed `existing_crm_ref` path (PR #18 review, finding 2).

An already-matched contact is precisely the case those fields exist for: before
this, the short-circuit returned a bare CRMRef and every existing person went
un-updated, so the four fields were only ever written on brand-new records."""

from __future__ import annotations

import logging

import pytest

from relationship_intel.crm.base import CRMRef
from relationship_intel.crm.sync import _resolve_person_ref


class _RecordingAdapter:
    provider = "twenty"

    def __init__(self):
        self.updates: list[tuple[CRMRef, dict]] = []
        self.created: list[dict] = []

    def update_contact_gtm_fields(self, ref: CRMRef, person: dict) -> CRMRef:
        self.updates.append((ref, person))
        return ref

    def find_or_create_contact(self, person: dict) -> CRMRef:
        self.created.append(person)
        return CRMRef(self.provider, "person", "p-new")


class _NoGtmAdapter:
    """A provider without the GTM surface (e.g. the mock adapter)."""

    provider = "mock"

    def find_or_create_contact(self, person: dict) -> CRMRef:  # pragma: no cover - guard
        raise AssertionError("cached-ref path must not create")


def _payload(**extra) -> dict:
    return {
        "name": "Bob Smith",
        "email": "bob@x.com",
        "existing_crm_ref": {"crm_id": "p-9", "url": "https://twenty/p-9"},
        **extra,
    }


def test_cached_ref_path_writes_gtm_fields():
    adapter = _RecordingAdapter()
    ref = _resolve_person_ref(
        adapter,
        _payload(wedge=["Acquirer"], source="warm-james", lifecycle_stage="Engaged"),
    )
    assert ref == CRMRef("twenty", "person", "p-9", "https://twenty/p-9")
    assert adapter.created == []
    assert len(adapter.updates) == 1
    written_ref, written_payload = adapter.updates[0]
    assert written_ref.crm_id == "p-9"
    assert written_payload["wedge"] == ["Acquirer"]
    assert written_payload["lifecycle_stage"] == "Engaged"


def test_cached_ref_path_skips_the_write_when_no_gtm_fields_present():
    """update_contact_gtm_fields raises on an empty payload, so the caller must
    not invoke it when the person carries none of the four keys."""
    adapter = _RecordingAdapter()
    _resolve_person_ref(adapter, _payload())
    assert adapter.updates == []


def test_cached_ref_path_tolerates_a_provider_without_the_gtm_surface():
    ref = _resolve_person_ref(_NoGtmAdapter(), _payload(source="warm-james"))
    assert ref == CRMRef("mock", "person", "p-9", "https://twenty/p-9")


def test_uncached_payload_still_falls_through_to_find_or_create():
    adapter = _RecordingAdapter()
    payload = {"name": "Ann Lee", "source": "cold-eos-list"}
    assert _resolve_person_ref(adapter, payload).crm_id == "p-new"
    assert adapter.created == [payload]
    assert adapter.updates == []


@pytest.mark.parametrize("crm_id", [None, ""])
def test_blank_cached_ref_falls_through_to_find_or_create(crm_id):
    adapter = _RecordingAdapter()
    payload = {"name": "Ann Lee", "existing_crm_ref": {"crm_id": crm_id}}
    assert _resolve_person_ref(adapter, payload).crm_id == "p-new"
    assert adapter.updates == []


class _RaisingAdapter(_RecordingAdapter):
    def __init__(self, exc: Exception):
        super().__init__()
        self.exc = exc

    def update_contact_gtm_fields(self, ref: CRMRef, person: dict) -> CRMRef:
        raise self.exc


@pytest.mark.parametrize("exc", [ValueError("bad wedge value"), RuntimeError("twenty 500")])
def test_gtm_write_failure_is_contained_per_record_and_counted(exc, caplog):
    """Finding 4: one malformed GTM value must not abort a run that already
    wrote companies and earlier people and persisted their sync state."""
    stats = {"gtm_write_failed": 0}
    adapter = _RaisingAdapter(exc)
    with caplog.at_level(logging.WARNING):
        ref = _resolve_person_ref(adapter, _payload(source="warm-james"), stats)
    assert ref.crm_id == "p-9"  # person still usable for notes/tasks
    assert stats["gtm_write_failed"] == 1
    assert any("GTM field write failed" in record.getMessage() for record in caplog.records)


def test_successful_gtm_write_does_not_increment_the_failure_counter():
    stats = {"gtm_write_failed": 0}
    _resolve_person_ref(_RecordingAdapter(), _payload(source="warm-james"), stats)
    assert stats["gtm_write_failed"] == 0


@pytest.mark.parametrize(
    "payload_extra",
    [
        {"wedge": None},
        {"wedge": None, "source": None, "lifecycle_stage": None, "wedge_primary": None},
    ],
)
def test_all_none_gtm_keys_do_not_trigger_an_update_round_trip(payload_extra):
    """Finding 2: has_person_gtm_fields tested key PRESENCE while the body
    builder skips None, so a `wedge: None` payload fired a whole update call
    (a live GET on the bare-ref path included) that wrote nothing."""
    adapter = _RecordingAdapter()
    _resolve_person_ref(adapter, _payload(**payload_extra), {"gtm_write_failed": 0})
    assert adapter.updates == []


def test_a_real_value_alongside_none_keys_still_writes():
    adapter = _RecordingAdapter()
    _resolve_person_ref(adapter, _payload(wedge=None, source="warm-james"), {"gtm_write_failed": 0})
    assert len(adapter.updates) == 1
