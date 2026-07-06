"""Read-only query views for agent delegation. No LLM calls, no CRM writes."""

from __future__ import annotations

from datetime import date

from relationship_intel.store.repository import Repository
from relationship_intel.util.dates import parse_iso_date

_URGENCY_RANK = {"high": 3, "medium": 2, "low": 1, "unknown": 0}


def pipeline(repo: Repository, owner: str | None = None, limit: int = 20) -> list[dict]:
    records = repo.opportunity_records()
    if owner:
        records = [record for record in records if record.owner == owner]
    return [
        {
            "id": record.id,
            "name": record.name,
            "person_name": record.person_name,
            "company_name": record.company_name,
            "stage": record.stage,
            "lead_type": record.lead_type,
            "succession_signal_score": record.succession_signal_score,
            "urgency": record.urgency,
            "timing_window": record.timing_window,
            "owner": record.owner,
            "next_action": record.next_action,
            "next_action_due": record.next_action_due,
            "slug": record.slug,
        }
        for record in sorted(
            records,
            key=lambda record: (
                record.stage,
                -record.succession_signal_score,
                record.person_name or "",
            ),
        )[:limit]
    ]


def last_touch(repo: Repository, limit: int = 20) -> list[dict]:
    return [
        {
            "id": record.id,
            "person_name": record.name,
            "company_name": record.company_name,
            "last_interaction": record.last_interaction,
            "lead_type": (record.profile or {}).get("lead_type", "unknown"),
            "stage": (record.profile or {}).get("stage", "new"),
            "next_action": (record.profile or {}).get("next_best_action"),
            "needs_review": record.needs_review,
            "slug": record.slug,
        }
        for record in sorted(
            repo.people_records(),
            key=lambda record: (record.last_interaction is None, record.last_interaction or ""),
        )[:limit]
    ]


def who_to_call(
    repo: Repository,
    owner: str | None = None,
    limit: int = 10,
    as_of: date | None = None,
) -> list[dict]:
    as_of = as_of or date.today()
    people_by_id = {record.id: record for record in repo.people_records()}
    records = repo.opportunity_records()
    if owner:
        records = [record for record in records if record.owner == owner]

    def days_since_last(person_id: int | None) -> int | None:
        if person_id is None or person_id not in people_by_id:
            return None
        last = people_by_id[person_id].last_interaction
        if not last:
            return None
        return (as_of - parse_iso_date(last)).days

    def rank(record) -> tuple:
        days = days_since_last(record.person_id)
        return (
            0 if record.next_action else 1,
            -_URGENCY_RANK.get(record.urgency, 0),
            -record.succession_signal_score,
            -(days if days is not None else -1),
            record.person_name or "",
        )

    items = []
    for record in sorted(records, key=rank)[:limit]:
        days = days_since_last(record.person_id)
        items.append(
            {
                "id": record.id,
                "person_name": record.person_name,
                "company_name": record.company_name,
                "stage": record.stage,
                "lead_type": record.lead_type,
                "succession_signal_score": record.succession_signal_score,
                "urgency": record.urgency,
                "timing_window": record.timing_window,
                "last_interaction": (
                    people_by_id[record.person_id].last_interaction
                    if record.person_id in people_by_id
                    else None
                ),
                "days_since_last_interaction": days,
                "next_action": record.next_action,
                "next_action_due": record.next_action_due,
                "owner": record.owner,
                "slug": record.slug,
            }
        )
    return items
