"""Pipeline orchestration used by the CLI (kept out of cli.py so tests can drive
the stages directly). Logging references transcript hashes only — never bodies."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from relationship_intel.config import Settings
from relationship_intel.crm.base import CRMAdapter
from relationship_intel.crm.mock_adapter import MockCRMAdapter
from relationship_intel.crm.sync import sync_to_crm
from relationship_intel.extraction.extractor import Extractor
from relationship_intel.extraction.schemas import (
    PROSPECT_LEAD_TYPES,
    ExtractedRelationshipIntelligence,
)
from relationship_intel.intake.local_folder import (
    LocalFolderSource,
    RawTranscript,
    TranscriptSource,
)
from relationship_intel.obsidian import templates
from relationship_intel.obsidian.writer import VaultWriter
from relationship_intel.planning import contract, promotion_proposal, weekly_plan
from relationship_intel.store.db import connect
from relationship_intel.store.repository import Repository
from relationship_intel.util.dates import monday_of_week
from relationship_intel.util.slugs import slugify

logger = logging.getLogger(__name__)


def open_repo(settings: Settings) -> Repository:
    return Repository(connect(settings.db_path))


def make_adapter(settings: Settings, crm: str | None = None) -> CRMAdapter:
    provider = crm or settings.crm_provider
    if provider == "twenty":
        from relationship_intel.crm.twenty_adapter import TwentyCRMAdapter

        return TwentyCRMAdapter(settings.twenty_api_url, settings.twenty_api_key)
    return MockCRMAdapter(settings.mock_crm_path)


def try_make_adapter(settings: Settings, crm: str | None = None) -> CRMAdapter | None:
    """Best-effort adapter construction for read-only enrichment paths (gh #15).
    Returns None if the adapter can't be built (e.g., TwentyCRMAdapter without
    an API key). Callers that only need read-only lookups can degrade
    gracefully — the review UI keeps working without the 'already in CRM'
    badge when Twenty isn't reachable/configured."""
    try:
        return make_adapter(settings, crm)
    except Exception as exc:  # noqa: BLE001 - best-effort by design
        logger.info("adapter unavailable for enrichment: %s", type(exc).__name__)
        return None


def run_init(settings: Settings, vault: Path | None = None) -> Path:
    vault_root = vault or settings.obsidian_vault_path
    writer = VaultWriter(vault_root, settings.obsidian_mode)
    for folder in writer.folder_names:
        writer.dir_for(folder).mkdir(parents=True, exist_ok=True)
    writer.ensure_readme()
    open_repo(settings)  # creates the db + schema
    settings.mock_crm_path.mkdir(parents=True, exist_ok=True)
    return writer.root


def run_ingest(settings: Settings, source: Path, vault: Path | None = None) -> dict:
    return run_ingest_source(settings, LocalFolderSource(source), vault)


def run_ingest_source(
    settings: Settings, source: TranscriptSource, vault: Path | None = None
) -> dict:
    vault_root = vault or settings.obsidian_vault_path
    run_init(settings, vault_root)
    repo = open_repo(settings)
    writer = VaultWriter(vault_root, settings.obsidian_mode)
    extractor = Extractor(settings)

    stats = {"ingested": 0, "skipped_duplicates": 0}
    processed: list[tuple[RawTranscript, ExtractedRelationshipIntelligence, list]] = []
    try:
        for raw in source.iter_transcripts():
            # Dedupe first; extraction is pure, so nothing is persisted until it
            # succeeds.
            if repo.transcript_seen(raw.transcript_hash):
                logger.info("Skipping duplicate transcript hash=%s", raw.transcript_hash[:12])
                stats["skipped_duplicates"] += 1
                continue
            eri = extractor.extract(raw)
            transcript_id, _ = repo.register_transcript(
                raw, store_raw=settings.store_raw_transcripts
            )
            try:
                opportunity_ids = _persist(repo, transcript_id, raw, eri, settings)
            except Exception:
                # Make the transcript retryable instead of stranding it as a false
                # duplicate; people/companies already upserted are retry-safe.
                repo.delete_transcript(transcript_id)
                raise
            processed.append((raw, eri, opportunity_ids))
            stats["ingested"] += 1
    finally:
        # Notes are written after all persists so cross-links use the final
        # collision-aware slugs — and in the finally so a mid-batch failure
        # still writes notes for the transcripts that DID land (they are
        # registered and would be skipped as duplicates on the retry run).
        _write_transcript_notes(repo, writer, processed, settings)
        _write_entity_notes(repo, writer, settings.llm_provider, settings.default_owner)
        rebuild_review_queue(repo, adapter=try_make_adapter(settings))
    return stats


