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
from relationship_intel.util.hashing import short_hash

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
        # Stable per-(person, week) item id for the plan-feedback loop
        # (gh #16). Same person in the same week = same id, so feedback
        # can be recorded against a hash the operator can copy from the
        # plan Markdown/JSON and pipe back into `plan-feedback record`.
        item_id = short_hash(f"{rec.id}|{week_start.isoformat()}")
        item = {
            "id": item_id,
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

    # Stage rollup, deduped by person — feeds the Contract-1 report's
    # spec-shaped `pipeline_counts_by_stage` metric (docs/architecture.md §3.7).
    # top_plays overlaps with warm/hot/overdue, so iterate the non-top_plays
    # groups and dedupe on person_name.
    stage_counts: dict[str, int] = {}
    seen_people: set[str] = set()
    for name in ("hot", "overdue", "warm", "cold_retouch", "stalled", "long_term", "not_ready"):
        for item in groups[name]:
            if item["person_name"] in seen_people:
                continue
            seen_people.add(item["person_name"])
            stage = item.get("stage") or "unknown"
            stage_counts[stage] = stage_counts.get(stage, 0) + 1

    return {
        "owner": owner,
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "week_label": week_label(week_start),
        "generated_at": run_date.isoformat(),
        "llm_provider": llm_provider,
        "total_people": len(people),
        "groups": groups,
        "stage_counts": stage_counts,
    }


def _crm_link(repo: Repository, person_id: int) -> str | None:
    row = repo.any_crm_ref("person", person_id)
    if not row:
        return None
    return row["url"] or f"{row['provider']}:{row['crm_id']}"


# -- renderings -----------------------------------------------------------------

_HUMAN_TIMING = {
    "immediate": "immediate",
    "0_3_months": "0–3 months",
    "3_6_months": "3–6 months",
    "6_12_months": "6–12 months",
    "long_term": "long-term",
    "unknown": None,
}
_HUMAN_LEAD_TYPE = {
    "cold": "cold",
    "warm": "warm",
    "active": "active opportunity",
    "referral_source": "referral source",
    "partner": "partner",
    "not_fit": "not fit",
    "unknown": "unknown",
}
_HUMAN_URGENCY = {"high": "high urgency", "medium": "medium urgency", "low": "low urgency"}


def _humanize_timing(value: str | None) -> str | None:
    if value in (None, "", "unknown"):
        return None
    return _HUMAN_TIMING.get(value, value.replace("_", " "))


def _humanize_lead_type(value: str | None) -> str:
    if not value:
        return "unknown"
    return _HUMAN_LEAD_TYPE.get(value, value.replace("_", " "))


def _humanize_due(value: str | None) -> str | None:
    if not value or value == "unknown":
        return None
    return value.replace("_", " ")


def _render_item(index: int, item: dict) -> list[str]:
    """Human-readable per-item block. Meta (lead type / timing / score) lives
    on a subtle context line at the bottom, not stuffed into the header.
    Item id is embedded as an HTML comment so it stays copyable for the
    feedback loop but doesn't clutter the read."""
    name = item["person_name"]
    company = item.get("company_name")
    heading = f"### {index}. {name}"
    if company:
        heading += f" — {company}"

    lines: list[str] = [heading, ""]

    if item.get("why_now"):
        lines += [f"**Why now:** {item['why_now']}", ""]

    if item["next_action"]:
        lines.append(f"**Next action:** {item['next_action']}")
        due = _humanize_due(item.get("next_action_due_window"))
        if due:
            lines.append(f"*Due:* {due}")
        lines.append("")

    if item["suggested_message"]:
        # message_drafts.draft_for() prefixes with "DRAFT — not sent: " —
        # keep that marker literal so it survives any downstream automated
        # scan for the "never sent" invariant, but render it as a bolded
        # label above a blockquote of the actual message body.
        raw = item["suggested_message"]
        prefix = "DRAFT — not sent:"
        body = raw[len(prefix) :].strip() if raw.startswith(prefix) else raw
        lines += ["**DRAFT — not sent:**", "", f"> {body}", ""]

    # Context line: humanized lead type · timing · score · urgency.
    context_bits: list[str] = [_humanize_lead_type(item.get("lead_type"))]
    timing = _humanize_timing(item.get("timing_window"))
    if timing:
        context_bits.append(timing)
    if item.get("priority_score"):
        context_bits.append(f"signal score {item['priority_score']}")
    urgency_human = _HUMAN_URGENCY.get(item.get("urgency") or "", None)
    if urgency_human:
        context_bits.append(urgency_human)
    lines.append(f"*Context:* {' · '.join(context_bits)}")

    if item["evidence_links"]:
        lines.append(f"*Evidence:* {', '.join(item['evidence_links'])}")
    lines.append(f"*Profile:* {item['obsidian_link']}")
    if item["crm_link"]:
        lines.append(f"*CRM:* {item['crm_link']}")

    # Hidden anchor for the plan-feedback CLI copy-paste flow (gh #16).
    lines += ["", f"<!-- item-id: {item['id']} -->", ""]
    return lines


def _render_group(heading: str, items: list[dict], empty: str) -> list[str]:
    """Group section. Empty groups collapse to a one-liner so the plan reads
    tight when there's nothing in a bucket."""
    if not items:
        return [f"## {heading}", "", f"*{empty}*", ""]
    lines = [f"## {heading}", ""]
    for i, item in enumerate(items, 1):
        lines += _render_item(i, item)
    return lines


def _render_summary(plan: dict) -> list[str]:
    """One-glance summary of what's in the plan this week."""
    g = plan["groups"]
    counts = {name: len(g[name]) for name in g}

    def plural(n: int, singular: str, plural: str | None = None) -> str:
        return singular if n == 1 else (plural or singular + "s")

    bullets: list[str] = []
    if counts["top_plays"]:
        names = ", ".join(item["person_name"] for item in g["top_plays"][:3])
        bullets.append(
            f"**{counts['top_plays']}** {plural(counts['top_plays'], 'top play')} "
            f"this week: {names}"
        )
    if counts["overdue"]:
        bullets.append(f"**{counts['overdue']}** overdue — action needed")
    if counts["warm"]:
        bullets.append(f"**{counts['warm']}** warm {plural(counts['warm'], 'follow-up')}")
    if counts["cold_retouch"]:
        n = counts["cold_retouch"]
        bullets.append(f"**{n}** cold {plural(n, 'retouch', 'retouches')} due")
    if counts["referral_nurture"]:
        n = counts["referral_nurture"]
        bullets.append(f"**{n}** {plural(n, 'referral / partner')} to nurture")
    if counts["stalled"]:
        bullets.append(f"**{counts['stalled']}** stalled — worth a check-in")
    if counts["needs_review"]:
        bullets.append(f"**{counts['needs_review']}** flagged for identity review")
    tail_bits = []
    if counts["long_term"]:
        tail_bits.append(f"long-term nurture: {counts['long_term']}")
    if counts["not_ready"]:
        tail_bits.append(f"not ready: {counts['not_ready']}")
    if tail_bits:
        bullets.append("Also tracked — " + " · ".join(tail_bits))
    if not bullets:
        bullets.append("Light week — nothing needs your attention.")
    return ["## This week at a glance", ""] + [f"- {b}" for b in bullets] + [""]


def to_markdown(plan: dict) -> str:
    g = plan["groups"]
    # Week header — friendlier date phrasing than raw ISO.
    lines = [
        f"# Weekly Succession Plan — Week of {plan['week_start']}",
        "",
        f"*{plan['owner']} · Week {plan['week_label']} "
        f"({plan['week_start']} → {plan['week_end']}) · "
        f"extraction: `{plan['llm_provider']}`*",
        "",
    ]
    lines += _render_summary(plan)
    lines += ["---", ""]
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
        f"*Long-term nurture: {len(g['long_term'])} · Not ready: {len(g['not_ready'])}*",
        "",
        "*All drafts above are proposals — nothing is sent by this system.*",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _render_time_blocks(groups: dict[str, list[dict]]) -> list[str]:
    """Deterministic time-block heuristic — same input, same output. Owner
    uses these as prompts, not commitments. Grammar respects singular vs
    plural (one warm follow-up, three warm follow-ups)."""
    blocks: list[tuple[str, int, str, str]] = [
        ("Monday morning", len(groups["top_plays"]), "top play", "plan the week"),
        ("Tuesday morning", len(groups["warm"]), "warm follow-up", None),
        ("Wednesday morning", len(groups["overdue"]), "overdue item", "clean up"),
        ("Thursday afternoon", len(groups["cold_retouch"]), "cold retouch", None),
        (
            "Friday morning",
            len(groups["referral_nurture"]),
            "referral / partner",
            "nurture",
        ),
    ]
    lines = ["## Suggested time blocks", ""]
    if not any(count for _, count, *_ in blocks):
        lines += ["*Light week — no items to block.*", ""]
        return lines
    for label, count, singular, suffix in blocks:
        if not count:
            continue
        item_text = f"{count} {singular}" if count == 1 else f"{count} {singular}s"
        tail = f" — {suffix}" if suffix else ""
        lines.append(f"- **{label}** — {item_text}{tail}")
    lines.append("")
    return lines


def to_json(plan: dict) -> str:
    return json.dumps(plan, indent=2, sort_keys=True) + "\n"
