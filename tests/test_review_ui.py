from __future__ import annotations

from relationship_intel import pipeline
from relationship_intel.review import _handle_bundle, _render_page


def test_review_page_groups_people_with_context(settings, samples_dir):
    pipeline.run_ingest(settings, samples_dir)

    html = _render_page(settings)

    assert "Extracted people" in html
    assert "Twenty write preview" in html
    assert "Approve all" in html
    assert "Evidence and source transcript" in html
    assert "Bob Smith" in html
    assert "Smith HVAC" in html
    assert "Relationship note" in html


def test_bundle_action_updates_related_review_items(settings, samples_dir):
    pipeline.run_ingest(settings, samples_dir)
    repo = pipeline.open_repo(settings)
    bob = next(person for person in repo.people_records() if person.name == "Bob Smith")

    changed = _handle_bundle(
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
    repo = pipeline.open_repo(settings)
    assert repo.review_item("person", bob.id).status == "approved"
    assert repo.review_item("person_note", bob.id).status == "approved"
    assert repo.review_item("person_task", bob.id).status == "approved"
