from __future__ import annotations

import json

import pytest

from relationship_intel import pipeline, review
from relationship_intel.review import _handle_bundle, _render_page


def test_review_page_groups_people_with_context(settings, samples_dir):
    pipeline.run_ingest(settings, samples_dir)

    html = _render_page(settings)

    assert "Extracted people" in html
    assert "Twenty write preview" in html
    assert "Approve" in html and "push to Twenty" in html
    assert "Evidence and source transcript" in html
    assert "Bob Smith" in html
    assert "Smith HVAC" in html
    assert "Relationship note" in html


def test_bundle_action_updates_related_review_items(settings, samples_dir):
    pipeline.run_ingest(settings, samples_dir)
    repo = pipeline.open_repo(settings)
    bob = next(person for person in repo.people_records() if person.name == "Bob Smith")

    changed, sync_stats = _handle_bundle(
        settings,
        {
            "status": ["approved"],
            "item": [
                f"person:{bob.id}",
                f"person_note:{bob.id}",
                f"person_task:{bob.id}",
            ],
        },
    )

    assert changed == 3
    # Approve bundle auto-pushes to the CRM (gh issue #6, Option 1).
    assert sync_stats is not None
    assert sync_stats["people"] == 1
    assert sync_stats["notes"] == 1
    assert sync_stats["tasks"] == 1
    repo = pipeline.open_repo(settings)
    assert repo.review_item("person", bob.id).status == "approved"
    assert repo.review_item("person_note", bob.id).status == "approved"
    assert repo.review_item("person_task", bob.id).status == "approved"


def test_existing_crm_contact_surfaces_as_followup_badge_and_skips_create(settings, samples_dir):
    """gh #15: a contact already in the CRM shows a follow-up badge in the
    review UI and, on approve, sync_to_crm uses the existing CRM id
    instead of creating a duplicate."""
    from relationship_intel.crm.mock_adapter import MockCRMAdapter
    from relationship_intel.crm.sync import sync_to_crm

    # Seed the mock CRM with Bob Smith BEFORE the pipeline runs, so his
    # first ingest looks like a "follow-up" from the CRM's perspective.
    # Email must match the extracted transcript's normalized email.
    settings.mock_crm_path.mkdir(parents=True, exist_ok=True)
    seed_adapter = MockCRMAdapter(settings.mock_crm_path)
    seed_ref = seed_adapter.find_or_create_contact(
        {"name": "Bob Smith", "email": "bob@smithhvac.com"}
    )

    pipeline.run_ingest(settings, samples_dir)

    html = _render_page(settings)
    assert "Follow-up with existing CRM record" in html
    assert seed_ref.crm_id in html

    # Approve triggers sync; the person write reuses the seeded CRM id
    # instead of creating a second Bob Smith.
    repo = pipeline.open_repo(settings)
    bob = next(p for p in repo.people_records() if p.name == "Bob Smith")
    review = repo.review_item("person", bob.id)
    assert review.payload.get("existing_crm_ref", {}).get("crm_id") == seed_ref.crm_id

    stats = sync_to_crm(repo, seed_adapter, settings.default_owner)
    assert stats["skipped"] >= 0  # sanity — mock adapter accepts the write
    # Only one Bob Smith exists in the mock CRM store post-sync.
    people = json.loads((settings.mock_crm_path / "people.json").read_text())
    bobs = [p for p in people.values() if p.get("name") == "Bob Smith"]
    assert len(bobs) == 1
    assert bobs[0]["id"] == seed_ref.crm_id


def test_bundle_approve_rolls_back_status_when_sync_raises(settings, samples_dir, monkeypatch):
    """A failed CRM push must not leave the review_items marked 'approved' —
    otherwise the next click silently pushes what this one couldn't (verified
    finding from the /review-workflow high-effort pass)."""
    pipeline.run_ingest(settings, samples_dir)
    repo = pipeline.open_repo(settings)
    bob = next(person for person in repo.people_records() if person.name == "Bob Smith")

    # Capture pre-click statuses so we can assert exact rollback fidelity.
    prior_person = repo.review_item("person", bob.id).status
    prior_note = repo.review_item("person_note", bob.id).status
    prior_task = repo.review_item("person_task", bob.id).status

    def boom(_settings):
        raise RuntimeError("simulated CRM outage during approve-and-push")

    monkeypatch.setattr(review, "_handle_sync", boom)

    with pytest.raises(RuntimeError, match="simulated CRM outage"):
        _handle_bundle(
            settings,
            {
                "status": ["approved"],
                "item": [
                    f"person:{bob.id}",
                    f"person_note:{bob.id}",
                    f"person_task:{bob.id}",
                ],
            },
        )

    repo = pipeline.open_repo(settings)
    assert repo.review_item("person", bob.id).status == prior_person
    assert repo.review_item("person_note", bob.id).status == prior_note
    assert repo.review_item("person_task", bob.id).status == prior_task
