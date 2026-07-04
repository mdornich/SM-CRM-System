---
title: "feat: Phase 0 relationship-intelligence pipeline POC"
type: feat
date: 2026-07-04
origin: docs/architecture.md
deepened: 2026-07-04
---

# feat: Phase 0 Relationship-Intelligence Pipeline POC

**Origin:** `docs/architecture.md` (draft v1, commit 374e2d4) — the spec is the requirements document; this plan sequences its Phase 0 scope into implementation units. Where this plan is silent, the spec governs. The original build prompt is committed as `docs/build-prompt.md` (source contract for note templates, lens text, CLI commands, and weekly-plan rules); where it and the spec disagree, the spec governs.

---

## Summary

Build the runnable Phase 0 POC of the transcript-to-relationship-intelligence pipeline: local transcript ingestion → deterministic mock extraction (full schema) → SQLite canonical store with fixed entity-resolution rules → Obsidian-compatible vault notes with managed-section idempotency → mock CRM sync (plus a real-docs-grounded Twenty REST adapter, inert without a key) → weekly plan in three renderings (Markdown, JSON, Contract-1 union report). Exit: `python -m relationship_intel.cli run-demo` green end-to-end, all tests pass, PR opened.

---

## Problem Frame

The spec (§1–§3) defines seven layers; Phase 0 (§9) requires all of them working locally with mocks at the two expensive boundaries (LLM, CRM). The deliverable proves plumbing, identity handling, idempotency, and contract compliance — explicitly *not* extraction quality (that is Phase 1, and every artifact must self-label `llm_provider: mock`).

**Hard boundaries:** do not modify `~/Documents/GitHub/twenty` or `~/GitHub/980labsOS`; no outbound-send capability anywhere; no delete methods on the CRM interface; no Anthropic API spend (mock provider default; Anthropic client present but inert).

---

## Requirements (traceability)

From spec §9 Phase 0 exit criteria and §8 test suite:

- R1. `run-demo` executes the full pipeline end-to-end from sample transcripts (spec §9).
- R2. Obsidian `plain`-mode vault generated at `./output/obsidian-vault` with the §3.5 structure, frontmatter (incl. `review_status`, `generated_by`, `content_hash`), wikilinks, evidence snippets, managed-section markers, `.bak` backups, byte-identical re-runs.
- R3. SQLite canonical store with §3.4 entity-resolution rules and `crm_sync_state` idempotency bookkeeping.
- R4. `CRMAdapter` interface (§3.6) with fully working `MockCRMAdapter`; `TwentyCRMAdapter` complete against the verified local-fork REST API (port 3002), safe when unconfigured.
- R5. Weekly plan: Markdown + JSON + Contract-1 **union** report that passes a vendored `validate_agent_report_v1`; Monday week math (§3.7).
- R6. All 12 test cases from spec §8, including the structural no-outbound-send test.
- R7. Sample transcripts: warm succession prospect, referral source, not-fit (§8), exercising every schema field through the mock extractor.
- R8. Docs: README (exact run instructions), `docs/data-model.md`, `docs/succession-lens.md`, `docs/obsidian-archive.md`, `docs/twenty-setup.md`, `docs/granola-ingestion.md`; repo `CLAUDE.md` listing the canonical local-CI command set.
- R9. Security §7: no transcript bodies in logs; `STORE_RAW_TRANSCRIPTS` toggle; secrets via env only; `output/` gitignored except `.gitkeep`.

---

## Key Technical Decisions