def _persist(
    repo: Repository,
    transcript_id: int,
    raw: RawTranscript,
    eri: ExtractedRelationshipIntelligence,
    settings: Settings,
) -> list[int]:
    company_ids: dict[str, int] = {}
    for company in eri.companies:
        company_ids[company.name], _ = repo.resolve_company(company)

    profiles_by_person = {p.person_name: p for p in eri.lead_profiles}
    meeting_date = raw.meeting_date.isoformat() if raw.meeting_date else None

    opportunity_ids: list[int] = []
    for person in eri.people:
        profile = profiles_by_person.get(person.name)
        company_id = company_ids.get(profile.company_name) if profile else None
        person_id, _ = repo.resolve_person(person, company_id)
        evidence = profile.evidence_snippets if profile else person.evidence
        repo.add_interaction(person_id, transcript_id, meeting_date, evidence)
        if profile:
            repo.add_lead_profile(
                person_id,
                transcript_id,
                profile.model_dump_json(),
                eri.lens_version,
                eri.llm_provider,
            )
            if profile.lead_type in PROSPECT_LEAD_TYPES:
                # Person is always part of the name: co-owner prospects at one
                # company must never collide on the opportunity name.
                anchor = " — ".join(part for part in (profile.company_name, person.name) if part)
                opportunity_ids.append(
                    repo.upsert_opportunity(
                        f"{anchor} — Succession",
                        person_id,
                        company_id,
                        profile.model_dump(mode="json"),
                        raw.owner or settings.default_owner,
                    )
                )
    return opportunity_ids


def _write_transcript_notes(
    repo: Repository, writer: VaultWriter, processed: list, settings: Settings
) -> None:
    if not processed:
        return
    # Name-keyed maps prefer the lowest-id record (base slug). Known limitation:
    # when two people share a name, transcript-note links point at the first
    # person; the interaction rows and person notes themselves are always correct.
    person_slug_by_name = {rec.name: rec.slug for rec in reversed(repo.people_records())}
    company_slug_by_name = {rec.name: rec.slug for rec in reversed(repo.company_records())}
    opp_by_id = {rec.id: rec for rec in repo.opportunity_records()}
    for raw, eri, opportunity_ids in processed:
        opportunity_links = [
            (opp_by_id[oid].slug, opp_by_id[oid].name)
            for oid in opportunity_ids
            if oid in opp_by_id
        ]
        name, fm, managed = templates.transcript_note(
            raw,
            eri,
            settings.store_raw_transcripts,
            person_slug_by_name,
            company_slug_by_name,
            opportunity_links,
        )
        writer.write_note("transcripts", name, fm, managed)


def _write_entity_notes(
    repo: Repository,
    writer: VaultWriter,
    llm_provider: str,
    default_owner: str | None = None,
) -> None:
    people = repo.people_records()
    companies = repo.company_records()
    opportunities = repo.opportunity_records()

    for rec in people:
        name, fm, managed = templates.person_note(rec, llm_provider, default_owner)
        writer.write_note("people", name, fm, managed)
    for rec in companies:
        name, fm, managed = templates.company_note(rec, llm_provider, default_owner)
        writer.write_note("companies", name, fm, managed)
    for rec in opportunities:
        name, fm, managed = templates.opportunity_note(rec, llm_provider, default_owner)
        writer.write_note("opportunities", name, fm, managed)

    writer.write_jsonl_index(
        "people", templates.index_lines(people, ["id", "name", "email", "company_name", "slug"])
    )
    writer.write_jsonl_index(
        "companies", templates.index_lines(companies, ["id", "name", "domain", "slug"])
    )
    writer.write_jsonl_index(
        "opportunities",
        templates.index_lines(opportunities, ["id", "name", "stage", "lead_type", "slug"]),
    )
    writer.write_jsonl_index(
        "transcript-index",
        [
            json.dumps(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "date": row["meeting_date"],
                    "hash": row["transcript_hash"],
                },
                sort_keys=True,
            )
            for row in repo.transcript_records()
        ],
    )


