from __future__ import annotations

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