1. **Python 3.12 (system), venv at `.venv`, `pyproject.toml` + editable install** so `python -m relationship_intel.cli` works. Deps: `pydantic` v2, `httpx`, `python-dotenv`, `pyyaml` (frontmatter parse/emit); dev: `pytest`, `ruff`. CLI via stdlib `argparse` (spec allows it; zero extra deps for a POC).
2. **No ORM** — stdlib `sqlite3` behind `repository.py`; the store is small and transactional needs are simple.
3. **Mock LLM is deterministic and cue-driven**: sample transcripts embed explicit structured cues (names, quoted signal phrases); `MockLLMClient` parses them with rules to produce full-schema `ExtractedRelationshipIntelligence`. No randomness → tests are exact.
4. **Twenty adapter grounded in the fork's actual code** (verified 2026-07-04 by reading `packages/twenty-server`): base path `/rest`, `Authorization: Bearer <api-key-jwt>`, plural object routes (`/rest/people`, `/rest/companies`, `/rest/opportunities`, `/rest/tasks`, `/rest/notes`), composite request fields (`name: {firstName,lastName}`, `emails: {primaryEmail,…}`, `domainName: {primaryLinkUrl,…}`, `bodyV2: {markdown,…}`), filter DSL `filter=emails.primaryEmail[eq]:x@y.com`, response envelopes `data.people` / `data.createPerson`, default opportunity stages `NEW|SCREENING|MEETING|PROPOSAL|CUSTOMER`. Task/note ↔ record linking uses join tables (`taskTargets`/`noteTargets`) — Phase 0 implements create + link via a second POST, documented as the one integration-untested area until Phase 2.
5. **Stage mapping is a single table** in the adapter: spec stages (`new|nurture|discovery|qualified|active_opportunity|stalled|closed_won|closed_lost|not_fit` — the full closed vocabulary from `docs/build-prompt.md` §"Extraction schema") → Twenty stages (`NEW|SCREENING|MEETING|PROPOSAL|CUSTOMER`), with unmapped spec stages (`not_fit`, `stalled`, `closed_lost`) intentionally not creating opportunities.
6. **Contract-1 validator vendored** as `planning/contract.py` (logic mirrored from `980labsOS/scripts/agent-fleet/contracts.py`, stdlib-only): the report is validated at emit time and in tests. Report is the union shape from spec §3.7.
7. **Managed sections**: `<!-- ri:begin NAME -->` / `<!-- ri:end NAME -->`; writer replaces only sections whose content hash changed; out-of-marker text preserved verbatim; `.bak` to `<vault>/.ri-backups/` before touching a file containing manual edits. **Unbalanced/corrupted markers → conservative fallback:** the file is treated as fully manually-edited — writer skips the rewrite, logs a warning naming the file, still writes the `.bak`. Backups are capped at the 10 most recent per source file (retention documented in `docs/obsidian-archive.md`).
8. **Structural security tests** (three, all mechanized): (a) *no-send* — scan the installed package source for outbound modules/calls (`smtplib`, `requests.post`/`httpx.post` to non-CRM hosts, `subprocess` mail/sendmail, etc.); the only permitted network surface is `crm/twenty_adapter.py` (and the inert `llm_client` Anthropic path); also assert `CRMAdapter` exposes no delete method. (b) *no-transcript-in-logs* — capture log output across a full pipeline run and assert no raw transcript substring appears; log statements touching transcript-derived data reference `transcript_hash` only. (c) *summary boundary* — CRM note bodies never contain evidence-snippet text (spec §3.6 "Twenty gets summaries, not evidence").

---

## Output Structure

Repo root is the project root (spec §2):

```
SM-CRM-System/
  README.md  CLAUDE.md  pyproject.toml  .env.example  .gitignore
  docs/
    architecture.md  data-model.md  succession-lens.md
    obsidian-archive.md  twenty-setup.md  granola-ingestion.md
    plans/  (this file)
  examples/transcripts/
    sample-warm-succession-prospect.md
    sample-referral-source.md
    sample-not-fit.md
  output/.gitkeep
  src/relationship_intel/
    __init__.py  cli.py  config.py
    intake/{__init__,local_folder,granola_api}.py
    extraction/{__init__,schemas,succession_lens,llm_client,extractor}.py
    store/{__init__,db,models,repository}.py
    obsidian/{__init__,writer,templates,links}.py
    crm/{__init__,base,mock_adapter,twenty_adapter}.py
    planning/{__init__,weekly_plan,message_drafts,contract}.py
    util/{__init__,hashing,markdown,dates}.py
  tests/
    conftest.py
    test_extraction.py  test_obsidian_writer.py  test_weekly_plan.py
    test_dedupe.py  test_crm_mock_adapter.py  test_twenty_adapter.py
    test_idempotency.py  test_contract_report.py  test_no_send.py
```

