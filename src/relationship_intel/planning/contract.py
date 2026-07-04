"""Contract-1 department report.

The 980labsOS repo carries two Contract-1 shapes: the morning-brief template
(department/top_decisions/flagged_anomalies/...) and the fleet runtime validator
(agent/report_date/headline/confidence as non-empty STRINGS, metrics dict,
findings+decisions lists). We emit the UNION so both consumers are satisfied.

validate_agent_report_v1 below is vendored from
980labsOS/scripts/agent-fleet/contracts.py (same semantics, stdlib-only) so the
report is validated at emit time and in tests without a cross-repo import."""

from __future__ import annotations

_REQUIRED_STR_FIELDS = ("agent", "report_date", "headline", "confidence")
_REQUIRED_DICT_FIELDS = ("metrics",)
_REQUIRED_LIST_FIELDS = ("findings", "decisions")


def validate_agent_report_v1(payload) -> str | None:
    if not isinstance(payload, dict):
        return "payload must be object"
    for name in _REQUIRED_STR_FIELDS + _REQUIRED_DICT_FIELDS + _REQUIRED_LIST_FIELDS:
        if name not in payload:
            return f"missing field: {name}"
    for name in _REQUIRED_STR_FIELDS:
        value = payload[name]
        if not isinstance(value, str):
            return f"{name} must be string"
        if not value:
            return f"{name} must be non-empty string"
    for name in _REQUIRED_DICT_FIELDS:
        if not isinstance(payload[name], dict):
            return f"{name} must be object"
    for name in _REQUIRED_LIST_FIELDS:
        if not isinstance(payload[name], list):
            return f"{name} must be array"
    return None


def build_report(plan: dict) -> dict:
    groups = plan["groups"]
    counts = {name: len(items) for name, items in groups.items()}
    top = groups["top_plays"][:3]
    headline = (
        f"{counts['hot']} hot, {counts['overdue']} overdue, "
        f"{counts['warm']} warm follow-ups for {plan['owner']} "
        f"(week of {plan['week_start']})"
    )
    report = {
        # fleet-validator required shape
        "agent": "crm-source",
        "report_date": plan["generated_at"],
        "headline": headline,
        "confidence": "high" if plan["llm_provider"] != "mock" else "low",
        "metrics": {
            "pipeline_counts_by_group": counts,
            "total_tracked_people": plan["total_people"],
            "llm_provider": plan["llm_provider"],
        },
        "findings": [
            f"{item['person_name']} ({item['company_name'] or 'no company'}): "
            f"{item['why_now']}"
            for item in top
        ],
        "decisions": [
            {
                "summary": item["next_action"],
                "context": item["why_now"],
                "approval_status": "proposed",
            }
            for item in top
            if item["next_action"]
        ],
        # morning-brief template shape
        "department": "CRM",
        "top_decisions": [
            {"priority": i + 1, "summary": item["next_action"] or "review",
             "context": item["why_now"]}
            for i, item in enumerate(top)
        ],
        "flagged_anomalies": [
            f"identity needs review: {item['person_name']}" for item in groups["needs_review"]
        ],
        "yesterday_followups": [],
        "tomorrow_focus": [item["person_name"] for item in top],
    }
    error = validate_agent_report_v1(report)
    if error:
        raise ValueError(f"Contract-1 report invalid: {error}")
    return report
