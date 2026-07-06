"""Weekly plan: one PlanModel, three renderings (Markdown, JSON, Contract-1).

Grouping logic follows docs/build-prompt.md §"Weekly plan rules"; the Markdown
rendering uses the architecture.md §3.7 section structure (Top Plays / Overdue /
Warm Follow-Ups / Cold Retouches / Referral Nurture / Stalled / Needs Review /
Risks), with long-term / not-ready counts folded into a tail note under Risks.

Deterministic rubric: overdue first, then urgency x succession_signal_score
descending; stalled = no interaction in stall_threshold_days."""

from __future__ import annotations

import json
from datetime import date, timedelta

from relationship_intel.extraction.schemas import PROSPECT_LEAD_TYPES
from relationship_intel.obsidian.links import transcript_note_name, wikilink
from relationship_intel.planning.message_drafts import draft_for
from relationship_intel.store.repository import Repository
from relationship_intel.util.dates import parse_iso_date, week_label

_URGENCY_RANK = {"high": 3, "medium": 2, "low": 1, "unknown": 0}
_DUE_WINDOW_DAYS = {"immediate": 1, "this_week": 7, "two_weeks": 14}
_CADENCE_DAYS = {"weekly": 7, "biweekly": 14, "monthly": 30}


def _days_since(week_start: date, last_interaction: str | None) -> int | None:
    if not last_interaction:
        return None
    return (week_start - parse_iso_date(last_interaction)).days


def build_plan(
    repo: Repository,
    owner: str,
    week_start: date,
    stall_threshold_days: int,
    llm_provider: str,
    run_date: date,
) -> dict:
    groups: dict[str, list[dict]] = {
        name: []
        for name in (
            "top_plays",
            "hot",
            "overdue",
            "warm",
            "cold_retouch",
            "referral_nurture",
            "stalled",
            "long_term",
            "not_ready",
            "needs_review",
        )
    }
    people = repo.people_records()

    for rec in people:
        profile = rec.profile
        if profile is None or profile.get("lead_type") in ("not_fit", None):
            continue

        lead_type = profile["lead_type"]
        score = int(profile.get("succession_signal_score", 0))
        urgency = profile.get("urgency", "unknown")
        days = _days_since(week_start, rec.last_interaction)

        due_days = _DUE_WINDOW_DAYS.get(profile.get("next_action_due_window") or "", None)
        overdue = (
            profile.get("next_best_action") is not None
            and due_days is not None
            and days is not None
            and days > due_days
        )
        stalled = (
            lead_type in PROSPECT_LEAD_TYPES and days is not None and days >= stall_threshold_days
        )
        cadence_days = _CADENCE_DAYS.get(profile.get("recommended_cadence") or "", 30)

        evidence = profile.get("evidence_snippets") or rec.evidence
        transcript_links = [
            wikilink(transcript_note_name(d, t, h), t) for d, t, h in rec.transcripts
        ]
        item = {
            "person_name": rec.name,
            "company_name": rec.company_name,
            "stage": profile.get("stage", "new"),
            "lead_type": lead_type,
            "priority_score": score,
            "urgency": urgency,
            "timing_window": profile.get("timing_window", "unknown"),
            "overdue": overdue,
            "stalled": stalled,
            "days_since_last_interaction": days,
            "why_now": (evidence[0] if evidence else "no recorded signal"),
            "next_action": profile.get("next_best_action"),
            "next_action_due_window": profile.get("next_action_due_window"),
            "suggested_message": draft_for(rec.name, lead_type, profile.get("suggested_message")),
            "evidence_links": transcript_links,
            "obsidian_link": wikilink(rec.slug, rec.name),
            "crm_link": _crm_link(repo, rec.id),
            "needs_review": rec.needs_review or rec.identity_confidence == "medium",
            "approval_status": "proposed",
        }

        if item["needs_review"]:
            groups["needs_review"].append(item)
        if overdue:
            groups["overdue"].append(item)
        elif stalled:
            groups["stalled"].append(item)
        elif lead_type == "referral_source":
            groups["referral_nurture"].append(item)
        elif lead_type in ("warm", "active"):
            if urgency == "high" or score >= 70:
                groups["hot"].append(item)
            groups["warm"].append(item)
        elif lead_type == "cold":
            if days is None or days >= cadence_days:
                groups["cold_retouch"].append(item)
            else:
                groups["not_ready"].append(item)
        elif profile.get("timing_window") == "long_term":
            groups["long_term"].append(item)
        else:
            groups["not_ready"].append(item)

    def rank(item: dict) -> tuple:
        return (
            0 if item["overdue"] else 1,
            -_URGENCY_RANK.get(item["urgency"], 0) * max(item["priority_score"], 1),
            -item["priority_score"],
            item["person_name"],
        )

    for name, items in groups.items():
        groups[name] = sorted(items, key=rank)
    groups["top_plays"] = sorted(
        {i["person_name"]: i for i in groups["overdue"] + groups["hot"] + groups["warm"]}.values(),
        key=rank,
    )[:3]

    return {
        "owner": owner,
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "week_label": week_label(week_start),
        "generated_at": run_date.isoformat(),
        "llm_provider": llm_provider,
        "total_people": len(people),
        "groups": groups,
    }