---

## Implementation Units

### Phase A — Foundation

### U1. Scaffolding, config, and packaging

**Goal:** installable package skeleton; every later unit drops into place.
**Requirements:** R1 (prereq), R8 (CLAUDE.md), R9 (gitignore/env).
**Dependencies:** none.
**Files:** `pyproject.toml`, `.env.example`, `.gitignore`, `CLAUDE.md`, `output/.gitkeep`, `src/relationship_intel/__init__.py`, `src/relationship_intel/config.py`, all package `__init__.py` files, `tests/conftest.py`.
**Approach:** `config.py` loads `.env` via python-dotenv into a frozen `Settings` dataclass (env names exactly per spec §6, incl. `TWENTY_API_URL=http://localhost:3002` default and `STORE_RAW_TRANSCRIPTS`). `.gitignore`: `output/*`, `!output/.gitkeep`, `.env`, `.venv/`, `__pycache__/`. `CLAUDE.md` records local CI: `ruff check . && ruff format --check . && pytest`. `conftest.py` provides tmp-path vault/store fixtures.
**Test scenarios:** Settings defaults resolve when `.env` absent; env override wins; `STORE_RAW_TRANSCRIPTS=false` parses as boolean false.
**Verification:** `pip install -e .` succeeds; `python -c "from relationship_intel.config import Settings"` works.

### U2. Schemas and succession lens

**Goal:** the full Pydantic model set and the lens-as-data.
**Requirements:** R7, R6 (test 11), spec §5.
**Dependencies:** U1.
**Files:** `src/relationship_intel/extraction/schemas.py`, `src/relationship_intel/extraction/succession_lens.py`, `tests/test_extraction.py` (schema portion).
**Approach:** All spec §5 models with closed enums defined once; additions per spec: `identity_confidence`, `needs_review`, `llm_provider`, `lens_version`, `approval_status`, `review_status`. Evidence is required on classifications (validator: a `SuccessionLeadProfile` with `lead_type != unknown` must carry ≥1 evidence snippet). `succession_lens.py` holds `LENS_VERSION`, the extraction prompt text (`docs/build-prompt.md` §"Succession extraction lens"), and the rule constants the mock honors — a future real-LLM lens reuses the same module.
**Test scenarios:** unknown fields default to `None`/`unknown` (never fabricated); enum rejection of out-of-vocabulary values; classification-without-evidence raises validation error; `review_status` defaults to `unreviewed`, `approval_status` to `proposed`.
**Verification:** schema round-trips to/from JSON.

### U3. Intake layer

**Goal:** local transcript folder → `RawTranscript` objects with hash dedupe at the gate.
**Requirements:** R1, R6 (test 4), spec §3.1.
**Dependencies:** U1.
**Files:** `src/relationship_intel/intake/local_folder.py`, `src/relationship_intel/intake/granola_api.py`, `src/relationship_intel/util/hashing.py`, `tests/test_dedupe.py` (intake portion).
**Approach:** `TranscriptSource` protocol; `LocalFolderSource` reads `.md`/`.txt`, parses optional YAML frontmatter (title/date/attendees/owner), falls back to `YYYY-MM-DD-source-title.md` filename convention; `transcript_hash = sha256(normalized_text)` (strip trailing whitespace, normalize newlines). `granola_api.py` is a documented stub implementing the protocol and raising a clear `NotConfiguredError`.
**Test scenarios:** frontmatter parsed; filename fallback works; hash stable across trailing-whitespace/newline variants; malformed frontmatter degrades to filename metadata rather than crashing.
**Verification:** the three sample transcripts load with correct metadata.

### U4. Canonical store and entity resolution

