# SM-CRM-System — Relationship Intelligence Pipeline Architecture

**Status:** Draft v2 — reflects shipped code as of 2026-07-06
**Date:** 2026-07-06 (v1 was 2026-07-04)
**Owner:** Mitch Dornich (980Labs / Stable Mischief)
**First use case:** Succession pipeline for James Whitfield

**v2 changelog (2026-07-06):** review-first Twenty sync is live (§3.9);
CodexExecClient added as a third LLM provider (§3.2, §6); managed-marker
granularity relaxed to block-level (§3.5, gh #8); Contract-1 metrics emit
both stage-shaped and group-shaped counts (§3.7, gh #12); `review_status`
symmetric across all intelligence artifacts (§3.5, gh #11); daily
scheduler via launchd (§4, gh #5); Twenty stage filter for unmappable
stages (§3.9, gh #3); default review-gate flipped on (§6, gh #4);
push-on-approve wiring in the review UI (§3.9, gh #6); Obsidian
template drift closed against docs/build-prompt.md (gh #10); Twenty
`tag_record` now raises NotImplementedError, CLI `report --json` split
from human summary (gh #14).

---

## 1. What this system is

A reusable **transcript-to-relationship-intelligence pipeline**. It turns meeting
transcripts into (a) durable, evidence-backed relationship intelligence in an
Obsidian-compatible vault, (b) operational pipeline records in a CRM (Twenty),
and (c) actionable weekly follow-up plans.

It is **not** a CRM. Twenty is the CRM. This system is the intelligence layer
that feeds it — and, critically, it is designed from day one to run as a
**department agent** in the 980Labs OS fleet, so that Dex (chief of staff)
communicates with it rather than operating a CRM directly.

### Three-plane model

| Plane | System | Role |
|---|---|---|
| Evidence / memory | Obsidian vault (Cairns-compatible) | Film room & evidence locker: transcripts, intelligence cards, reasoning trails, audit history |
| Operations | Twenty CRM | Field & scoreboard: contacts, companies, opportunities, stages, tasks, due dates |
| Reasoning | AI agents (this pipeline; Dex/Thane above it) | Coach: extraction, classification, planning, drafting |

### Core principles

1. **Evidence-first.** Every classification carries evidence snippets and a
   confidence score. Nothing in the CRM exists that can't be traced back to a
   transcript in the vault.
2. **Conservative warmth.** The extraction lens is biased against overstating
   interest. Unknown means `unknown`/`null`, never a guess.
3. **CRM-agnostic core.** The canonical store and extraction layer know nothing
   about Twenty. Twenty is one adapter behind a `CRMAdapter` interface.
4. **Additive, idempotent writes everywhere.** Re-running the pipeline on the
   same input changes nothing. No destructive CRM operations. Manual edits to
   vault notes survive re-runs.
5. **Proposals, not actions.** The system drafts messages and plans; it never
   sends anything externally. A human (or a future approval layer) executes.
6. **Agent-native.** Outputs conform to 980Labs OS contracts (Contract-1
   department reports) so Dex can consume them without special-casing.

---

## 2. System context and topology

### Repositories

| Repo | Path | Role |
|---|---|---|
| **SM-CRM-System** (this repo) | `~/Documents/GitHub/SM-CRM-System` | The pipeline. All code, docs, tests, sample data live here at repo root. |
| **twenty** (fork of twentyhq/twenty) | `~/Documents/GitHub/twenty` | Self-hosted CRM backend. **Read-only reference + runtime dependency.** Never modified by this project; we track upstream evolution by pulling the fork. Pinned reference: commit `1a60d4ea` (2026-07-04, v0.2.1). |
| **980labsOS** | `~/GitHub/980labsOS` | Agent fleet home. Phase 4 target: this system registers there as the `crm-source` department agent. Not touched in the POC. |

### Runtime topology (POC → production)

```
                      ┌────────────────────────────────────────────┐
                      │                Dex (chief of staff)         │
                      │   delegate_task (sync) / Kanban (async)     │
                      │   morning-brief fan-out (Contract-1)        │
                      └───────────────┬────────────────────────────┘
                                      │  Phase 4
┌──────────────┐   ┌──────────────────▼───────────────────────────┐   ┌─────────────┐
│ Transcript   │   │        SM-CRM-System pipeline (Python)        │   │ Twenty CRM  │
│ sources      ├──▶│  intake → extraction → canonical store        ├──▶│ (Docker,    │
│ • local dir  │   │  → obsidian writer → crm sync → weekly plan   │   │  localhost) │
│ • Granola API│   └──────────┬───────────────────┬───────────────┘   └─────────────┘
│   (later)    │              │                   │
└──────────────┘   ┌──────────▼─────────┐   ┌─────▼──────────────┐
                   │ Obsidian vault      │   │ SQLite canonical   │
                   │ (evidence archive)  │   │ store              │
                   └────────────────────┘   └────────────────────┘
```

The pipeline is a CLI-invoked batch process in the POC. In later phases the
same code runs as a scheduled fleet agent (980labsOS `scripts/agent-fleet`
registry) and/or responds to Dex `delegate_task` calls for ad-hoc queries
("what's the last touch with Bob Smith?").

---

## 3. Layer architecture

Seven layers, each with a narrow contract. POC scope noted per layer.

### 3.1 Transcript Intake Layer (`src/relationship_intel/intake/`)

**Contract:** produce `RawTranscript` objects (source system, source id, title,
date, attendees if known, raw text, content hash) from any source.

- `local_folder.py` — reads `.md`/`.txt` transcripts from a directory. Parses
  optional YAML frontmatter for metadata; falls back to filename conventions
  (`YYYY-MM-DD-source-title.md`). **POC: fully working.**
- `granola_api.py` — pluggable `TranscriptSource` implementation for Granola.
  Lists notes with cursor pagination, fetches note transcripts, and supports
  created/updated/folder filters. Granola access options (API, export folder,
  Zapier, MCP) are documented in `docs/granola-ingestion.md`; local folder
  ingestion is the contractual fallback forever (it also covers manual paste,
  Otter exports, etc.).

**Dedupe at the gate:** intake computes `transcript_hash = sha256(normalized
text)`. A hash already present in the canonical store is skipped (logged, not
reprocessed).

### 3.2 Extraction / Lead Intelligence Layer (`src/relationship_intel/extraction/`)

**Contract:** `RawTranscript → ExtractedRelationshipIntelligence` (Pydantic).

- `schemas.py` — all Pydantic models (§5).
- `succession_lens.py` — the Succession extraction lens: the system prompt,
  classification rules, and warmth-scoring rubric, stored as **data/config,
  not code**, so future lenses (client development, investor relations,
  referral partners) are new lens files, not new pipelines.
- `llm_client.py` — provider-agnostic LLM interface: `complete(system, user,
  response_schema) -> dict`. Implementations: `MockLLMClient` (POC default),
  `AnthropicClient` (Phase 1, code present but inert without key), and
  `CodexExecClient` (`LLM_PROVIDER=codex`) which shells out to
  `codex exec --sandbox read-only` and lets a developer drive extraction
  through their own Codex CLI subscription instead of the paid API. All
  three conform to the same `complete()` contract; the extractor doesn't
  care which is wired.
- `extractor.py` — orchestrates lens + client, validates output against
  schemas, enforces the anti-hallucination rules (evidence required for every
  classification; nulls for unknowns).

**Mock extraction strategy (important for POC honesty):** the mock LLM is a
deterministic rule-based extractor keyed off structured cues in the sample
transcripts (explicit names, quoted signal phrases). It exercises the *entire*
schema — every field, every enum — so the pipeline, storage, vault writer, CRM
sync, and planner are fully proven. What it does **not** prove is extraction
quality on messy real transcripts; that is explicitly Phase 1. The demo output
labels itself `llm_provider: mock` in every artifact so nothing masquerades as
real intelligence.

### 3.3 Internal Canonical Store (`src/relationship_intel/store/`)

**Contract:** the single source of truth for entity identity and pipeline
state. SQLite (`output/relationship_intel.db`), accessed only through
`repository.py`.

Tables: `transcripts`, `people`, `companies`, `opportunities`,
`lead_profiles`, `interactions` (person/company ↔ transcript join with
evidence), `crm_sync_state` (local id ↔ CRM id ↔ last-synced hash),
`plans`.

Why a canonical store at all (vs. "Obsidian is the database"): entity
resolution, idempotency bookkeeping, and CRM sync state need transactional
queries. Markdown is the *rendering* of this store for humans and for Dex's
vault search — never the source of truth for identity.

**Scope boundary (ORD-0003 compliance):** this store holds *pipeline
operational state* — prospect/entity dedupe keys, sync hashes, stage
tracking. It is not, and must never become, Mitch's canonical
knowledge/identity memory; Cairns keeps that role. Relationship intelligence
only enters canonical memory (Vault A) through the review-status promotion
flow (§3.5), never automatically.

### 3.4 Entity Resolution (inside store layer)

The hardest correctness problem in the system; the rule is fixed here:

1. **Email match** (case-insensitive, exact) → same person. Highest authority.
2. Else **normalized name + company match** → same person. Normalization:
   lowercase, strip punctuation/honorifics, collapse whitespace.
3. Else **normalized name match with no company conflict** → same person,
   flagged `identity_confidence: medium` for human review.
4. Else → new person, flagged `needs_review: true` if the name is similar
   (edit distance ≤ 2) to an existing person.

Companies: normalized name match (strip Inc/LLC/Co/etc.); website domain match
overrides name. Merges are **never automatic** beyond these rules — ambiguous
cases surface in the weekly plan's "needs review" section rather than being
silently merged or duplicated.

### 3.5 Obsidian Intelligence Archive Layer (`src/relationship_intel/obsidian/`)

**Contract:** render canonical-store state into an Obsidian-compatible vault.
Output path configurable (`OBSIDIAN_VAULT_PATH`). Two modes:

**`plain` mode (POC default)** — the structure from the build prompt:

```
<vault>/relationship-intelligence/
  README.md
  transcripts/YYYY-MM-DD-source-title.md
  people/<person-slug>.md
  companies/<company-slug>.md
  opportunities/<opportunity-slug>.md
  weekly-plans/YYYY-WW-<owner>-succession-plan.md
  indexes/{people,companies,opportunities,transcript-index}.jsonl
  reports/CRM-YYYY-MM-DD.json          ← Contract-1 department report (§3.7)
```

**`cairns` mode (Phase 4)** — maps the same content onto the 980labsOS Cairns
convention so it lands in Dex's memory model natively:

| Pipeline artifact | Cairns layer | Rationale |
|---|---|---|
| Raw transcripts + raw extraction JSON | **L3** (`raw/`) | Immutable source evidence, citable |
| Person / company / opportunity intelligence cards | **L2** (`card-catalog/L2/`) | Chain-of-Density cards, one per entity, tagged, backlinked |
| `succession-pipeline.md` waypoint (top plays, pipeline shape, hot list) | **L1** (`cairns/L1/`) | The guidepost agents read first |

Long-term home is a `relationships` corpus in Vault A
(`~/Documents/second-brain`), Dex's canonical memory — which makes every
intelligence card searchable via Dex's existing `vault-search` skill with zero
extra integration. The POC writes to `./output/obsidian-vault` in `plain`
mode; the writer treats mode + root as pure configuration so the switch is a
config change, not a refactor.

**Review-status model (per ORD-0003 §Memory):** every AI-generated
intelligence artifact that could affect future planning — person, company,
opportunity, and lead-profile records, and weekly plans — carries frontmatter
`review_status: unreviewed | reviewed | corrected | confirmed`, defaulting to
`unreviewed`. As of v2 the column exists on all four artifact tables and the
note templates read the DB value (gh #11 — v1 shipped the column on `people`
only; migrations add it to companies/opportunities/lead_profiles on next
connect). Unreviewed artifacts may inform recommendations but are always
labeled as AI synthesis, never treated as canonical fact. Corrections
preserve what changed and why (the Idempotent-write mechanism below keeps
originals visible in `.ri-backups/`). Only `reviewed`/`corrected`/
`confirmed` content is a candidate for promotion into canonical memory
(Vault A L1/L2) in Phase 4 — unreviewed synthesis never promotes
automatically. `Repository.set_review_status(table, id, status)` gives future
UI/CLI a validated write path.

**Idempotent-write mechanism (concrete, testable):**

- Every generated note carries frontmatter `generated_by: relationship-intel`
  and `content_hash` of its AI-managed content.
- AI-managed content lives between markers:
  `<!-- ri:begin main -->` … `<!-- ri:end main -->` — a **single block-level
  marker** covering the whole managed body, not per-section markers. (Draft
  v1 sketched per-section markers; v2 relaxes to block-level after real
  usage confirmed the `.ri-backups/` safety net is enough and per-section
  granularity added complexity without a demonstrated user need. gh #8.)
- On rewrite: text outside the marker is preserved verbatim; the block is
  replaced only when its content hash changed; a `.bak` copy is written to
  `<vault>/.ri-backups/<path>/<timestamp>.md` before any file that contains
  out-of-marker edits is touched.
- Re-running on unchanged input is a byte-for-byte no-op (asserted in tests).

**Accepted trade-offs of block-level markers + capped backups:**

1. *Hand-edits INSIDE the managed block get overwritten on the next rewrite.*
   The intended workflow is: hand-edit OUTSIDE the markers; treat the managed
   block as AI-owned. If you edit inside anyway, the change lands in
   `.ri-backups/` and the operator has to reconcile.
2. *`.ri-backups/` is capped at 10 backups per file* (a bounded-storage
   choice). This is NOT the ORD-0003 audit trail of record — git history of
   the vault is. If the vault is under version control (recommended for
   James's real deployment), the audit trail is unbounded via `git log`;
   `.ri-backups/` is only a short-term recovery window for accidental
   overwrites between commits.

### 3.6 CRM Adapter Layer (`src/relationship_intel/crm/`)

**Contract:** `base.py` defines the abstract interface; the pipeline core
imports only this.

```python
class CRMAdapter(ABC):
    def ensure_schema() -> dict                   # provision custom fields (v2)
    def find_or_create_contact(person) -> CRMRef
    def find_or_create_company(company) -> CRMRef
    def create_or_update_opportunity(opportunity) -> CRMRef
    def attach_note(ref, note) -> None            # concise summary + vault link back
    def create_task(ref, task) -> CRMRef          # follow-ups with due dates
    def tag_record(ref, tags) -> None             # v2: Twenty raises NotImplemented (gh #14)
    def get_pipeline_items(owner, stages) -> list[PipelineItem]
    def health_check() -> AdapterStatus
```

`ensure_schema()` (v2) is called at the top of every `sync_to_crm` run. The
Twenty adapter uses it to auto-provision the succession-specific custom
fields (`successionSignalScore`, `leadType`, `timingWindow`) on the
opportunity object; the mock adapter no-ops. This makes first-run sync
against a fresh Twenty workspace safe without a manual metadata setup step.

Design rules:

- **Additive/update-safe only.** No delete methods exist on the interface.
- **Idempotency** via `crm_sync_state`: each local record stores the CRM id
  and the hash of what was last pushed; unchanged records are skipped.
- **Twenty gets summaries, not evidence.** Notes pushed to Twenty are concise
  operational summaries with an `obsidian://` (or file-path) link back to the
  evidence note. Transcripts never go into the CRM.

Implementations:

- `mock_adapter.py` — **POC: fully working.** JSON-file-backed
  (`output/mock_crm/`), implements the full interface including
  `get_pipeline_items`, so the weekly planner runs against it exactly as it
  will against Twenty.
- `twenty_adapter.py` — targets the **local fork** at
  `~/Documents/GitHub/twenty` (pin: `1a60d4ea` / v0.2.1). Twenty exposes a
  GraphQL API and a REST API generated from the workspace schema
  (`TWENTY_API_URL` — **`http://localhost:3002` on this machine**, not the
  stock 3000: the local install remaps ports because other services own the
  defaults (backend 3002, frontend 3001, Postgres 5433, Redis 6380); API key
  from Settings → Developers, `TWENTY_API_KEY` env var). Object mapping: Person → `people`,
  Company → `companies`, Opportunity → `opportunities` (custom fields for
  `succession_signal_score`, `lead_type`, `timing_window`), Task → `tasks`,
  Note → `notes`. **POC: as complete as current docs allow, exercised only by
  `health_check` against the local instance if it's up; full integration is
  Phase 2 with the running fork.** Logs request/response shapes, never
  secrets; degrades to a clear error (not a crash) when unconfigured.
- **Watch item:** the fork's latest commit adds an MCP setup screen — Twenty
  is gaining native MCP support. If it stabilizes, a future
  `twenty_mcp_adapter` may replace hand-rolled REST/GraphQL calls, and Dex
  could even address Twenty directly for simple lookups. Decision deferred;
  the `CRMAdapter` interface is the hedge.

### 3.7 Weekly Planning Layer (`src/relationship_intel/planning/`)

**Contract:** canonical store + CRM pipeline state → three artifacts per run:

1. **Markdown plan** (`weekly-plans/YYYY-WW-james-succession-plan.md`) —
   human-readable, action-oriented, using the section structure from the build
   prompt (Top Plays / Overdue / Warm Follow-Ups / Cold Retouches / Referral
   Nurture / Stalled / Needs Review / Risks). Every item: contact, company,
   stage, priority, *why now*, next action, suggested message draft, due
   window, evidence wikilink, CRM link.
2. **Plan JSON** — the same content, machine-readable, for downstream agents.
3. **Contract-1 department report** (`reports/CRM-YYYY-MM-DD.json`). Note:
   980labsOS currently has **two divergent Contract-1 shapes** — the
   morning-brief template (`department`, `top_decisions[]`,
   `flagged_anomalies[]`, `yesterday_followups[]`, `tomorrow_focus[]`) and the
   fleet runtime validator
   (`scripts/agent-fleet/contracts.py::validate_agent_report_v1`), which
   requires `agent`, `report_date`, `headline` and `confidence` as
   **non-empty strings**, `metrics` as an object, and `findings[]` +
   `decisions[]` as arrays (canonical example:
   `scripts/agent-fleet/agents/smoke_test.sh`). The validator ignores extra
   fields, so this system emits the **union**:

   ```json
   {
     "agent": "crm-source", "department": "CRM",
     "report_date": "YYYY-MM-DD", "headline": "…",
     "confidence": "high|medium|low",
     "metrics": {
       "pipeline_counts_by_stage": {},
       "overdue": 0,
       "pipeline_counts_by_group": {},
       "total_tracked_people": 0,
       "llm_provider": "mock"
     },
     "findings": [], "decisions": [],
     "top_decisions": [], "flagged_anomalies": [],
     "yesterday_followups": [], "tomorrow_focus": []
   }
   ```

   v2 (gh #12) emits BOTH `pipeline_counts_by_stage` (spec-shaped, deduped
   by person via `weekly_plan.build_plan`) AND `pipeline_counts_by_group`
   (richer for humans reading the report locally). Top-level `overdue` is
   the same integer as `len(groups["overdue"])`. The fleet validator
   ignores extras, so the union shape stays fleet-compatible.

   This passes `validate_agent_report_v1` verbatim **and** slots into the
   morning-brief synthesizer without special-casing. Our test suite validates
   emitted reports with a vendored copy of the same validator logic.

**Week convention:** weeks start **Monday**. `weekly-plan` defaults
`--week-start` to the Monday of the current ISO week (e.g. run on Sat
2026-07-04 → week of Mon 2026-06-29); `--week-start` overrides for planning
the upcoming week.

Prioritization rubric (deterministic, testable): overdue items first, then
`urgency × succession_signal_score` descending within groups; stalled = no
interaction in `stall_threshold_days` (default 21); retouch cadence from
`recommended_cadence` on the lead profile.

`message_drafts.py` produces suggested messages **as drafts only** — plain
text in the plan, never dispatched. Voice/tone calibration is a Phase 1+
concern (candidate: James's sent-mail samples as few-shot).

### 3.8 Human Approval / Execution Layer

**POC scope (deliberately minimal, per decision 2026-07-04):** approval *is*
"James reads the weekly plan and acts." The system enforces the boundary
structurally: no email/message sending code exists anywhere in the codebase,
and a test asserts no outbound-send imports/calls exist.

**Designed-in for later (schema, not behavior):** every
`recommended_crm_action` and plan item carries
`approval_status: proposed | approved | rejected | executed` (POC: everything
is `proposed`, and CRM sync only executes record-upserts, which are
classified pre-authorized-additive). The state machine and UI/CLI land here
later without schema migration.

**ORD-0003 authority mapping (explicit):** the pipeline operates strictly at
Levels 0–3 of the authority model
(`980labsOS/docs/ord/ORD-0003-authority-and-approval-model.md`):

| ORD-0003 level | What this system does there |
|---|---|
| 0 — Observe | Read transcripts, canonical store, CRM pipeline state |
| 1 — Recommend | Lead classification, next-best-action, weekly-plan priorities |
| 2 — Draft | Suggested messages and plans — **always labeled as drafts** in output, per the "drafts must be clearly marked" rule |
| 3 — Pre-authorized execute | Additive-only writes within its bounded scope: its own vault corpus, its own SQLite store, additive CRM upserts to the Stable Mischief workspace |
| 4 — Explicit approval | Nothing today. Future candidates (sending messages, canonical-memory promotion) will use the ORD-0003 approval-request format: Action / Scope / Reason / Risk / Rollback / Evidence |
| 5 — Never | No sending as Mitch/James, no fabricated evidence (evidence-required rule), no authority self-expansion, no moving canonical memory out of Cairns |

The Level-5 "expose uncertainty instead of acting through it" principle is
implemented structurally: confidence scores, `unknown`/`null` enums, and the
conservative-warmth lens rules.

### 3.9 Review + Approval Layer (`src/relationship_intel/review.py`)

Added in v2. The review-first flow gates CRM sync on human approval and is
the default posture (`CRM_REVIEW_REQUIRED=true`).

- **`crm_review_items` table** — one row per proposal the pipeline wants to
  push to the CRM (`object_type` ∈ {company, person, person_note,
  person_task, opportunity}, `local_id`, `status`, editable `payload_json`,
  optional `reason` warning). `rebuild_review_queue(repo)` fires at the end
  of every ingest; approve/reject/vault-only writes come from the local UI.
- **`review-ui` CLI** — `python -m relationship_intel review-ui` boots a
  stdlib HTTP server (`127.0.0.1:8765` by default). The page groups
  proposals by candidate person with a "Twenty write preview" pane;
  operators can approve-all/vault-only/reject-all per person, or edit
  individual field payloads.
- **Push-on-approve (gh #6, Option 1)** — clicking Approve on a bundle
  flips the review-item statuses AND fires `sync_to_crm(approved_only=True)`
  in the same request. Reject and Vault-only never push. On sync failure
  the approved-status writes are rolled back (compensating action; not a
  real DB transaction — see review.py for the concurrency + atomicity
  trade-offs accepted for the single-operator local UI).
- **`review-queue` CLI** — machine-readable snapshot of the pending queue
  (`review-queue --json`). Used by external automation / Dex to check the
  queue state without booting the UI.
- **CRM-side gate** — `sync_to_crm` with `approved_only=True` (default in
  production via `settings.crm_review_required`) skips any entity whose
  review status is not `approved` and reports the count under
  `stats["skipped_not_approved"]`. Idempotent hash-match skips are tracked
  separately under `stats["skipped"]` so a re-sync where everything's
  already in the CRM doesn't misfire the "awaiting approval" hint.
- **Twenty stage safety (gh #3)** — `sync_to_crm` filters opportunities
  whose reviewed stage is in `NO_OPP_STAGES` (`not_fit`, `stalled`,
  `closed_lost`) and reports them under `stats["skipped_by_stage"]`
  instead of crashing the loop on Twenty's stage-map lookup.

The review layer is deliberately **local-only** today. A cloud deployment
(§9 Phase 4+) will need multi-user concurrency handling and a real DB
transaction around the approve+sync sequence.

---

## 4. Dex / 980Labs OS integration contract

This system is built to become the **CRM department agent** in the fleet. The
Phase 4 integration surface now exists in 980labsOS:

| Fleet convention | This system provides |
|---|---|
| Contract-1 report (`agent_report_v1`) | Emitted by `report` and by `scripts/fleet-crm-source-report.sh` without writing vault/plans |
| Fleet registry entry (`scripts/agent-fleet/registry.json`) | 980labsOS registers `crm-source`, `kind: command`, `command: scripts/fleet-crm-source-report.sh`, `output_contract: agent_report_v1`, `authority_level: observe` |
| Skill for Dex dispatch (`.claude/skills/crm-source/SKILL.md`) | 980labsOS skill routes pipeline status, last-touch lookups, and "who should James call this week" to read-only CLI queries |
| Morning-brief fan-out (`.claude/commands/morning.md`) | 980labsOS includes `crm-source` in the parallel source list |
| Sync queries (`delegate_task`) | CLI `query` subcommand answering entity/last-touch/next-action questions from the canonical store in <1s (no LLM needed) |
| Async work (Kanban) | Nightly ingest + weekly plan generation as scheduled fleet jobs. Local Mac testing uses `scripts/launchd/com.stablemischief.smcrm-daily.plist` at 05:00 (see `docs/deployment/launchd-daily.md`); sync-crm is intentionally NOT on the scheduler — it fires from the review UI on approve |
| Memory integration | `cairns` vault mode writes L3 evidence and `unreviewed`-labeled L2 cards into Vault A → searchable by Dex's `vault-search` skill. **L1 waypoint updates are canonical-memory promotion** and are written as reviewable promotion proposals under `promotion-proposals/` (see `planning/promotion_proposal.py`), not applied directly — per the ORD-0003 rule that unreviewed synthesis never promotes automatically |
| Context.Assemble (emerging) | 980labsOS has `scripts/context/collectors/relationships.py` as an opt-in `relationships` source feeding the unified read model from `query who-to-call --json` |

The key architectural consequence **today**: the weekly planner and the
Contract-1 reporter are separate renderers over the same plan model, and the
CLI is factored so every human command has a machine-callable equivalent.
Dex never parses Markdown; humans never read JSON.

**Fleet-side ground rules (Phase 4):** when this system runs inside the
980labsOS fleet, it obeys that repo's hard rules — local agents invoked only
via `agents/_runtime/invoke.py`, and the ORD-0003 authority preflight
(`agents/_runtime/preflight_cli.py`) runs before action-bearing work. Until
then, the POC runs standalone in this repo and touches nothing in 980labsOS.

---

## 5. Data model (summary)

Full field-level definitions live in `docs/data-model.md` (build phase). The
Pydantic schema set is exactly the build prompt's, with these additions:

- `TranscriptMetadata`, `Person`, `Company`, `SuccessionLeadProfile`,
  `ConversationSummary`, `ExtractedRelationshipIntelligence` — as specified.
- **Added to `Person`/`Company`:** `identity_confidence: high|medium|low`,
  `needs_review: bool` (entity-resolution surface, §3.4).
- **Added to all extracted entities:** `llm_provider` + `lens_version`
  (provenance — mock output is always labeled mock).
- **Added to recommended actions / plan items:** `approval_status` (§3.8).
- **Added to all generated intelligence artifacts:** `review_status:
  unreviewed | reviewed | corrected | confirmed`, default `unreviewed`
  (ORD-0003 review-status model, §3.5).
- **`CRMRef`:** `{provider, object_type, crm_id, url}` — adapter-neutral
  handle stored in `crm_sync_state`.

Enums (`lead_type`, `stage`, `urgency`, `timing_window`) are closed
vocabularies defined once in `schemas.py`; the lens prompt, the store, and the
Twenty field mappings all reference them — one place to evolve.

---

## 6. Configuration

`.env.example` (v2 — reflects shipped code as of 2026-07-06):

```
# LLM — mock for plumbing; codex for local-CLI-driven; anthropic for API
LLM_PROVIDER=mock            # mock | codex | anthropic
CODEX_MODEL=                 # optional model override for the Codex CLI
ANTHROPIC_API_KEY=

# Obsidian
OBSIDIAN_VAULT_PATH=./output/obsidian-vault
OBSIDIAN_MODE=plain          # plain | cairns (cairns is Phase 4)
STORE_RAW_TRANSCRIPTS=true   # false → store hash + metadata + evidence only

# CRM
CRM_PROVIDER=mock            # mock | twenty
CRM_REVIEW_REQUIRED=true     # v2 default. sync-crm only pushes approved review items
TWENTY_API_URL=http://localhost:3002   # local fork's remapped backend port
TWENTY_API_KEY=

# Granola (Phase 3)
GRANOLA_API_KEY=

# Pipeline
TRANSCRIPTS_INBOX_DIR=./examples/transcripts
DEFAULT_OWNER=James
STALL_THRESHOLD_DAYS=21
```

---

## 7. Security & privacy

- Transcripts contain sensitive personal/business information. Full
  transcripts are never logged; log lines reference `transcript_hash` only.
- `STORE_RAW_TRANSCRIPTS=false` stores hash + metadata + evidence snippets
  only (snippets are the audit trail and are always kept).
- No outbound sending capability exists in the codebase (test-enforced, §3.8).
- No destructive CRM operations exist on the adapter interface (structural).
- Secrets via env only; `.env` gitignored; adapter logging redacts keys.
- `output/` is gitignored except `.gitkeep` — generated vault/DB/mock-CRM
  state never lands in version control.

---

## 8. Testing strategy

The build prompt's 12 test cases, organized by what they actually protect:

- **Extraction honesty** (tests 1–3, 11): warm prospect / referral-source /
  not-fit fixtures; unknown fields are null; every classification has
  evidence. Run against the mock LLM → deterministic.
- **Identity** (4–6): duplicate transcript no-ops; cross-transcript person and
  company resolution follow the §3.4 rules exactly.
- **Vault integrity** (7–8): notes render correctly; re-run is byte-identical;
  out-of-marker manual edits survive with backup.
- **Planning** (9): prioritization rubric ordering; Monday week math;
  Contract-1 report validates against `agent_report_v1` rules.
- **CRM safety** (10): mock adapter idempotency (second sync = zero writes).
- **Boundary** (12): no outbound-send capability, no delete methods.

CI = `pytest` + `ruff check` + `ruff format --check` (project convention:
that command set goes in this repo's `CLAUDE.md`).

---

## 9. Phasing

| Phase | Scope | Exit criterion |
|---|---|---|
| **0 — POC (now)** | Full pipeline, mock LLM, mock CRM, plain vault mode, sample transcripts, tests, Contract-1 emission | `python -m relationship_intel.cli run-demo` green end-to-end; all tests pass |
| **1 — Real extraction** | `AnthropicClient` live; lens tuned on real (redacted) Granola transcripts; message-draft voice | Extraction quality accepted by Mitch/James on ≥5 real transcripts |
| **2 — Real Twenty** | Fork running locally (Docker); `twenty_adapter` integration-tested; custom fields provisioned; pipeline stages configured | Sync of POC dataset visible and correct in Twenty UI |
| **3 — Real Granola** | API `TranscriptSource` shipped; folder/export fallback still supported | James's actual meetings flow in without manual copying once credentials/access are available |
| **4 — Fleet registration** | `cairns` vault mode into Vault A; registry entry; SKILL.md; morning-brief fan-out; `query` subcommand for delegate_task; Context.Assemble collector | Dex answers "who should James call this week?" from this system's report |
| **5+ — Reuse** | Second lens (client development or investor relations); approval-layer state machine; possible Twenty MCP adapter | New lens ships with zero pipeline-code changes |

---

## 10. Open questions (tracked, not blocking)

1. **Granola live access** — API key/workspace availability and 5-10 real
   James transcripts are still needed for acceptance; local folder covers until
   then.
2. **Promotion application workflow** — weekly plan generation writes
   reviewable L1 promotion proposals; remaining work is the future human/Dex
   workflow that applies or rejects a proposal. Ties into a Cairns L1
   `succession-pipeline.md` writer (gh #9), deferred to Phase 4.
3. **Approval-layer shape** — ORD-0003 authority tiers (analyst /
   principal / etc.) vs. the flat approve/reject queue shipped in v2
   (§3.9). v2 chose the flat model to unblock local usage; if cloud
   deployment introduces multi-role review, the `crm_review_items`
   schema will need a role/authority column and a matching gate in
   `sync_to_crm`. Deferred pending real-world review patterns.
4. **Multi-tenant review layer** — see the concurrency + atomicity
   caveats already documented in §3.9. Cloud deployment work should
   address both here and in the schema (question 3).
5. **Anthropic API model id + Claude Code CLI provider** — gh #2 and gh #7
   remain open. `AnthropicClient.MODEL` needs a valid current model id
   before Phase 1 can use the paid path; a `ClaudeCodeExecClient` mirror
   of `CodexExecClient` would let developers drive extraction through a
   Claude Max subscription.
6. **Thane's role** — currently unspecified vs. Dex. The Contract-1 +
   delegate_task surface serves any orchestrator; no coupling to Dex
   specifically.