def run_sync(settings: Settings, crm: str | None = None) -> dict:
    repo = open_repo(settings)
    adapter = make_adapter(settings, crm)
    return sync_to_crm(
        repo,
        adapter,
        settings.default_owner,
        approved_only=settings.crm_review_required,
    )


def rebuild_review_queue(repo: Repository, adapter: CRMAdapter | None = None) -> dict:
    """Rebuild the review queue from the canonical store.

    When `adapter` is supplied, the queue is also enriched with
    `existing_crm_ref` for any person/company already in the CRM (gh #15).
    The lookup is cached in the payload so subsequent rebuilds skip the
    (potentially slow) CRM call — a re-lookup only fires when the review
    item has no cached `existing_crm_ref` yet.
    """
    stats = {"people": 0, "companies": 0, "opportunities": 0, "notes": 0, "tasks": 0}
    for company in repo.company_records():
        payload = {"name": company.name, "domain": company.domain, "industry": company.industry}
        _apply_existing_crm_ref(
            repo, "company", company.id, payload, adapter, _lookup_existing_company
        )
        repo.upsert_review_item(
            "company",
            company.id,
            company.name,
            payload,
            reason=_company_review_reason(company),
        )
        stats["companies"] += 1

    for person in repo.people_records():
        profile = person.profile or {}
        person_payload = {
            "name": person.name,
            "email": person.email,
            "title": person.title,
            "company_id": person.company_id,
            "company_name": person.company_name,
        }
        _apply_existing_crm_ref(
            repo, "person", person.id, person_payload, adapter, _lookup_existing_person
        )
        reason = _person_review_reason(person)
        repo.upsert_review_item(
            "person",
            person.id,
            person.name,
            person_payload,
            reason=reason,
        )
        stats["people"] += 1

        if person.profile:
            note_payload = {
                "title": f"Relationship intelligence — {person.name}",
                "body": (
                    f"Lead type: {profile.get('lead_type')} | "
                    f"stage: {profile.get('stage')} | "
                    f"score: {profile.get('succession_signal_score')} | "
                    f"timing: {profile.get('timing_window')}.\n"
                    f"Next action: {profile.get('next_best_action') or 'none'}.\n"
                    f"Evidence lives in the vault: "
                    f"relationship-intelligence/people/{person.slug}.md"
                ),
            }
            repo.upsert_review_item(
                "person_note",
                person.id,
                note_payload["title"],
                note_payload,
                reason=reason,
            )
            stats["notes"] += 1

        if profile.get("next_best_action"):
            task_payload = {
                "title": profile["next_best_action"],
                "body": f"Owner: proposed by relationship-intel ({profile.get('lead_type')} lead).",
                "due_window": profile.get("next_action_due_window"),
            }
            repo.upsert_review_item(
                "person_task",
                person.id,
                task_payload["title"],
                task_payload,
                reason=reason,
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
            "person_id": opp.person_id,
            "company_id": opp.company_id,
        }
        repo.upsert_review_item(
            "opportunity",
            opp.id,
            opp.name,
            payload,
            reason=None,
            default_status="pending",
        )
        stats["opportunities"] += 1
    return stats


def _apply_existing_crm_ref(
    repo: Repository,
    object_type: str,
    local_id: int,
    payload: dict,
    adapter: CRMAdapter | None,
    lookup_fn,
) -> None:
    """Populate `payload['existing_crm_ref']` when the entity already exists
    in the CRM (gh #15). Uses the prior review item's cached ref when
    available so we don't spam the CRM on every review-UI page render.

    `upsert_review_item` no longer overwrites payload_json on conflict (so
    reviewer edits survive rebuild), which means enrichment done here won't
    hit disk for an EXISTING row unless we also merge it in explicitly.
    """
    if adapter is None:
        return
    prior = repo.review_item(object_type, local_id)
    cached = prior.payload.get("existing_crm_ref") if prior else None
    if isinstance(cached, dict):
        # Cache hit — copy into current payload so a new-row insert still
        # writes the enrichment as part of its initial payload.
        payload["existing_crm_ref"] = cached
        return
    # Anything else (None, missing, or a corrupted string from an older
    # form round-trip) is treated as a cache miss and we do a fresh lookup.
    existing = lookup_fn(adapter, payload)
    if not existing:
        return
    payload["existing_crm_ref"] = existing
    if prior is not None:
        # Existing row — upsert will preserve payload_json, so persist the
        # enrichment lookup explicitly rather than let it evaporate.
        repo.merge_review_item_payload(object_type, local_id, {"existing_crm_ref": existing})


