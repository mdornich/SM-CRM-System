"""CRM sync orchestration. Additive/update-safe; idempotent via crm_sync_state
(unchanged payload hash -> skipped entirely).

Summary boundary (KTD-8c): note bodies are built from profile/operational fields
plus the vault link — evidence snippets never pass into a CRM note."""

from __future__ import annotations

import hashlib
import json
import logging

from relationship_intel.crm.base import CRMAdapter, NotePayload, TaskPayload
from relationship_intel.obsidian.links import slugify
from relationship_intel.store.repository import Repository

logger = logging.getLogger(__name__)


def _payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _sync_object(repo, adapter, object_type: str, local_id: int, payload: dict, create):
    state = repo.get_sync_state(adapter.provider, object_type, local_id)
    if state and state["last_pushed_hash"] == _payload_hash(payload):
        return state, False
    ref = create(payload)
    repo.set_sync_state(
        adapter.provider, object_type, local_id, ref.crm_id, ref.url, _payload_hash(payload)
    )
    return repo.get_sync_state(adapter.provider, object_type, local_id), True


def sync_to_crm(repo: Repository, adapter: CRMAdapter, default_owner: str) -> dict:
    stats = {"companies": 0, "people": 0, "opportunities": 0, "notes": 0, "tasks": 0,
             "skipped": 0}

    company_refs: dict[int, str] = {}
    for company in repo.company_records():
        payload = {"name": company.name, "domain": company.domain,
                   "industry": company.industry}
        state, pushed = _sync_object(
            repo, adapter, "company", company.id, payload,
            lambda p: adapter.find_or_create_company(p),
        )
        company_refs[company.id] = state["crm_id"]
        stats["companies" if pushed else "skipped"] += 1

    person_refs: dict[int, str] = {}
    for person in repo.people_records():
        payload = {
            "name": person.name,
            "email": person.email,
            "title": person.title,
            "company_crm_id": company_refs.get(person.company_id),
        }
        state, pushed = _sync_object(
            repo, adapter, "person", person.id, payload,
            lambda p: adapter.find_or_create_contact(p),
        )
        person_refs[person.id] = state["crm_id"]
        stats["people" if pushed else "skipped"] += 1

        if pushed and person.profile:
            profile = person.profile
            note = NotePayload(
                title=f"Relationship intelligence — {person.name}",
                body=(
                    f"Lead type: {profile.get('lead_type')} | stage: {profile.get('stage')} | "
                    f"score: {profile.get('succession_signal_score')} | "
                    f"timing: {profile.get('timing_window')}.\n"
                    f"Next action: {profile.get('next_best_action') or 'none'}.\n"
                    f"Evidence lives in the vault: "
                    f"relationship-intelligence/people/{slugify(person.name)}.md"
                ),
            )
            ref_row = repo.get_sync_state(adapter.provider, "person", person.id)
            from relationship_intel.crm.base import CRMRef

            person_ref = CRMRef(adapter.provider, "person", ref_row["crm_id"], ref_row["url"])
            adapter.attach_note(person_ref, note)
            stats["notes"] += 1
            if profile.get("next_best_action"):
                adapter.create_task(
                    person_ref,
                    TaskPayload(
                        title=profile["next_best_action"],
                        body=f"Owner: {default_owner}. Proposed by relationship-intel "
                        f"({profile.get('lead_type')} lead).",
                        due_window=profile.get("next_action_due_window"),
                        assignee=default_owner,
                    ),
                )
                stats["tasks"] += 1

    for opp in repo.opportunity_records():
        payload = {
            "name": opp.name,
            "stage": opp.stage,
            "lead_type": opp.lead_type,
            "succession_signal_score": opp.succession_signal_score,
            "urgency": opp.urgency,
            "timing_window": opp.timing_window,
            "owner": opp.owner,
            "next_action": opp.next_action,
            "next_action_due": opp.next_action_due,
            "person_name": opp.person_name,
            "company_name": opp.company_name,
            "person_crm_id": person_refs.get(opp.person_id),
            "company_crm_id": company_refs.get(opp.company_id),
        }
        _, pushed = _sync_object(
            repo, adapter, "opportunity", opp.id, payload,
            lambda p: adapter.create_or_update_opportunity(p),
        )
        stats["opportunities" if pushed else "skipped"] += 1

    logger.info("CRM sync (%s): %s", adapter.provider, stats)
    return stats
