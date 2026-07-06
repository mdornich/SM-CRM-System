"""CRM sync orchestration. Additive/update-safe; idempotent via crm_sync_state
(unchanged payload hash -> skipped entirely).

Summary boundary (KTD-8c): note bodies are built from profile/operational fields
plus the vault link — evidence snippets never pass into a CRM note."""

from __future__ import annotations

import json
import logging

from relationship_intel.crm.base import CRMAdapter, CRMRef, NotePayload, TaskPayload
from relationship_intel.crm.twenty_adapter import NO_OPP_STAGES
from relationship_intel.store.repository import Repository
from relationship_intel.util.hashing import short_hash

logger = logging.getLogger(__name__)


def _payload_hash(payload: dict) -> str:
    return short_hash(json.dumps(payload, sort_keys=True))


def _sync_object(
    repo,
    adapter,
    object_type: str,
    local_id: int,
    payload: dict,
    create,
    hash_payload: dict | None = None,
):
    state = repo.get_sync_state(adapter.provider, object_type, local_id)
    delivered_hash = _payload_hash(hash_payload or payload)
    if state and state["last_pushed_hash"] == delivered_hash:
        return state, False
    ref = create(payload)
    repo.set_sync_state(
        adapter.provider, object_type, local_id, ref.crm_id, ref.url, delivered_hash
    )
    return repo.get_sync_state(adapter.provider, object_type, local_id), True


