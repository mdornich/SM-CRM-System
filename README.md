# Opportunity Engine

**A lead is an entity. An opportunity is an evidence-backed commercial hypothesis.**

Opportunity Engine turns business evidence into reviewable commercial hypotheses for
multiple products. It shares account and person identity, source evidence, and observations;
Product Packs supply the criteria and interpretation for each offering.

For example, the same firm could be a candidate for succession advice and a workflow
automation audit. Those are separate hypotheses, supported by shared evidence—not one
lead record with a single product score.

**Succession is Product Pack #1.** The existing transcript-to-relationship-intelligence
pipeline remains the working default while the generic foundation is introduced additively.
The repository is still named `SM-CRM-System`, and the Python package and CLI remain
`relationship_intel`.

[Product Brief](docs/opportunity-engine/PRODUCT_BRIEF.md) ·
[PRD](docs/opportunity-engine/PRD.md) ·
[Architecture & migration](docs/opportunity-engine/ARCHITECTURE_MIGRATION.md) ·
[Full design package](docs/opportunity-engine/README.md)

## What works today

| Area | Current capability |
|---|---|
| Transcript workflow | Local-file and Granola intake, evidence-backed extraction, deterministic entity resolution, and duplicate detection |
| Human review | Review queue/UI, reviewer corrections, and approval-gated CRM sync |
| CRM and archive | Twenty API adapter, mock CRM, Obsidian/Cairns evidence archive, and reviewed memory-promotion proposals |
| Planning | Weekly follow-up plans, drafts, feedback, deterministic queries, and Contract-1 reports for 980labsOS |
| Generic foundation | Versioned products/packs, neutral evidence and observations, product signals, and multiple hypotheses per account/person |
| Compatibility | Explicit projection of supported legacy Succession profiles into generic shadow state |
| Evaluation | Existing transcript evaluation plus a generic gold-set format and two Product Pack implementations |

The generic foundation is **opt-in**. Opening the store creates additive `oe_*` tables;
the default transcript workflow still uses its existing models. Generic hypotheses are
not automatically backfilled, rendered into the archive, exported to Twenty, or added
to weekly plans. They begin as unreviewed hypotheses, with no approval-transition API.

The second pack, **Workflow Automation Audit**, is a synthetic architecture fixture for
20–250 employee professional-services firms. It exercises a different ICP and signal set;
it is not an approved commercial offering. Mock extraction and synthetic evaluation prove
software behavior, not real-world extraction accuracy or commercial qualification quality.

## How it fits together

```text
Source evidence → Neutral observations → Product Pack interpretation
                                              ↓
                                      Product-specific signals
                                              ↓
                                   Evidence-backed hypotheses
                                              ↓
                           Human validation and engagement (next)
```

- **Opportunity Engine** owns commercial identity, evidence, observations, signals,
  hypotheses, qualification, and the future engagement/learning workflow. Deterministic
  code owns canonical writes, identity resolution, score arithmetic, and transition rules.
- **Product Packs** own product-specific ICPs, exclusions, signals, evidence requirements,
  scoring policies, and the eventual offers, stakeholder maps, and messaging policies.
- **Twenty** is the human-facing CRM and system of engagement, accessed through supported
  APIs. It receives approved operational records and summaries from the existing pipeline.
- **SQLite** holds canonical operational state. **Obsidian/Cairns** holds the evidence archive
  and reviewed memory outputs.
- **980labsOS** remains the control plane for task execution, model routing, permissions,
  budgets, secrets, scheduling, and audit. Agents propose bounded research, extraction,
  and synthesis; they do not directly mutate canonical state.

The transition preserves the existing pipeline. There is no new outbound-send capability,
external discovery/enrichment provider, or database-platform migration in this foundation.

## Quick start: existing Succession workflow

Use Python 3.11+ in a development checkout; CI uses Python 3.12.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

