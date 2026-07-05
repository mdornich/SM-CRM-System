"""Review artifacts for Cairns L1 promotion candidates.

The pipeline never writes canonical L1 memory directly. This module renders a
proposal packet that a human or future approval layer can review and apply.
"""

from __future__ import annotations

import json
from typing import Any

TARGET_PATH = "cairns/L1/succession-pipeline.md"


def build_l1_proposal(plan: dict[str, Any]) -> dict[str, Any]:
    proposed_markdown = _proposed_l1(plan)
    return {
        "type": "l1_promotion_proposal",
        "target_path": TARGET_PATH,
        "approval_status": "proposed",
        "owner": plan["owner"],
        "generated_at": plan["generated_at"],
        "week_start": plan["week_start"],
        "action": f"Update {TARGET_PATH} with the latest Succession pipeline waypoint.",
        "scope": "Relationship-intelligence summary only; no raw transcript promotion.",
        "reason": "Keep Dex's first-read waypoint aligned with the reviewed weekly pipeline shape.",
        "risk": (
            "Unreviewed AI synthesis could distort canonical memory if applied without "
            "human review."
        ),
        "rollback": f"Revert the applied edit to {TARGET_PATH}; source proposal remains auditable.",
        "evidence": _evidence(plan),
        "proposed_markdown": proposed_markdown,
    }


def to_markdown(proposal: dict[str, Any]) -> str:
    lines = [
        f"# L1 Promotion Proposal - {proposal['week_start']}",
        "",
        f"Target: `{proposal['target_path']}`",
        f"Approval status: `{proposal['approval_status']}`",
        "",
        "## Approval Request",
        "",
        f"- Action: {proposal['action']}",
        f"- Scope: {proposal['scope']}",
        f"- Reason: {proposal['reason']}",
        f"- Risk: {proposal['risk']}",
        f"- Rollback: {proposal['rollback']}",
        "",
        "## Evidence",
        "",
    ]
    evidence = proposal.get("evidence") or []
    if evidence:
        lines.extend(f"- {item}" for item in evidence)
    else:
        lines.append("- No active pipeline evidence in this plan.")
    lines += [
        "",
        "## Proposed L1 Content",
        "",
        "```markdown",
        proposal["proposed_markdown"].rstrip(),
        "```",
        "",
    ]
    return "\n".join(lines)


def to_json(proposal: dict[str, Any]) -> str:
    return json.dumps(proposal, indent=2, sort_keys=True) + "\n"


def _proposed_l1(plan: dict[str, Any]) -> str:
    top = plan["groups"].get("top_plays", [])
    warm = plan["groups"].get("warm", [])
    stalled = plan["groups"].get("stalled", [])
    lines = [
        "# Succession Pipeline Waypoint",
        "",
        f"Week: {plan['week_start']} to {plan['week_end']}",
        f"Owner: {plan['owner']}",
        "Review status: unreviewed",
        "",
        "## Top Plays",
        "",
    ]
    if not top:
        lines.append("- No urgent plays surfaced.")
    else:
        for item in top:
            lines.append(
                f"- {item['person_name']}"
                + (f" - {item['company_name']}" if item.get("company_name") else "")
                + f": {item['lead_type']} / {item['timing_window']} / "
                f"score {item['priority_score']}; next: {item.get('next_action') or 'review'}"
            )
    lines += [
        "",
        "## Pipeline Shape",
        "",
        f"- Warm follow-ups: {len(warm)}",
        f"- Stalled: {len(stalled)}",
        f"- Needs review: {len(plan['groups'].get('needs_review', []))}",
        "",
        "## Guardrail",
        "",
        "This waypoint is proposed from unreviewed relationship-intelligence output. "
        "Apply only after human review.",
        "",
    ]
    return "\n".join(lines)


def _evidence(plan: dict[str, Any]) -> list[str]:
    items = plan["groups"].get("top_plays", []) or plan["groups"].get("warm", [])
    return [
        f"{item['person_name']}: {item['why_now']}" for item in items[:5] if item.get("why_now")
    ]
