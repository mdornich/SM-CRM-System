# SM-CRM-System — Relationship Intelligence Pipeline Architecture

**Status:** Draft v1 — spec for review before build
**Date:** 2026-07-04
**Owner:** Mitch Dornich (980Labs / Stable Mischief)
**First use case:** Succession pipeline for James Whitfield

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
  **POC: interface + documented stub.** Granola access options (API, export
  folder, Zapier, MCP) are documented in `docs/granola-ingestion.md`; local
  folder ingestion is the contractual fallback forever (it also covers manual
  paste, Otter exports, etc.).

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
  `AnthropicClient` (Phase 1, code present but inert without key).
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
and opportunity cards, and weekly plans — carries frontmatter
`review_status: unreviewed | reviewed | corrected | confirmed`, defaulting to
`unreviewed`. Unreviewed artifacts may inform recommendations but are always
labeled as AI synthesis, never treated as canonical fact. Corrections
preserve what changed and why (the managed-section + backup mechanism below
keeps the original visible in `.ri-backups/`). Only `reviewed`/`corrected`/
`confirmed` content is a candidate for promotion into canonical memory
(Vault A L1/L2) in Phase 4 — unreviewed synthesis never promotes
automatically.

**Idempotent-write mechanism (concrete, testable):**

- Every generated note carries frontmatter `generated_by: relationship-intel`
  and `content_hash` of its AI-managed content.
- AI-managed content lives between markers:
  `<!-- ri:begin section-name -->` … `<!-- ri:end section-name -->`.
- On rewrite: text outside markers is preserved verbatim; sections are
  replaced only when their content hash changed; a `.bak` copy is written to
  `<vault>/.ri-backups/<path>/<timestamp>.md` before any file that contains
  out-of-marker edits is touched.
- Re-running on unchanged input is a byte-for-byte no-op (asserted in tests).

### 3.6 CRM Adapter Layer (`src/relationship_intel/crm/`)

**Contract:** `base.py` defines the abstract interface; the pipeline core
imports only this.

```python
class CRMAdapter(ABC):
    def find_or_create_contact(person) -> CRMRef
    def find_or_create_company(company) -> CRMRef
    def create_or_update_opportunity(opportunity) -> CRMRef
    def attach_note(ref, note) -> None            # concise summary + vault link back
    def create_task(ref, task) -> CRMRef          # follow-ups with due dates
    def tag_record(ref, tags) -> None
    def get_pipeline_items(owner, stages) -> list[PipelineItem]
    def health_check() -> AdapterStatus
```

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
     "metrics": {"pipeline_counts_by_stage": {}, "overdue": 0, "…": 0},
     "findings": [], "decisions": [],
     "top_decisions": [], "flagged_anomalies": [],
     "yesterday_followups": [], "tomorrow_focus": []
   }
   ```

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

---

## 4. Dex / 980Labs OS integration contract

This system is built to become the **CRM department agent** in the fleet. The
integration surface (all Phase 4, all designed-for now):

| Fleet convention | This system provides |
|---|---|
| Contract-1 report (`agent_report_v1`) | Emitted every pipeline run to `<vault>/reports/CRM-YYYY-MM-DD.json` (§3.7) — already in the POC |
| Fleet registry entry (`scripts/agent-fleet/registry.json`) | `name: crm-source`, `kind: command`, `command: python -m relationship_intel.cli run --report`, `output_contract: agent_report_v1`, `authority_level: observe` for the scheduled read/report path (matching existing entries like `research-fleet`); the CRM-sync step runs under an explicit pre-authorized scope (additive upserts, SM workspace only) per the §3.8 authority mapping |
| Skill for Dex dispatch (`.claude/skills/crm-source/SKILL.md`) | Trigger phrases: pipeline status, last-touch lookups, "who should James call this week" |
| Morning-brief fan-out (`.claude/commands/morning.md`) | Add `crm-source` to the parallel source list |
| Sync queries (`delegate_task`) | CLI `query` subcommand answering entity/last-touch/next-action questions from the canonical store in <1s (no LLM needed) |
| Async work (Kanban) | Nightly ingest + weekly plan generation as scheduled fleet jobs |
| Memory integration | `cairns` vault mode writes L3 evidence and `unreviewed`-labeled L2 cards into Vault A → searchable by Dex's `vault-search` skill. **L1 waypoint updates are canonical-memory promotion** and are *proposed*, not written directly, until reviewed — per the ORD-0003 rule that unreviewed synthesis never promotes automatically |
| Context.Assemble (emerging) | Future `scripts/context/collectors/relationships.py` feeding the unified read model |

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

`.env.example` (trimmed to what this phase actually uses):

```
# LLM — mock until extraction quality phase begins (decision 2026-07-04)
LLM_PROVIDER=mock            # mock | anthropic
ANTHROPIC_API_KEY=

# Obsidian
OBSIDIAN_VAULT_PATH=./output/obsidian-vault
OBSIDIAN_MODE=plain          # plain | cairns
STORE_RAW_TRANSCRIPTS=true   # false → store hash + metadata only

# CRM
CRM_PROVIDER=mock            # mock | twenty
TWENTY_API_URL=http://localhost:3002   # local fork's remapped backend port
TWENTY_API_KEY=

# Granola (Phase 3)
GRANOLA_API_KEY=

# Pipeline
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
| **3 — Real Granola** | Chosen ingestion path (API / export / MCP) wired as `TranscriptSource` | James's actual meetings flow in without manual copying |
| **4 — Fleet registration** | `cairns` vault mode into Vault A; registry entry; SKILL.md; morning-brief fan-out; `query` subcommand for delegate_task | Dex answers "who should James call this week?" from this system's report |
| **5+ — Reuse** | Second lens (client development or investor relations); approval-layer state machine; possible Twenty MCP adapter | New lens ships with zero pipeline-code changes |

---

## 10. Open questions (tracked, not blocking)

1. **Granola access path** — API plan availability vs. export folder vs. MCP.
   Investigate during Phase 3; local folder covers until then.
2. **Twenty custom fields vs. native fields** for succession-specific data
   (signal score, timing window) — decide when provisioning the workspace in
   Phase 2.
3. **Vault A write policy** — partially settled by ORD-0003: L1 waypoint
   updates are canonical-memory promotion, so this system *proposes* them
   (e.g., for a `cairns-dream`-style consolidation pass) rather than writing
   them directly; unreviewed synthesis never promotes automatically. Remaining
   question is only the mechanics of the proposal/review queue at Phase 4.
4. **Approval-layer shape** — ORD-0003 authority levels vs. a simpler
   approve/reject queue in the weekly plan. Decide as usage patterns emerge.
5. **Thane's role** — currently unspecified vs. Dex. The Contract-1 +
   delegate_task surface serves any orchestrator; no coupling to Dex
   specifically.