def _crm_link(repo: Repository, person_id: int) -> str | None:
    row = repo.any_crm_ref("person", person_id)
    if not row:
        return None
    return row["url"] or f"{row['provider']}:{row['crm_id']}"


# -- renderings -----------------------------------------------------------------


def _render_item(index: int, item: dict) -> list[str]:
    lines = [
        f"{index}. **{item['person_name']}**"
        + (f" — {item['company_name']}" if item["company_name"] else "")
        + f" · {item['lead_type']} / {item['timing_window']} / score {item['priority_score']}",
        f"   - Why now: {item['why_now']}",
    ]
    if item["next_action"]:
        lines.append(
            f"   - Next action: {item['next_action']}"
            + (
                f" (due: {item['next_action_due_window']})"
                if item["next_action_due_window"]
                else ""
            )
        )
    if item["suggested_message"]:
        lines.append(f"   - {item['suggested_message']}")
    if item["evidence_links"]:
        lines.append(f"   - Evidence: {', '.join(item['evidence_links'])}")
    lines.append(f"   - Profile: {item['obsidian_link']}")
    if item["crm_link"]:
        lines.append(f"   - CRM: {item['crm_link']}")
    return lines


def _render_group(heading: str, items: list[dict], empty: str) -> list[str]:
    lines = [f"## {heading}", ""]
    if not items:
        lines += [f"_{empty}_", ""]
        return lines
    for i, item in enumerate(items, 1):
        lines += _render_item(i, item)
        lines.append("")
    return lines


def to_markdown(plan: dict) -> str:
    g = plan["groups"]
    lines = [
        f"# Weekly Succession Follow-Up Plan — {plan['week_start']}",
        "",
        f"Owner: {plan['owner']} · Week {plan['week_label']} "
        f"({plan['week_start']} → {plan['week_end']}) · "
        f"extraction: `{plan['llm_provider']}`",
        "",
    ]
    lines += _render_group("Top Plays This Week", g["top_plays"], "nothing urgent this week")
    lines += _render_group("Overdue", g["overdue"], "nothing overdue")
    lines += _render_group("Warm Follow-Ups", g["warm"], "no warm leads yet")
    lines += _render_group("Cold Retouches", g["cold_retouch"], "no retouches due")
    lines += _render_group(
        "Referral / Partner Nurture", g["referral_nurture"], "no referral sources tracked"
    )
    lines += _render_group("Stalled", g["stalled"], "nothing stalled")
    lines += _render_group(
        "Needs Review", g["needs_review"], "no identity flags — entity resolution is clean"
    )
    lines += _render_time_blocks(g)
    lines += [
        "## Risks",
        "",
        f"_Long-term nurture: {len(g['long_term'])} · Not ready: {len(g['not_ready'])}._",
        "All drafts above are proposals — nothing is sent by this system.",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _render_time_blocks(groups: dict[str, list[dict]]) -> list[str]:
    """Deterministic time-block heuristic — same input, same output. Owner uses
    these as prompts, not commitments."""
    blocks: list[tuple[str, int, str]] = [
        ("Mon AM — plan the week", len(groups["top_plays"]), "top plays"),
        ("Tue AM — warm follow-ups", len(groups["warm"]), "warm follow-ups"),
        ("Wed AM — overdue cleanup", len(groups["overdue"]), "overdue items"),
        ("Thu PM — cold retouches", len(groups["cold_retouch"]), "cold retouches"),
        ("Fri AM — referral / partner nurture", len(groups["referral_nurture"]), "referrals"),
    ]
    lines = ["## Suggested Time Blocks", ""]
    if not any(count for _, count, _ in blocks):
        lines += ["_No items to block — light week._", ""]
        return lines
    for label, count, kind in blocks:
        if count:
            lines.append(f"- **{label}** — {count} {kind}")
    lines.append("")
    return lines


def to_json(plan: dict) -> str:
    return json.dumps(plan, indent=2, sort_keys=True) + "\n"