**Goal:** SQLite store, repository API, and the §3.4 identity rules — the correctness core.
**Requirements:** R3, R6 (tests 4–6).
**Dependencies:** U1, U2.
**Files:** `src/relationship_intel/store/db.py`, `src/relationship_intel/store/models.py`, `src/relationship_intel/store/repository.py`, `tests/test_dedupe.py`.
**Approach:** Tables per spec §3.3 (`transcripts`, `people`, `companies`, `opportunities`, `lead_profiles`, `interactions`, `crm_sync_state`, `plans`). Resolution exactly per §3.4: (1) case-insensitive email match; (2) normalized name + company; (3) name-only with no company conflict → match flagged `identity_confidence: medium`; (4) new record, `needs_review: true` when edit-distance ≤ 2 from an existing name (stdlib implementation, no dependency). Companies: normalized name (strip Inc/LLC/Co/…); domain match overrides. `register_transcript` returns already-seen for a known hash.
**Execution note:** implement resolution rules test-first — the test cases in spec §8 define the contract.
**Test scenarios:** same email, different name spelling → same person; same normalized name + company across transcripts → same person; name-only match flagged medium; near-duplicate name (edit distance 2) → new person flagged `needs_review`; company `"Acme Inc."`/`"Acme"` merge; domain match overrides differing names; duplicate transcript hash → no new rows anywhere.
**Verification:** re-ingesting the sample folder twice produces identical row counts.

### Phase B — Pipeline stages

### U5. Extraction layer with deterministic mock LLM

**Goal:** `RawTranscript → ExtractedRelationshipIntelligence`, provider-pluggable.
**Requirements:** R1, R6 (tests 1–3, 11), R7.
**Dependencies:** U2, U3.
**Files:** `src/relationship_intel/extraction/llm_client.py`, `src/relationship_intel/extraction/extractor.py`, `examples/transcripts/*.md` (co-designed with the mock), `tests/test_extraction.py`.
**Approach:** `LLMClient` protocol with `complete(system, user, response_schema)`. `MockLLMClient` parses structured cues from transcripts: attendee lines, quoted signal phrases (e.g. "trying to figure out the next chapter" → `exit_or_transition_signal: true`, warm), explicit referral language, absence of signals → `not_fit`/`unknown`. `AnthropicClient` implemented (httpx call shape, model param) but raises `NotConfiguredError` without a key — never called in Phase 0 tests. `extractor.py` selects client from `Settings`, stamps `llm_provider` + `lens_version` on every artifact, validates against schemas, and applies the conservative-warmth rules (a business owner with no transition signal stays `unknown`, not warm). Logging safety (R9): intake/extraction log lines reference `transcript_hash` only — never raw transcript text or full extracted field values.
**Test scenarios:** warm-prospect sample → `lead_type: warm`, timing `3_6_months`, evidence snippets quote the transcript verbatim; referral-source sample → `referral_source`, NOT a prospect stage; not-fit sample → `not_fit` with no fabricated people/emails (fields null); every extracted artifact carries `llm_provider == "mock"`.
**Verification:** all three samples extract to full-schema objects with zero validation errors.

### U6. Obsidian writer

**Goal:** render store state to the `plain`-mode vault, idempotently and edit-safely.
**Requirements:** R2, R6 (tests 7–8), R9.
**Dependencies:** U4, U5.
**Files:** `src/relationship_intel/obsidian/writer.py`, `src/relationship_intel/obsidian/templates.py`, `src/relationship_intel/obsidian/links.py`, `src/relationship_intel/util/markdown.py`, `tests/test_obsidian_writer.py`, `tests/test_idempotency.py`.
**Approach:** Templates exactly per `docs/build-prompt.md` §"Obsidian note templates" (transcript, person, company, opportunity, weekly plan) plus vault `README.md` and `indexes/*.jsonl`. Frontmatter includes `generated_by`, `content_hash`, `review_status: unreviewed`, `llm_provider`. Managed sections per KTD-7. Raw transcript body included only when `STORE_RAW_TRANSCRIPTS=true`; evidence snippets always kept. Wikilinks connect people ↔ companies ↔ opportunities ↔ transcripts. Slug collision policy: append `-2` style suffix keyed to store id.
**Test scenarios:** all note types render with correct frontmatter and wikilinks; second run on unchanged input is byte-for-byte identical (hash the tree); a manual edit outside markers survives a re-run AND a `.bak` appears; a manual edit *inside* markers is replaced but backed up; a file with a deleted/mangled `ri:end` marker is skipped with a warning and backed up, never rewritten; `STORE_RAW_TRANSCRIPTS=false` omits the raw body but keeps evidence; JSONL indexes are valid line-delimited JSON.
**Verification:** open the generated vault in a file browser; structure matches spec §3.5.