LLM_PROVIDER=mock CRM_PROVIDER=mock python -m relationship_intel.cli run-demo
```

With default development paths, the demo ingests three sample transcripts, writes the
archive, attempts mock CRM sync under the configured review gate, and generates a weekly
plan. `CRM_REVIEW_REQUIRED` defaults to `true`; pending items need approval before sync.

| Artifact | Default location |
|---|---|
| Evidence archive | `output/obsidian-vault/relationship-intelligence/` |
| Weekly plans | `output/obsidian-vault/relationship-intelligence/weekly-plans/` |
| Contract-1 reports | `output/obsidian-vault/relationship-intelligence/reports/` |
| SQLite operational store | `output/relationship_intel.db` |
| Mock CRM output | `output/mock_crm/` |

Generated state belongs under `output/` and is not committed. To inspect and approve the
demo's CRM candidates, run `review-ui`, then `sync-crm --crm mock` after review.

## Run the generic evaluation

```bash
python -m relationship_intel.opportunity_engine.evaluation --source examples/opportunity-engine
```

This evaluates six synthetic development cases across Succession and Workflow Audit without
provider credentials. It reports classifications, signal expectations, score bounds, citation
integrity, and signal precision/recall. Exit codes: `0` for passing expectations, `1` for failed
expectations, and `2` for invalid input. It does not ingest into the operational store.

The foundation's repository, pack registry, hypothesis service, and optional legacy projection
are Python APIs. See the [Product Pack contract](docs/opportunity-engine/PRODUCT_PACK_CONTRACT.md)
and [API contracts](docs/opportunity-engine/EVENT_API_CONTRACTS.md) for their boundaries.

## Existing CLI commands

```bash
python -m relationship_intel.cli init
python -m relationship_intel.cli ingest --source examples/transcripts
python -m relationship_intel.cli ingest --source-type granola --created-after 2026-07-01
python -m relationship_intel.cli review-queue --json
python -m relationship_intel.cli review-ui --port 8765
python -m relationship_intel.cli sync-crm --crm mock
python -m relationship_intel.cli weekly-plan --owner James
python -m relationship_intel.cli report --json
python -m relationship_intel.cli query who-to-call --json
python -m relationship_intel.cli doctor --json
python -m relationship_intel.cli eval --source redacted-evals --json
```

CLI commands accept `--json` for structured output where applicable. `query` supports
`pipeline`, `last-touch`, and `who-to-call`; these read SQLite without an LLM. `doctor`
checks local configuration and configured service readiness. The existing `eval` command
uses transcript fixtures with `expected.profiles` frontmatter; it remains separate from
the generic evaluation above. Weekly plans use Monday as the start of the week.

## Configuration and deployment

For local development, copy `.env.example` to `.env` and choose explicit output paths.
Mock is the default extraction and CRM provider. Optional extraction adapters support
`LLM_PROVIDER=codex` with local CLI authentication, or `LLM_PROVIDER=anthropic` with
`ANTHROPIC_API_KEY`; `CODEX_MODEL` and `ANTHROPIC_MODEL` provide model overrides.
For live Twenty sync, configure the API URL/key and retain the review gate.

The Mac mini deployment uses injected secrets rather than a `.env` file; its setup is below.
Deployment and operational details live in:

- [Daily scheduling and review gate](docs/deployment/launchd-daily.md)
- [Docker/Coolify deployment](docs/deployment/coolify.md)
- [Twenty setup](docs/twenty-setup.md)
- [Granola and local-file intake](docs/granola-ingestion.md)
- [First real ingest checklist](docs/real-ingest-checklist.md)

`scripts/fleet-crm-source-report.sh` emits the current Contract-1 report for the 980labsOS
`crm-source` integration. Generic hypotheses do not yet change that report.

## Mac mini review gate (980labsOS Phase 13A S1 §5.2)

The production checkout is on the **Mac mini** at
`/Users/980macmini/Documents/GitHub/SM-CRM-System`, alongside Twenty
(`http://127.0.0.1:3002`). Every shell entrypoint in `scripts/` resolves its repo
root from its own location (`scripts/_repo-env.sh`), so the same scripts run on
either machine.

**There is no `.env` on the mini and none should be created.** Secrets are
rendered by the 980labsOS 8D Infisical Agent and injected for one child process
by `with-8d-env.sh`. `scripts/_repo-env.sh` merges `.env` at the **lowest**
precedence and only when the file exists, so on a dev machine that does have one
the injected values still win — an unconditional shell-level load would clobber
them before Python ever ran. `load_settings()` then reads `os.environ`.

