# SM-CRM-System

Stable Mischief's **relationship-intelligence pipeline**: meeting transcripts in →
evidence-backed intelligence notes (Obsidian), operational CRM records (Twenty),
and an actionable beginning-of-week follow-up plan out.

- **Obsidian vault** = film room & evidence locker (transcripts, intelligence cards, audit trail)
- **Twenty CRM** = field & scoreboard (contacts, companies, opportunities, tasks)
- **This pipeline** = coach (extraction, classification, planning, drafting)

Spec: [`docs/architecture.md`](docs/architecture.md) · Source contract:
[`docs/build-prompt.md`](docs/build-prompt.md) · First use case: Succession
pipeline for James Whitfield.

**Phase 0 status:** the pipeline runs end-to-end with a **deterministic mock
extractor** (`llm_provider: mock` is stamped on every artifact — plumbing is
proven, extraction quality is Phase 1) and a **mock CRM** (the Twenty REST
adapter ships, verified against the local fork's source; live integration is
Phase 2).

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

python -m relationship_intel.cli run-demo
```

`run-demo` ingests the three sample transcripts, writes the vault, syncs the
mock CRM, and generates the weekly plan. Then look at:

| Artifact | Where |
|---|---|
| Obsidian vault | `output/obsidian-vault/relationship-intelligence/` (open in Obsidian: point a vault at `output/obsidian-vault`) |
| Weekly plan (Markdown + JSON) | `.../weekly-plans/2026-Wnn-james-succession-plan.{md,json}` |
| Contract-1 department report | `.../reports/CRM-YYYY-MM-DD.json` |
| Canonical store (SQLite) | `output/relationship_intel.db` |
| Mock CRM records | `output/mock_crm/*.json` |

## Commands

```bash
python -m relationship_intel.cli init                 # create store + vault skeleton
python -m relationship_intel.cli ingest               # defaults to TRANSCRIPTS_INBOX_DIR
python -m relationship_intel.cli ingest --source examples/transcripts
python -m relationship_intel.cli ingest --source-type granola --created-after 2026-07-01
python -m relationship_intel.cli sync-crm --crm mock  # or --crm twenty (needs TWENTY_API_KEY)
python -m relationship_intel.cli weekly-plan --owner James --week-start 2026-07-06
python -m relationship_intel.cli query who-to-call --json
python -m relationship_intel.cli run-demo
```

Add `--json` to any command for machine-readable stdout. `query` supports
`pipeline`, `last-touch`, and `who-to-call`; all read from SQLite without an LLM.

Configuration via `.env` (copy `.env.example`). Weeks start **Monday**;
`weekly-plan` defaults to the current week's Monday. For the local go-live setup,
`TRANSCRIPTS_INBOX_DIR` should point at the vault's `transcripts-inbox` folder.

Daily automation is defined in
`launchd/com.stablemischief.relationship-intel.daily.plist`; it runs
`scripts/relationship-intel-daily.sh` at 7:30 AM, performing
`init -> ingest -> sync-crm`, plus `weekly-plan` on Mondays. Install with:

```bash
cp launchd/com.stablemischief.relationship-intel.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.stablemischief.relationship-intel.daily.plist
```

## Tests & CI

```bash
ruff check . && ruff format --check . && pytest
```

The suite includes three structural security tests: no outbound-send capability
anywhere, no transcript content in logs, and CRM notes carry summaries + vault
links but never evidence snippets.

## Docs

- [`docs/architecture.md`](docs/architecture.md) — the governing spec (7 layers, ORD-0003 compliance, phasing)
- [`docs/data-model.md`](docs/data-model.md) — schemas, enums, entity-resolution rules
- [`docs/succession-lens.md`](docs/succession-lens.md) — the extraction lens and mock cue grammar
- [`docs/obsidian-archive.md`](docs/obsidian-archive.md) — vault layout, managed sections, backups
- [`docs/twenty-setup.md`](docs/twenty-setup.md) — connecting the real Twenty (port 3002, API key, stage mapping)
- [`docs/granola-ingestion.md`](docs/granola-ingestion.md) — connecting real Granola (Phase 3 options)
