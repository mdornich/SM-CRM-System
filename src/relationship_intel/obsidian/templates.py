"""Note templates per docs/build-prompt.md §"Obsidian note templates".
Every generated note carries generated_by / review_status / llm_provider frontmatter
(content_hash is appended by the writer)."""

from __future__ import annotations

import json

from relationship_intel.obsidian.links import slugify, transcript_note_name, wikilink
from relationship_intel.store.models import CompanyRecord, OpportunityRecord, PersonRecord
from relationship_intel.util.markdown import bullets, section

GENERATED_BY = "relationship-intel"


def _base_frontmatter(note_type: str, llm_provider: str) -> list[tuple[str, object]]:
    return [
        ("type", note_type),
        ("generated_by", GENERATED_BY),
        ("review_status", "unreviewed"),
        ("llm_provider", llm_provider),
    ]


def transcript_note(raw, eri, store_raw: bool) -> tuple[str, list[tuple[str, object]], str]:
    date_str = raw.meeting_date.isoformat() if raw.meeting_date else None
    name = transcript_note_name(date_str, raw.title)
    fm = _base_frontmatter("transcript", eri.llm_provider) + [
        ("source_system", raw.source_system),
        ("source_id", raw.source_id),
        ("date", date_str),
        ("owner", raw.owner),
        ("transcript_hash", raw.transcript_hash),
        ("processed", True),
    ]
    people_links = bullets([wikilink(slugify(p.name), p.name) for p in eri.people])
    company_links = bullets([wikilink(slugify(c.name), c.name) for c in eri.companies])
    opp_links = bullets(
        [
            wikilink(slugify(f"{p.company_name or p.person_name} succession"))
            for p in eri.lead_profiles
            if p.lead_type.value in ("warm", "active", "cold")
        ]
    )
    raw_body = (
        raw.raw_text
        if store_raw
        else "_Raw transcript storage disabled (STORE_RAW_TRANSCRIPTS=false); "
        "hash and evidence snippets retained._"
    )
    managed = "\n".join(
        [
            f"# Transcript: {raw.title}",
            "",
            section(
                "Metadata",
                bullets(
                    [
                        f"Source: {raw.source_system} / {raw.source_id}",
                        f"Date: {date_str or 'unknown'}",
                        f"Owner: {raw.owner or 'unknown'}",
                        f"Attendees: {', '.join(raw.attendees) or 'unknown'}",
                    ]
                ),
            ),
            section("Summary", [eri.conversation_summary.concise_summary]),
            section("Raw Transcript", [raw_body]),
            section(
                "Extraction Links",
                ["**People:**", *people_links, "", "**Companies:**", *company_links, "",
                 "**Opportunities:**", *(opp_links or ["- _none_"])],
            ),
        ]
    ).strip()
    return name, fm, managed


def person_note(rec: PersonRecord, llm_provider: str) -> tuple[str, list[tuple[str, object]], str]:
    profile = rec.profile or {}
    fm = _base_frontmatter("person", llm_provider) + [
        ("name", rec.name),
        ("email", rec.email),
        ("company", rec.company_name),
        ("lead_type", profile.get("lead_type")),
        ("stage", profile.get("stage")),
        ("confidence", profile.get("confidence")),
        ("identity_confidence", rec.identity_confidence),
        ("needs_review", rec.needs_review),
        ("last_interaction", rec.last_interaction),
        ("next_action", profile.get("next_best_action")),
        ("next_action_due", profile.get("next_action_due_window")),
        ("crm_id", None),
    ]
    signals = bullets(
        [
            f"Lead type: {profile.get('lead_type', 'unknown')}"
            f" | stage: {profile.get('stage', 'new')}"
            f" | score: {profile.get('succession_signal_score', 0)}",
            f"Urgency: {profile.get('urgency', 'unknown')}"
            f" | timing: {profile.get('timing_window', 'unknown')}",
            f"Business owner signal: {profile.get('business_owner_signal')}"
            f" | transition signal: {profile.get('exit_or_transition_signal')}",
        ]
    )
    managed = "\n".join(
        [
            f"# {rec.name}",
            "",
            section(
                "Snapshot",
                bullets(
                    [
                        f"Title: {rec.title or 'unknown'}",
                        f"Company: "
                        + (wikilink(slugify(rec.company_name), rec.company_name)
                           if rec.company_name else "unknown"),
                        f"Email: {rec.email or 'unknown'}",
                    ]
                ),
            ),
            section("Relationship Context", bullets([
                f"Identity confidence: {rec.identity_confidence}"
                + (" — **needs review**" if rec.needs_review else "")
            ])),
            section("Succession Signals", signals),
            section("Evidence", bullets([f'"{e}"' for e in rec.evidence])),
            section("Conversation History", bullets(
                [wikilink(transcript_note_name(d, t), t) for d, t in rec.transcripts]
            )),
            section("Next Actions", bullets(
                [a for a in [profile.get("next_best_action")] if a]
            )),
            section("CRM Links", []),
        ]
    ).strip()
    return slugify(rec.name), fm, managed


def company_note(rec: CompanyRecord, llm_provider: str) -> tuple[str, list[tuple[str, object]], str]:
    fm = _base_frontmatter("company", llm_provider) + [
        ("name", rec.name),
        ("industry", rec.industry),
        ("location", rec.location),
        ("crm_id", None),
    ]
    managed = "\n".join(
        [
            f"# {rec.name}",
            "",
            section("Snapshot", bullets(
                [
                    f"Website: {rec.website or 'unknown'}",
                    f"Industry: {rec.industry or 'unknown'}",
                    f"Location: {rec.location or 'unknown'}",
                ]
            )),
            section("Ownership / Succession Context",
                    [rec.ownership_context or "_unknown_"]),
            section("People", bullets(
                [wikilink(slugify(n), n) for n in rec.people_names]
            )),
        ]
    ).strip()
    return slugify(rec.name), fm, managed


def opportunity_note(
    rec: OpportunityRecord, llm_provider: str
) -> tuple[str, list[tuple[str, object]], str]:
    fm = _base_frontmatter("opportunity", llm_provider) + [
        ("name", rec.name),
        ("company", rec.company_name),
        ("primary_contact", rec.person_name),
        ("stage", rec.stage),
        ("lead_type", rec.lead_type),
        ("succession_signal_score", rec.succession_signal_score),
        ("urgency", rec.urgency),
        ("timing_window", rec.timing_window),
        ("owner", rec.owner),
        ("next_action", rec.next_action),
        ("next_action_due", rec.next_action_due),
        ("crm_id", None),
    ]
    managed = "\n".join(
        [
            f"# {rec.name}",
            "",
            section("Current Read", bullets(
                [
                    f"Stage: {rec.stage} | lead type: {rec.lead_type}"
                    f" | score: {rec.succession_signal_score}",
                    f"Urgency: {rec.urgency} | timing: {rec.timing_window}",
                ]
            )),
            section("Next Best Action", bullets(
                [a for a in [rec.next_action] if a] or ["_none_"]
            )),
            section("Links", bullets(
                [wikilink(slugify(n), n) for n in
                 [rec.person_name, rec.company_name] if n]
            )),
        ]
    ).strip()
    return slugify(rec.name), fm, managed


def index_lines(records: list, keys: list[str]) -> list[str]:
    lines = []
    for rec in records:
        payload = {k: getattr(rec, k, None) for k in keys}
        lines.append(json.dumps(payload, sort_keys=True, default=str))
    return lines