### U7. CRM adapter layer

**Goal:** the adapter contract, a fully working mock, and a docs-complete Twenty adapter.
**Requirements:** R4, R6 (tests 10, 12), R3 (sync-state).
**Dependencies:** U4.
**Files:** `src/relationship_intel/crm/base.py`, `src/relationship_intel/crm/mock_adapter.py`, `src/relationship_intel/crm/twenty_adapter.py`, `tests/test_crm_mock_adapter.py`, `tests/test_twenty_adapter.py`, `tests/test_no_send.py`.
**Approach:** `base.py` per spec §3.6 — abstract methods only, **no delete**, plus `CRMRef` and `AdapterStatus`. `MockCRMAdapter` persists JSON files under `output/mock_crm/`, implements find-or-create semantics keyed on email/domain/name, and `get_pipeline_items` so the planner runs identically against mock and real. `TwentyCRMAdapter` per KTD-4/5: httpx client, Bearer auth, composite-field payload builders, filter-DSL lookups (email for people, domain then name for companies), envelope unwrapping (`data.createPerson` verb-prefixed keys), notes/tasks via `bodyV2.markdown` + `*Targets` join-table second POST, `health_check()` GET, structured logging that redacts the key, `NotConfiguredError` without `TWENTY_API_KEY`. **Summary boundary (both adapters):** `attach_note` payloads are built exclusively from `ConversationSummary` fields + vault link — evidence-snippet strings must never pass into a CRM note body (KTD-8c). Idempotency: both adapters consult/update `crm_sync_state` (skip when last-pushed hash unchanged).
**Test scenarios:** mock — second `sync` of unchanged data performs zero writes (file mtimes/contents unchanged); find-or-create returns the same `CRMRef` for the same person twice; pipeline items round-trip; CRM note bodies contain the summary + vault link and NO evidence-snippet substring (KTD-8c). Twenty (unit-level, httpx mocked via `httpx.MockTransport`) — payload shapes match the verified composite structure; email filter string built correctly; missing key → clean `NotConfiguredError`, no request attempted; envelope parsing handles `data.people` and `data.createPerson`; API key never appears in log output. No-send — per KTD-8.
**Verification:** `sync-crm --crm mock` populates `output/mock_crm/`; `sync-crm --crm twenty` without a key exits with a clear message, non-zero, no crash.

### U8. Planning layer

**Goal:** the weekly plan in three renderings from one plan model.
**Requirements:** R5, R6 (test 9).
**Dependencies:** U4, U6 (weekly-plan template + wikilink conventions), U7 (reads `get_pipeline_items`).
**Files:** `src/relationship_intel/planning/weekly_plan.py`, `src/relationship_intel/planning/message_drafts.py`, `src/relationship_intel/planning/contract.py`, `src/relationship_intel/util/dates.py`, `tests/test_weekly_plan.py`, `tests/test_contract_report.py`.
**Approach:** `PlanModel` built from store + pipeline items. Two related structures, reconciled explicitly: *grouping logic* classifies records into the `docs/build-prompt.md` §"Weekly plan rules" categories (Hot/urgent, Overdue, Warm follow-ups, Cold retouches, Referral/partner nurture, Stalled, Long-term nurture, Not ready); the *Markdown rendering* uses the section structure required by spec §3.7 (Top Plays / Overdue / Warm Follow-Ups / Cold Retouches / Referral Nurture / Stalled / Needs Review / Risks) — Top Plays is the ranked head of Hot+Overdue+Warm, Long-term/Not-ready fold into a short tail note, Needs Review lists flagged identities from U4. Deterministic rubric per spec §3.7 (overdue first, then `urgency × succession_signal_score`, stall threshold from settings). Renderers: Markdown (template per spec), JSON, Contract-1 union (KTD-6) — validated by `planning/contract.py` before write. `message_drafts.py` emits template-based drafts, each prefixed `DRAFT — not sent` (ORD-0003 Level-2 marking). `dates.py`: Monday-of-ISO-week default, `--week-start` override.
**Test scenarios:** Monday math — run dated Sat 2026-07-04 defaults to week-start 2026-06-29; explicit `--week-start 2026-07-06` honored; overdue item outranks higher-scored non-overdue; stalled detection at exactly threshold vs threshold-1 days; Contract-1 report passes the vendored validator (and a mutated report missing `findings` fails it); `confidence` emitted as string; every plan item carries evidence wikilink + obsidian path; drafts carry the DRAFT marker.
**Verification:** generated Markdown reads as actionable plan sections, not a data dump (human check).