Run anything on the mini like this:

```bash
~/Documents/GitHub/980labsOS-deploy/scripts/with-8d-env.sh -- \
  ~/Documents/GitHub/SM-CRM-System/.venv/bin/python -m relationship_intel.cli review-queue --json
```

The always-on review gate itself is
`scripts/launchd/com.stablemischief.smcrm-reviewgate.plist` →
`scripts/review-gate.sh` (re-execs through `with-8d-env.sh`, then serves
`review-ui` on `127.0.0.1:8765`). It **refuses to start** (exit 78) when the
wrapper is missing or `TWENTY_API_KEY` is empty, rather than coming up green
backed by the mock CRM — an approval gate that gates nothing is worse than one
that is down. `KeepAlive` is a dictionary (`SuccessfulExit` + `Crashed`), not
`<true/>`: launchd ORs those conditions and stops the job when neither matches,
so a configuration refusal stays stopped instead of respawning every 10s
forever, while a clean exit or a signal death still brings the gate back. After
fixing the configuration, `launchctl kickstart -k gui/$(id -u)/com.stablemischief.smcrm-reviewgate`. It also creates its own log directory, because launchd creates the
log file but not its parent.

This plist **replaces `com.stablemischief.smcrm-reviewui.plist`**, removed in the
same change. Both bound `127.0.0.1:8765`; with `KeepAlive` and a 10s
`ThrottleInterval`, loading both leaves one crash-looping indefinitely. Unload
the old one first:

```bash
launchctl bootout gui/$(id -u)/com.stablemischief.smcrm-reviewui 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.stablemischief.smcrm-reviewui.plist

cp scripts/launchd/com.stablemischief.smcrm-reviewgate.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.stablemischief.smcrm-reviewgate.plist
launchctl list com.stablemischief.smcrm-reviewgate
```

Logs land in `~/.980labsOS/smcrm/review-gate.{out,err}.log`. The job is
registered in 980labsOS `docs/standards/recurring-job-routing.md`.

## Tests and CI

```bash
ruff check . && ruff format --check . && pytest
```

Shell entrypoint tests also require `zsh`; CI installs it explicitly. Tests cover the
legacy CLI/demo, extraction, identity, review, CRM sync, archive preservation, planning,
Contract-1, and deployment scripts. Foundation tests add evidence lineage, multiple products
and episodes, immutable replay, atomic rollback, additive migration, and negative pack cases.
Structural checks protect the no-send boundary and keep source evidence out of CRM notes/logs.

See the [test and evaluation plan](docs/opportunity-engine/TEST_EVALUATION_PLAN.md) for
recorded validation and the distinction between development fixtures and real acceptance data.

## Next milestones

1. Add neutral intake and a resumable, explicitly invoked shadow projection over existing transcripts.
2. Validate attribution and qualification using independently labeled real examples from two products.
3. Define generic lifecycle/review decisions and product-aware archive/CRM views.
4. Consider budgeted discovery/enrichment providers only after the domain and second pack are proven.

Production calibration, full lifecycle transitions, generic CRM export, cost accounting,
and outreach/reply execution remain future work. Human approval remains the default for
any future first-touch outbound capability.

The north-star metric is **validated commercial opportunities discovered per unit of
research + outreach cost**. It is not yet measured by the foundation.

## Documentation

Start with the [Opportunity Engine design index](docs/opportunity-engine/README.md).
It links the Product Brief, PRD, migration plan, schema, Product Pack and event/API contracts,
scoring/calibration spec, provider matrix, test plan, ADRs, open questions, and backlog.

The existing pipeline's governing documents remain in place during reconciliation:

- [Pipeline architecture](docs/architecture.md) and [source contract](docs/build-prompt.md)
- [Existing data model](docs/data-model.md) and [Succession lens](docs/succession-lens.md)
- [Obsidian/Cairns archive](docs/obsidian-archive.md)

For implementation sequencing and unresolved decisions, use the
[backlog](docs/opportunity-engine/IMPLEMENTATION_BACKLOG.md) and
[open questions](docs/opportunity-engine/OPEN_QUESTIONS.md).