def _lookup_existing_person(adapter: CRMAdapter, payload: dict) -> dict | None:
    return adapter.find_contact({"name": payload.get("name"), "email": payload.get("email")})


def _lookup_existing_company(adapter: CRMAdapter, payload: dict) -> dict | None:
    return adapter.find_company({"name": payload.get("name"), "domain": payload.get("domain")})


def _person_review_reason(person) -> str | None:
    reasons = []
    if len(person.name.split()) < 2:
        reasons.append("single-token name")
    if person.identity_confidence != "high":
        reasons.append(f"identity confidence {person.identity_confidence}")
    lead_type = (person.profile or {}).get("lead_type")
    if lead_type in (None, "unknown", "not_fit"):
        reasons.append(f"lead type {lead_type or 'unknown'}")
    if not person.company_name:
        reasons.append("no company")
    return "; ".join(reasons) if reasons else None


def _company_review_reason(company) -> str | None:
    if not company.people and not company.website:
        return "mentioned company/org without linked person or website"
    return None


def run_weekly_plan(
    settings: Settings,
    owner: str | None = None,
    week_start: date | None = None,
    vault: Path | None = None,
    run_date: date | None = None,
) -> dict:
    vault_root = vault or settings.obsidian_vault_path
    repo = open_repo(settings)
    writer = VaultWriter(vault_root, settings.obsidian_mode)
    run_date = run_date or date.today()
    week_start = week_start or monday_of_week(run_date)
    owner = owner or settings.default_owner

    plan = weekly_plan.build_plan(
        repo,
        owner,
        week_start,
        settings.stall_threshold_days,
        settings.llm_provider,
        run_date,
    )
    repo.save_plan(owner, plan["week_start"], weekly_plan.to_json(plan))

    note_name = f"{plan['week_label']}-{slugify(owner)}-succession-plan"
    fm = [
        ("type", "weekly_plan"),
        ("generated_by", templates.GENERATED_BY),
        ("review_status", "unreviewed"),
        ("llm_provider", plan["llm_provider"]),
        ("owner", owner),
        ("week_start", plan["week_start"]),
        ("week_end", plan["week_end"]),
        ("generated_at", plan["generated_at"]),
    ]
    writer.write_note("weekly-plans", note_name, fm, weekly_plan.to_markdown(plan))
    writer.write_json_artifact(
        "weekly-plans",
        f"{note_name}.json",
        weekly_plan.to_json(plan),
    )

    report = contract.build_report(plan)
    writer.write_report(
        f"CRM-{plan['generated_at']}.json",
        json.dumps(report, indent=2, sort_keys=True) + "\n",
    )
    proposal = promotion_proposal.build_l1_proposal(plan)
    proposal_name = f"{plan['week_label']}-{slugify(owner)}-l1-promotion-proposal"
    proposal_fm = [
        ("type", "l1_promotion_proposal"),
        ("generated_by", templates.GENERATED_BY),
        ("review_status", "unreviewed"),
        ("approval_status", "proposed"),
        ("target_path", promotion_proposal.TARGET_PATH),
        ("owner", owner),
        ("week_start", plan["week_start"]),
        ("generated_at", plan["generated_at"]),
    ]
    writer.write_note(
        "promotion-proposals",
        proposal_name,
        proposal_fm,
        promotion_proposal.to_markdown(proposal),
    )
    writer.write_json_artifact(
        "promotion-proposals",
        f"{proposal_name}.json",
        promotion_proposal.to_json(proposal),
    )
    return plan


def run_report(
    settings: Settings,
    owner: str | None = None,
    week_start: date | None = None,
    vault: Path | None = None,
    run_date: date | None = None,
) -> dict:
    _ = vault  # report is read-only; keep CLI signature parallel to weekly-plan.
    repo = open_repo(settings)
    run_date = run_date or date.today()
    week_start = week_start or monday_of_week(run_date)
    owner = owner or settings.default_owner
    plan = weekly_plan.build_plan(
        repo,
        owner,
        week_start,
        settings.stall_threshold_days,
        settings.llm_provider,
        run_date,
    )
    return contract.build_report(plan)
