"""CLI — commands per docs/build-prompt.md §"CLI commands".

python -m relationship_intel.cli init
python -m relationship_intel.cli ingest --source examples/transcripts \\
    --vault ./output/obsidian-vault
python -m relationship_intel.cli sync-crm --crm mock
python -m relationship_intel.cli weekly-plan --owner James --week-start 2026-07-06
python -m relationship_intel.cli run-demo
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, is_dataclass
from datetime import date
from pathlib import Path
from typing import Any

from relationship_intel import pipeline
from relationship_intel.config import load_settings
from relationship_intel.doctor import run_doctor
from relationship_intel.errors import NotConfiguredError
from relationship_intel.evaluation import run_evaluation
from relationship_intel.intake.granola_api import GranolaAPISource
from relationship_intel.obsidian.writer import VaultWriter
from relationship_intel.queries import last_touch, who_to_call
from relationship_intel.queries import pipeline as pipeline_query
from relationship_intel.review import review_summary, serve_review_ui
from relationship_intel.util.dates import parse_iso_date


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, default=_json_default, indent=2, sort_keys=True))


_DERIVED_PLAN_GROUPS = frozenset({"top_plays", "needs_review"})


def _lookup_plan_item_context(
    repo: Any, week_start: str, item_id: str
) -> tuple[str | None, str | None]:
    """Best-effort: find (person_name, group_name) for a plan item id by
    reading the `plans` table for the given week. Iterates every stored plan
    for that week (one per owner), so operators who ran weekly-plan with a
    non-default --owner still get enriched feedback rollups. Filesystem-free
    on purpose — the old vault-walking path silently degraded whenever the
    filename slug convention drifted from what the caller reconstructed
    (gh #16 review-pass findings 1, 2, 5)."""
    # top_plays is a derived top-3 view over hot/warm/overdue; needs_review is
    # a metadata-flag view. Neither is a substantive pipeline group for tuning
    # purposes, so report the "home" group when the item appears there too.
    for row in repo.plans_for_week(week_start):
        try:
            plan = json.loads(row["plan_json"])
        except json.JSONDecodeError:
            continue
        groups = plan.get("groups") or {}
        # Two passes: substantive groups first, derived groups only as fallback.
        for group_name, items in groups.items():
            if group_name in _DERIVED_PLAN_GROUPS:
                continue
            for item in items:
                if item.get("id") == item_id:
                    return (item.get("person_name"), group_name)
        for group_name in _DERIVED_PLAN_GROUPS:
            for item in groups.get(group_name, []):
                if item.get("id") == item_id:
                    return (item.get("person_name"), group_name)
    return (None, None)


def _render_query(kind: str, rows: list[dict]) -> str:
    if not rows:
        return f"No {kind} results."
    lines = []
    for row in rows:
        if kind == "last-touch":
            lines.append(
                f"{row['person_name']}"
                + (f" — {row['company_name']}" if row["company_name"] else "")
                + f": last touch {row['last_interaction'] or 'never'}"
                + f" · {row['lead_type']} / {row['stage']}"
            )
        else:
            subject = row.get("person_name") or row.get("name") or "Unknown"
            lines.append(
                subject
                + (f" — {row['company_name']}" if row.get("company_name") else "")
                + f": {row['stage']} · {row['lead_type']} · score "
                f"{row['succession_signal_score']}"
                + (f" · next: {row['next_action']}" if row.get("next_action") else "")
            )
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    output_parent = argparse.ArgumentParser(add_help=False)
    output_parent.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="emit machine-readable JSON on stdout",
    )
    parser = argparse.ArgumentParser(
        prog="relationship_intel",
        description="Transcript -> relationship intelligence -> Obsidian + CRM + weekly plan",
        parents=[output_parent],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "init", help="initialize local store and output folders", parents=[output_parent]
    )

    ingest = sub.add_parser(
        "ingest", help="ingest transcripts and write vault notes", parents=[output_parent]
    )
    ingest.add_argument("--source-type", choices=["local", "granola"], default="local")
    ingest.add_argument("--source", default=None, type=Path)
    ingest.add_argument("--created-after", default=None)
    ingest.add_argument("--created-before", default=None)
    ingest.add_argument("--updated-after", default=None)
    ingest.add_argument("--folder-id", default=None)
    ingest.add_argument("--vault", default=None, type=Path)

    sync = sub.add_parser(
        "sync-crm", help="sync extracted records to the CRM", parents=[output_parent]
    )
    sync.add_argument("--crm", choices=["mock", "twenty"], default=None)

    plan = sub.add_parser(
        "weekly-plan", help="generate the beginning-of-week plan", parents=[output_parent]
    )
    plan.add_argument("--owner", default=None)
    plan.add_argument(
        "--week-start",
        default=None,
        help="ISO date (Monday); defaults to the current week's Monday",
    )
    plan.add_argument("--vault", default=None, type=Path)

    report = sub.add_parser(
        "report", help="emit the current Contract-1 CRM report", parents=[output_parent]
    )
    report.add_argument("--owner", default=None)
    report.add_argument(
        "--week-start",
        default=None,
        help="ISO date (Monday); defaults to the current week's Monday",
    )
    report.add_argument("--vault", default=None, type=Path)

    query = sub.add_parser(
        "query",
        help="read deterministic answers from the canonical store",
        parents=[output_parent],
    )
    query.add_argument("kind", choices=["pipeline", "last-touch", "who-to-call"])
    query.add_argument("--owner", default=None)
    query.add_argument("--limit", type=int, default=None)
    query.add_argument("--as-of", default=None, help="ISO date for who-to-call ranking")

    evaluate = sub.add_parser(
        "eval",
        help="score extraction against redacted expectation fixtures",
        parents=[output_parent],
    )
    evaluate.add_argument("--source", required=True, type=Path)

    sub.add_parser(
        "run-demo",
        help="full local POC: init + ingest samples + mock sync + plan",
        parents=[output_parent],
    )
    sub.add_parser(
        "doctor",
        help="read-only go-live readiness checks",
        parents=[output_parent],
    )
    provision_twenty = sub.add_parser(
        "provision-twenty",
        help=(
            "idempotently provision Twenty's schema for the review-in-Twenty "
            "flow (Phase 1.5: reviewStatus custom field on Person/Company/"
            "Opportunity + a single Home dashboard with a pending-review "
            "widget and a weekly-plan widget). Requires TWENTY_API_KEY."
        ),
        parents=[output_parent],
    )
    provision_twenty.add_argument(
        "--cleanup",
        action="store_true",
        help=(
            "after provisioning, delete Phase 1's dead artifacts (weeklyPlan "
            "custom object, its manually-published record, and the three "
            "'Review queue' KANBAN views on Person/Company/Opportunity)."
        ),
    )
    provision_twenty.add_argument(
        "--backfill-approved",
        action="store_true",
        help=(
            "DESTRUCTIVE, ONE-SHOT: after provisioning, flip every existing "
            "Twenty record with reviewStatus=PENDING to APPROVED. Intended "
            "to be run ONCE, after adding the reviewStatus field, so "
            "pre-Phase-1 records stop leaking into the pending queue. "
            "Prompts for interactive `YES` confirmation before running "
            "so re-invocations don't silently promote real candidates."
        ),
    )
    provision_twenty.add_argument(
        "--refresh-plan",
        action="store_true",
        help=(
            "overwrite the Home dashboard's weekly-plan widget with the "
            "current stored plan. Off by default so re-runs of "
            "provision-twenty (to reconfirm schema) don't blow away manual "
            "edits an operator made to the widget inside Twenty's UI. Turn "
            "on from the Monday weekly-plan job."
        ),
    )
    sub.add_parser(
        "review-queue",
        help="summarize pending CRM review items",
        parents=[output_parent],
    )
    review_ui = sub.add_parser(
        "review-ui",
        help=(
            "start the local CRM review UI. For a machine-readable snapshot "
            "of pending items use `review-queue --json` instead."
        ),
        parents=[output_parent],
    )
    review_ui.add_argument("--host", default="127.0.0.1")
    review_ui.add_argument("--port", type=int, default=8765)

    plan_feedback = sub.add_parser(
        "plan-feedback",
        help="record or summarize plan-item feedback (gh #16 learning loop)",
        parents=[output_parent],
    )
    plan_feedback.add_argument(
        "mode",
        choices=["record", "summary"],
        help="record: log an action for a plan item. summary: rollup of history.",
    )
    plan_feedback.add_argument(
        "--week-start",
        default=None,
        help="ISO date (Monday) for record mode; ignored in summary mode.",
    )
    plan_feedback.add_argument(
        "--item-id",
        default=None,
        help="hash id from the plan Markdown or JSON (record mode only)",
    )
    plan_feedback.add_argument(
        "--action",
        default=None,
        choices=["acted", "deferred", "rejected", "ignored"],
        help="operator's actual decision on this item (record mode only)",
    )
    plan_feedback.add_argument("--notes", default=None)
    plan_feedback.add_argument(
        "--weeks",
        type=int,
        default=None,
        help="summary mode: only include the last N distinct weeks",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)
    settings = load_settings()

    try:
        if args.command == "init":
            root = pipeline.run_init(settings)
            payload = {"db_path": settings.db_path, "vault_path": root}
            if args.json_output:
                _print_json(payload)
            else:
                print(f"Initialized store at {settings.db_path} and vault at {root}")

        elif args.command == "ingest":
            if args.source_type == "granola":
                source = GranolaAPISource(
                    settings.granola_api_key,
                    created_after=args.created_after,
                    created_before=args.created_before,
                    updated_after=args.updated_after,
                    folder_id=args.folder_id,
                )
                stats = pipeline.run_ingest_source(settings, source, args.vault)
            else:
                source = args.source or settings.transcripts_inbox_dir
                stats = pipeline.run_ingest(settings, source, args.vault)
            if args.json_output:
                _print_json(stats)
            else:
                print(
                    f"Ingested {stats['ingested']} transcript(s), "
                    f"skipped {stats['skipped_duplicates']} duplicate(s)"
                )

        elif args.command == "sync-crm":
            stats = pipeline.run_sync(settings, args.crm)
            if args.json_output:
                _print_json(stats)
            else:
                print(f"CRM sync complete: {stats}")

        elif args.command == "weekly-plan":
            try:
                week_start = parse_iso_date(args.week_start) if args.week_start else None
            except ValueError:
                print(
                    f"Invalid --week-start {args.week_start!r}; expected YYYY-MM-DD",
                    file=sys.stderr,
                )
                return 2
            plan = pipeline.run_weekly_plan(settings, args.owner, week_start, args.vault)
            if args.json_output:
                _print_json(plan)
            else:
                print(
                    f"Weekly plan generated for {plan['owner']}, week of {plan['week_start']} "
                    f"({sum(len(v) for v in plan['groups'].values())} grouped items)"
                )

        elif args.command == "report":
            try:
                week_start = parse_iso_date(args.week_start) if args.week_start else None
            except ValueError:
                print(
                    f"Invalid --week-start {args.week_start!r}; expected YYYY-MM-DD",
                    file=sys.stderr,
                )
                return 2
            report = pipeline.run_report(settings, args.owner, week_start, args.vault)
            if args.json_output:
                _print_json(report)
            else:
                metrics = report.get("metrics", {})
                print(f"Contract-1 report ({report['agent']}, {report['report_date']})")
                print(f"  {report['headline']}")
                print(
                    f"  confidence: {report['confidence']} · "
                    f"tracked: {metrics.get('total_tracked_people', 0)} · "
                    f"overdue: {metrics.get('overdue', 0)}"
                )
                print("  (use --json for the full report)")

        elif args.command == "query":
            limit = args.limit or (10 if args.kind == "who-to-call" else 20)
            repo = pipeline.open_repo(settings)
            if args.kind == "pipeline":
                rows = pipeline_query(repo, args.owner, limit)
            elif args.kind == "last-touch":
                rows = last_touch(repo, limit)
            else:
                try:
                    as_of = parse_iso_date(args.as_of) if args.as_of else None
                except ValueError:
                    print(f"Invalid --as-of {args.as_of!r}; expected YYYY-MM-DD", file=sys.stderr)
                    return 2
                rows = who_to_call(repo, args.owner, limit, as_of)
            payload = {"query": args.kind, "count": len(rows), "results": rows}
            if args.json_output:
                _print_json(payload)
            else:
                print(_render_query(args.kind, rows))

        elif args.command == "eval":
            report = run_evaluation(settings, args.source)
            if args.json_output:
                _print_json(report)
            else:
                print(
                    f"Evaluation: {report['passed']}/{report['cases']} passed "
                    f"({report['failed']} failed)"
                )
                for case in report["results"]:
                    status = "pass" if case["passed"] else "fail"
                    print(f"- {status}: {case['title']} ({case['source_id']})")
                    for finding in case["findings"]:
                        print(f"  - {finding['status']}: {finding['field']}: {finding['message']}")
            if report["failed"]:
                return 1

        elif args.command == "run-demo":
            vault = settings.obsidian_vault_path
            pipeline.run_init(settings)
            stats = pipeline.run_ingest(settings, Path("examples/transcripts"))
            sync_stats = pipeline.run_sync(settings, "mock")
            plan = pipeline.run_weekly_plan(settings)
            writer = VaultWriter(vault, settings.obsidian_mode)
            payload = {
                "llm_provider": settings.llm_provider,
                "ingest": stats,
                "sync": sync_stats,
                "vault_notes": writer.root,
                "weekly_plan_dir": writer.dir_for("weekly-plans"),
                "contract_report": writer.dir_for("reports") / f"CRM-{plan['generated_at']}.json",
                "db_path": settings.db_path,
                "mock_crm_path": settings.mock_crm_path,
            }
            if args.json_output:
                _print_json(payload)
            else:
                print(f"\n=== run-demo complete (llm_provider={settings.llm_provider}) ===")
                print(
                    f"Transcripts ingested: {stats['ingested']} "
                    f"(duplicates skipped: {stats['skipped_duplicates']})"
                )
                print(f"Mock CRM sync: {sync_stats}")
                print(f"Vault notes:   {writer.root}")
                print(f"Weekly plan:   {writer.dir_for('weekly-plans')}/")
                print(f"Contract-1:    {writer.dir_for('reports')}/CRM-{plan['generated_at']}.json")
                print(f"Canonical DB:  {settings.db_path}")
                print(f"Mock CRM data: {settings.mock_crm_path}")

        elif args.command == "doctor":
            report = run_doctor(settings, repo_root=Path.cwd())
            if args.json_output:
                _print_json(report)
            else:
                print(
                    f"Doctor status: {report['status']} "
                    f"({report['ok']} ok, {report['warn']} warn, "
                    f"{report['blocked']} blocked)"
                )
                for check in report["checks"]:
                    detail = f" — {check['detail']}" if check.get("detail") else ""
                    print(f"- {check['status']}: {check['name']}: {check['message']}{detail}")

        elif args.command == "provision-twenty":
            from relationship_intel.crm.twenty_provisioner import TwentyProvisioner
            from relationship_intel.planning import weekly_plan as _weekly_plan
            from relationship_intel.util.dates import monday_of_week

            if not settings.twenty_api_key:
                print("TWENTY_API_KEY is not set; see .env.example.", file=sys.stderr)
                return 2
            # Load the most-recent stored plan for the configured owner
            # (the plans table is keyed on (owner, week_start), so
            # unfiltered queries can return a colleague's plan) and render
            # it to markdown so the dashboard's rich-text widget shows the
            # actual plan James is working from — not a placeholder.
            rich_text_body: str | None = None
            repo = pipeline.open_repo(settings)
            week_start_iso = monday_of_week(date.today()).isoformat()
            plan_row = repo.conn.execute(
                "SELECT owner, week_start, plan_json FROM plans "
                "WHERE owner = ? AND week_start = ? LIMIT 1",
                (settings.default_owner, week_start_iso),
            ).fetchone()
            if plan_row is None:
                # Fall back to the most-recent plan on record for the same
                # owner so the widget is never empty just because Monday
                # hasn't run yet.
                plan_row = repo.conn.execute(
                    "SELECT owner, week_start, plan_json FROM plans "
                    "WHERE owner = ? ORDER BY week_start DESC LIMIT 1",
                    (settings.default_owner,),
                ).fetchone()
            if plan_row is not None:
                try:
                    plan_dict = json.loads(plan_row["plan_json"])
                    rich_text_body = _weekly_plan.to_markdown(plan_dict)
                except (json.JSONDecodeError, KeyError, TypeError) as exc:
                    print(
                        f"Warning: could not render weekly plan for widget: {exc}",
                        file=sys.stderr,
                    )
            # The dashboard iframe points at the local review UI daemon;
            # if it isn't running James sees a blank iframe in Twenty with
            # no in-Twenty triage fallback. Warn loudly at provision time.
            from relationship_intel.crm.twenty_provisioner import probe_review_ui

            probe_msg = probe_review_ui()
            if probe_msg:
                print(f"Warning: {probe_msg}", file=sys.stderr)

            provisioner = TwentyProvisioner(settings.twenty_api_url, settings.twenty_api_key)
            report = provisioner.provision_all(
                rich_text_body=rich_text_body,
                refresh_rich_text=args.refresh_plan,
            )
            cleanup_report = None
            if args.cleanup:
                cleanup_report = provisioner.cleanup_phase1_artifacts()
                report["cleanup"] = cleanup_report
            backfill_report = None
            if args.backfill_approved:
                # Destructive one-shot — insist on interactive `YES` so a
                # re-invocation doesn't silently promote real candidates.
                # Skip the prompt entirely when writing JSON output OR when
                # stdin isn't a TTY (launchd, cron, headless SSH) — in
                # those contexts `input()` raises EOFError and would crash
                # the whole command; treat non-interactive as an implicit
                # "no confirmation" and refuse the destructive step.
                interactive = sys.stdin.isatty() and not args.json_output
                confirmed = False
                if interactive:
                    prompt = (
                        "\n--backfill-approved is destructive and NOT idempotent.\n"
                        "It flips every Twenty record with reviewStatus=PENDING to\n"
                        "APPROVED — including genuine unreviewed candidates if you\n"
                        "run this after Phase 1.5 is live.\n"
                        "\nType YES to confirm, anything else to skip: "
                    )
                    try:
                        confirmed = input(prompt).strip() == "YES"
                    except EOFError:
                        confirmed = False
                if confirmed:
                    backfill_report = provisioner.backfill_pending_to_approved()
                    report["backfill"] = backfill_report
                else:
                    print(
                        "Backfill skipped (requires interactive YES confirmation).",
                        file=sys.stderr,
                    )
            if args.json_output:
                _print_json(report)
            else:
                print("Twenty provisioning report:")
                for entry in report["review_status_fields"]:
                    print(f"  reviewStatus on {entry['object']}: {entry['action']}")
                hd = report["home_dashboard"]
                print(f"  home dashboard '{hd['name']}':")
                print(f"    - page layout: {hd['page_layout']['action']}")
                print(f"    - tab: {hd['tab']['action']}")
                print(f"    - review-ui iframe widget: {hd['record_table_widget']['action']}")
                print(f"    - rich-text widget: {hd['rich_text_widget']['action']}")
                print(f"    - dashboard record: {hd['dashboard']['action']}")
                print(f"    - sidebar nav item: {hd['navigation_menu_item']['action']}")
                for entry in report["default_view_filters"]:
                    print(
                        f"  default-view IS_NOT PENDING filter on {entry['object']}: "
                        f"{entry['action']}"
                    )
                if cleanup_report is not None:
                    print("Phase 1 cleanup:")
                    print(
                        f"  legacy weeklyPlan record: "
                        f"{cleanup_report['legacy_weekly_plan_record']['action']}"
                    )
                    print(f"  weeklyPlan object: {cleanup_report['weekly_plan_object']['action']}")
                    for entry in cleanup_report["kanban_views"]:
                        print(f"  Review-queue kanban on {entry['object']}: {entry['action']}")
                if backfill_report is not None:
                    print("PENDING → APPROVED backfill:")
                    for entry in backfill_report["objects"]:
                        line = (
                            f"  {entry['object']}: {entry['patched']} patched, "
                            f"{entry['skipped']} skipped"
                        )
                        if entry.get("errors"):
                            line += f", patch errors: {len(entry['errors'])}"
                        if entry.get("fetch_error"):
                            line += f", fetch error: {entry['fetch_error']}"
                        if entry.get("truncated"):
                            line += " [TRUNCATED at page 1 — cursor pagination unsupported]"
                        print(line)

        elif args.command == "review-queue":
            summary = review_summary(settings)
            if args.json_output:
                _print_json(summary)
            else:
                print(f"Review queue: {summary['count']} item(s) {summary['by_status']}")

        elif args.command == "plan-feedback":
            repo = pipeline.open_repo(settings)
            if args.mode == "record":
                if not (args.week_start and args.item_id and args.action):
                    print(
                        "plan-feedback record requires --week-start, --item-id, --action",
                        file=sys.stderr,
                    )
                    return 2
                # Best-effort person_name / group_name lookup by reading the
                # `plans` table for the given week (all owners).
                person_name, group_name = _lookup_plan_item_context(
                    repo, args.week_start, args.item_id
                )
                repo.record_plan_feedback(
                    args.week_start,
                    args.item_id,
                    args.action,
                    args.notes,
                    person_name=person_name,
                    group_name=group_name,
                )
                payload = {
                    "recorded": True,
                    "week_start": args.week_start,
                    "item_id": args.item_id,
                    "action": args.action,
                    "person_name": person_name,
                    "group_name": group_name,
                }
                if args.json_output:
                    _print_json(payload)
                else:
                    context = f" ({person_name})" if person_name else ""
                    print(
                        f"Recorded: {args.action} on {args.item_id}"
                        f"{context} for week of {args.week_start}"
                    )
            else:  # summary
                if args.weeks is not None and args.weeks < 0:
                    print(
                        f"Invalid --weeks {args.weeks}; must be >= 0",
                        file=sys.stderr,
                    )
                    return 2
                summary = repo.plan_feedback_summary(args.weeks)
                if args.json_output:
                    _print_json(summary)
                else:
                    print(
                        f"Plan feedback ({summary['weeks_covered']} week(s)"
                        f"{f', last {args.weeks}' if args.weeks is not None else ''}):"
                    )
                    if not summary["totals"]:
                        print("  no feedback recorded yet")
                    for group, actions in sorted(summary["by_group"].items()):
                        print(f"  {group}: {actions}")
                    if summary["totals"]:
                        print(f"  totals: {summary['totals']}")

        elif args.command == "review-ui":
            if args.json_output:
                _print_json({"url": f"http://{args.host}:{args.port}/", "starting": True})
            serve_review_ui(settings, args.host, args.port)

    except NotConfiguredError as exc:
        if getattr(args, "json_output", False):
            _print_json({"error": "not_configured", "message": str(exc)})
        else:
            print(f"Not configured: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