def sync_to_crm(
    repo: Repository,
    adapter: CRMAdapter,
    default_owner: str,
    *,
    approved_only: bool = False,
) -> dict:
    stats = {
        "companies": 0,
        "people": 0,
        "opportunities": 0,
        "notes": 0,
        "tasks": 0,
        "skipped": 0,
        "skipped_by_stage": 0,
        "skipped_not_approved": 0,
    }
    twenty_provider = adapter.provider == "twenty"
    adapter.ensure_schema()

    approved_companies = repo.approved_review_ids("company") if approved_only else None
    approved_people = repo.approved_review_ids("person") if approved_only else None
    approved_opps = repo.approved_review_ids("opportunity") if approved_only else None
    approved_notes = repo.approved_review_ids("person_note") if approved_only else None
    approved_tasks = repo.approved_review_ids("person_task") if approved_only else None

    company_refs: dict[int, str] = {}
    for company in repo.company_records():
        if approved_companies is not None and company.id not in approved_companies:
            stats["skipped_not_approved"] += 1
            continue
        review = repo.review_item("company", company.id)
        payload = (
            review.payload
            if approved_only and review
            else {"name": company.name, "domain": company.domain, "industry": company.industry}
        )
        state, pushed = _sync_object(
            repo,
            adapter,
            "company",
            company.id,
            payload,
            lambda p: adapter.find_or_create_company(p),
        )
        company_refs[company.id] = state["crm_id"]
        stats["companies" if pushed else "skipped"] += 1

    person_refs: dict[int, str] = {}
    for person in repo.people_records():
        if approved_people is not None and person.id not in approved_people:
            stats["skipped_not_approved"] += 1
            continue
        review = repo.review_item("person", person.id)
        payload = (
            dict(review.payload)
            if approved_only and review
            else {
                "name": person.name,
                "email": person.email,
                "title": person.title,
            }
        )
        payload["company_crm_id"] = company_refs.get(person.company_id)
        state, pushed = _sync_object(
            repo,
            adapter,
            "person",
            person.id,
            payload,
            lambda p: adapter.find_or_create_contact(p),
        )
        person_refs[person.id] = state["crm_id"]
        stats["people" if pushed else "skipped"] += 1

        # Note/task delivery is tracked INDEPENDENTLY of the person record's sync
        # state (its own crm_sync_state rows, hashed on the profile payload,
        # written only after the adapter call succeeds). This means: a failed
        # attach is retried on the next sync, and a changed profile re-delivers
        # even when the person's identity payload is unchanged.
        if person.profile:
            profile = person.profile
            person_ref = CRMRef(adapter.provider, "person", state["crm_id"], state["url"])

            # Hashes cover the DELIVERED payloads, not the whole profile — an
            # unrelated profile-field change must not re-fire notes/tasks.
            if approved_notes is None or person.id in approved_notes:
                note_review = repo.review_item("person_note", person.id)
                if approved_only and note_review:
                    note = NotePayload(
                        title=note_review.payload["title"],
                        body=note_review.payload["body"],
                    )
                else:
                    note = NotePayload(
                        title=f"Relationship intelligence — {person.name}",
                        body=(
                            f"Lead type: {profile.get('lead_type')} | "
                            f"stage: {profile.get('stage')} | "
                            f"score: {profile.get('succession_signal_score')} | "
                            f"timing: {profile.get('timing_window')}.\n"
                            f"Next action: {profile.get('next_best_action') or 'none'}.\n"
                            f"Evidence lives in the vault: "
                            f"relationship-intelligence/people/{person.slug}.md"
                        ),
                    )
                note_hash = short_hash(note.title + "\n" + note.body)
                note_state = repo.get_sync_state(adapter.provider, "person_note", person.id)
                if not note_state or note_state["last_pushed_hash"] != note_hash:
                    note_ref = adapter.attach_note(person_ref, note)
                    repo.set_sync_state(
                        adapter.provider,
                        "person_note",
                        person.id,
                        note_ref.crm_id,
                        None,
                        note_hash,
                    )
                    stats["notes"] += 1

            if profile.get("next_best_action") and (
                approved_tasks is None or person.id in approved_tasks
            ):
                task_review = repo.review_item("person_task", person.id)
                if approved_only and task_review:
                    task = TaskPayload(
                        title=task_review.payload["title"],
                        body=task_review.payload["body"],
                        due_window=task_review.payload.get("due_window"),
                        assignee=default_owner,
                    )
                else:
                    task = TaskPayload(
                        title=profile["next_best_action"],
                        body=f"Owner: {default_owner}. Proposed by relationship-intel "
                        f"({profile.get('lead_type')} lead).",
                        due_window=profile.get("next_action_due_window"),
                        assignee=default_owner,
                    )
                task_hash = short_hash(f"{task.title}\n{task.body}\n{task.due_window}")
                task_state = repo.get_sync_state(adapter.provider, "person_task", person.id)
                if not task_state or task_state["last_pushed_hash"] != task_hash:
                    task_ref = adapter.create_task(person_ref, task)
                    repo.set_sync_state(
                        adapter.provider,
                        "person_task",
                        person.id,
                        task_ref.crm_id,
                        None,
                        task_hash,
                    )
                    stats["tasks"] += 1

    for opp in repo.opportunity_records():
        if approved_opps is not None and opp.id not in approved_opps:
            stats["skipped_not_approved"] += 1
            continue
        review = repo.review_item("opportunity", opp.id)
        payload = (
            dict(review.payload)
            if approved_only and review
            else {
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
            }
        )
        # Twenty's default board has no Lost/Stalled/Not-fit column; skip these
        # rather than crash the adapter. Check the REVIEWED stage (payload)
        # rather than the raw DB stage so a reviewer's edit doesn't bypass the
        # filter and detonate the sync mid-loop. `or opp.stage` (not
        # `dict.get(k, default)`) because a reviewer can clear the field to
        # an explicit None — we defensively fall back to the DB value rather
        # than push a None-stage payload the adapter will choke on. Mutating
        # `payload["stage"]` here (not just a local) is what actually keeps
        # None out of the adapter — the local check alone would leave the
        # payload dict carrying the reviewer's None into create_or_update.
        effective_stage = payload.get("stage") or opp.stage
        payload["stage"] = effective_stage
        if twenty_provider and effective_stage in NO_OPP_STAGES:
            stats["skipped_by_stage"] += 1
            logger.info(
                "twenty skip opportunity id=%s stage=%s (no Twenty column)",
                opp.id,
                effective_stage,
            )
            continue
        payload.update(
            {
                "person_crm_id": person_refs.get(opp.person_id),
                "company_crm_id": company_refs.get(opp.company_id),
            }
        )
        _, pushed = _sync_object(
            repo,
            adapter,
            "opportunity",
            opp.id,
            payload,
            lambda p: adapter.create_or_update_opportunity(p),
            hash_payload={**payload, "_crm_write_contract": "opportunity-custom-fields-v1"},
        )
        stats["opportunities" if pushed else "skipped"] += 1

    logger.info("CRM sync (%s): %s", adapter.provider, stats)
    # If the review gate held anything back, surface it as INFO (not WARNING).
    # Design choice, revisited across rounds 2-5 of /code-review:
    #   - Earlier versions gated on "and nothing landed" and oscillated
    #     between false positives (idempotent re-sync) and false negatives
    #     (only a note/task landed). The trigger condition kept flipping.
    #   - Fixed shape: fire whenever the gate held items back — that's what
    #     the operator wants to know. Whether other things landed is
    #     orthogonal.
    #   - INFO not WARNING because the review gate WORKING as designed is
    #     not an error condition. Ops who need alerting on a stuck backlog
    #     should run `relationship_intel review-queue --json` on a schedule
    #     — that surface is designed for it. A WARNING here would fire on
    #     every legitimate use of the gate and train operators to ignore it.
    if approved_only and stats["skipped_not_approved"] > 0:
        logger.info(
            "%d review item(s) awaiting approval — approve in the review UI "
            "(relationship_intel review-ui) or set CRM_REVIEW_REQUIRED=false "
            "to bypass the gate entirely.",
            stats["skipped_not_approved"],
        )
    return stats
