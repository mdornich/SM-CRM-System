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
from relationship_intel.planning import contract, weekly_plan
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
        _write_entity_notes(repo, writer, settings.llm_provider)
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


def _write_entity_notes(repo: Repository, writer: VaultWriter, llm_provider: str) -> None:
    people = repo.people_records()
    companies = repo.company_records()
    opportunities = repo.opportunity_records()

    for rec in people:
        name, fm, managed = templates.person_note(rec, llm_provider)
        writer.write_note("people", name, fm, managed)
    for rec in companies:
        name, fm, managed = templates.company_note(rec, llm_provider)
        writer.write_note("companies", name, fm, managed)
    for rec in opportunities:
        name, fm, managed = templates.opportunity_note(rec, llm_provider)
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
    return sync_to_crm(repo, adapter, settings.default_owner)


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
