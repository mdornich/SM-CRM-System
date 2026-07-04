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
from relationship_intel.errors import NotConfiguredError
from relationship_intel.queries import last_touch, who_to_call
from relationship_intel.queries import pipeline as pipeline_query
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
    ingest.add_argument("--source", default=None, type=Path)
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

    query = sub.add_parser(
        "query",
        help="read deterministic answers from the canonical store",
        parents=[output_parent],
    )
    query.add_argument("kind", choices=["pipeline", "last-touch", "who-to-call"])
    query.add_argument("--owner", default=None)
    query.add_argument("--limit", type=int, default=None)
    query.add_argument("--as-of", default=None, help="ISO date for who-to-call ranking")

    sub.add_parser(
        "run-demo",
        help="full local POC: init + ingest samples + mock sync + plan",
        parents=[output_parent],
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

        elif args.command == "run-demo":
            vault = settings.obsidian_vault_path
            pipeline.run_init(settings)
            stats = pipeline.run_ingest(settings, Path("examples/transcripts"))
            sync_stats = pipeline.run_sync(settings, "mock")
            plan = pipeline.run_weekly_plan(settings)
            vault_ri = Path(vault) / "relationship-intelligence"
            payload = {
                "llm_provider": settings.llm_provider,
                "ingest": stats,
                "sync": sync_stats,
                "vault_notes": vault_ri,
                "weekly_plan_dir": vault_ri / "weekly-plans",
                "contract_report": vault_ri / "reports" / f"CRM-{plan['generated_at']}.json",
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
                print(f"Vault notes:   {vault_ri}")
                print(f"Weekly plan:   {vault_ri}/weekly-plans/")
                print(f"Contract-1:    {vault_ri}/reports/CRM-{plan['generated_at']}.json")
                print(f"Canonical DB:  {settings.db_path}")
                print(f"Mock CRM data: {settings.mock_crm_path}")

    except NotConfiguredError as exc:
        if getattr(args, "json_output", False):
            _print_json({"error": "not_configured", "message": str(exc)})
        else:
            print(f"Not configured: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