### Phase C — Assembly

### U9. CLI, run-demo, samples, and docs

**Goal:** wire everything into the five spec commands; ship samples and docs; end-to-end green.
**Requirements:** R1, R7, R8, R9 (logging-safety test).
**Dependencies:** U3–U8.
**Files:** `src/relationship_intel/cli.py`, `examples/transcripts/*` (finalized), `tests/test_logging_safety.py`, `README.md`, `docs/data-model.md`, `docs/succession-lens.md`, `docs/obsidian-archive.md`, `docs/twenty-setup.md`, `docs/granola-ingestion.md`.
**Approach:** argparse subcommands exactly per `docs/build-prompt.md` §"CLI commands": `init`, `ingest --source --vault`, `sync-crm --crm`, `weekly-plan --owner --week-start --vault`, `run-demo` (init → ingest samples → sync mock → weekly plan, printing a summary of artifact locations). `docs/twenty-setup.md` documents the local fork (port 3002, API key creation at Settings → Developers, stage mapping table, the `*Targets` linking caveat); `docs/granola-ingestion.md` documents the Phase 3 options. README: exact venv + install + run commands.
**Test scenarios:** `run-demo` exit code 0 on a clean checkout (integration test invoking the CLI via `subprocess` into a tmp output dir); `init` is idempotent; unknown `--crm` value → argparse error listing valid choices; logging safety (KTD-8b) — captured log output from a full pipeline run contains no substring of any sample transcript body.
**Verification (the real-environment gate):** run the actual commands from README in a fresh venv; inspect the actual vault files, mock CRM JSON, and all three plan artifacts; `ruff check . && ruff format --check . && pytest` all green.

---

## Scope Boundaries

**In scope:** everything above; feature branch + PR against `main`.

**Out of scope (spec phases 1–5):** real Anthropic extraction; live Twenty integration testing (adapter ships, integration is Phase 2 — `test_twenty_adapter.py` uses mocked transport only); Granola API; `cairns` vault mode; 980labsOS registration; approval-layer state machine beyond the schema fields; `query` subcommand.

### Deferred to Follow-Up Work

- Live `twenty_adapter` smoke test against the running local fork (Phase 2 — requires provisioning an API key in the workspace).
- Voice-calibrated message drafts (Phase 1+).
- GitHub Actions CI workflow (repo has none today; local CI commands are the gate for this PR — add CI when the repo gains collaborators).

---

## Risks

1. **Mock-vs-real drift**: the mock extractor's cue grammar could ossify into a de-facto format. Mitigation: cues are ordinary English sentences in realistic transcripts; the lens prompt in `succession_lens.py` is the real contract.
2. **Twenty API drift**: adapter is pinned to fork commit `1a60d4ea` findings; upstream pulls may change shapes. Mitigation: pin documented in `docs/twenty-setup.md`; adapter failures are loud, not silent.
3. **`taskTargets`/`noteTargets` linking** is the least-verified adapter path (no integration test until Phase 2) — flagged in code TODO and docs.

---

## Sources & Research

- `docs/architecture.md` (origin; ORD-0003-verified 2026-07-04).
- Twenty REST facts read directly from the local fork source (`rest-api-core.controller.ts`, workspace-entity definitions, filter-parser utils, integration specs) — see KTD-4 for the digest.
- Contract-1 validator semantics from `980labsOS/scripts/agent-fleet/contracts.py` and `agents/smoke_test.sh` (read-only).
