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
import logging
import sys
from pathlib import Path

from relationship_intel import pipeline
from relationship_intel.config import load_settings
from relationship_intel.intake.local_folder import NotConfiguredError
from relationship_intel.util.dates import parse_iso_date


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="relationship_intel",
        description="Transcript -> relationship intelligence -> Obsidian + CRM + weekly plan",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="initialize local store and output folders")

    ingest = sub.add_parser("ingest", help="ingest transcripts and write vault notes")
    ingest.add_argument("--source", default="examples/transcripts", type=Path)
    ingest.add_argument("--vault", default=None, type=Path)

    sync = sub.add_parser("sync-crm", help="sync extracted records to the CRM")
    sync.add_argument("--crm", choices=["mock", "twenty"], default=None)

    plan = sub.add_parser("weekly-plan", help="generate the beginning-of-week plan")
    plan.add_argument("--owner", default=None)
    plan.add_argument(
        "--week-start",
        default=None,
        help="ISO date (Monday); defaults to the current week's Monday",
    )
    plan.add_argument("--vault", default=None, type=Path)

    sub.add_parser("run-demo", help="full local POC: init + ingest samples + mock sync + plan")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)
    settings = load_settings()

    try:
        if args.command == "init":
            root = pipeline.run_init(settings)
            print(f"Initialized store at {settings.db_path} and vault at {root}")

        elif args.command == "ingest":
            stats = pipeline.run_ingest(settings, args.source, args.vault)
            print(
                f"Ingested {stats['ingested']} transcript(s), "
                f"skipped {stats['skipped_duplicates']} duplicate(s)"
            )

        elif args.command == "sync-crm":
            stats = pipeline.run_sync(settings, args.crm)
            print(f"CRM sync complete: {stats}")

        elif args.command == "weekly-plan":
            week_start = parse_iso_date(args.week_start) if args.week_start else None
            plan = pipeline.run_weekly_plan(settings, args.owner, week_start, args.vault)
            print(
                f"Weekly plan generated for {plan['owner']}, week of {plan['week_start']} "
                f"({sum(len(v) for v in plan['groups'].values())} grouped items)"
            )

        elif args.command == "run-demo":
            vault = settings.obsidian_vault_path
            pipeline.run_init(settings)
            stats = pipeline.run_ingest(settings, Path("examples/transcripts"))
            sync_stats = pipeline.run_sync(settings, "mock")
            plan = pipeline.run_weekly_plan(settings)
            vault_ri = Path(vault) / "relationship-intelligence"
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
        print(f"Not configured: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
