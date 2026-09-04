# PRD: Opportunity Engine foundation

Status: implementation specification for the additive foundation; later milestones are proposals.

## Scope clarification

1. Problem: the existing reusable pipeline has product-specific extraction, scoring and
   opportunity identity. Product-neutral storage must precede provider expansion.
2. Core actions: register shared evidence/observations, apply a versioned Product Pack, and
   create an evidence-backed hypothesis for a resolved account/person.
3. Boundaries: preserve current production behavior; no provider onboarding, persistence
   replacement, generic outbound, automatic approvals or Twenty migration in this slice.
4. Success: legacy suite remains green and the same account/person supports hypotheses for
   two unrelated products and multiple episodes without copying neutral evidence.
5. Constraints: additive/idempotent SQLite changes, explicit product versions, deterministic
   arithmetic, no canonical state writes by LLMs, existing governing docs retained.

## Goals

- Separate source material, observations and product interpretation in schema and code.
- Preserve the current Succession demo, review gate, sync, archive and Contract-1 behavior.
- Make replay, attribution, missing evidence and version conflicts testable.
- Establish a generic gold-set format before expanding discovery.

## Tasks and acceptance criteria

### T-001: Reconcile the repository and write the design package

Inspect the repository tree, governing documents, storage, extraction, CRM/review paths,
evaluation, deployment entry points and test setup.

- [x] Record the exact baseline commit and current test result.
- [x] Document source/code drift and changes to proposed boundaries.
- [x] Add all design artifacts under `docs/opportunity-engine/` without rewriting governing docs.

### T-002: Add neutral records and product-specific hypotheses

- [x] Products and immutable pack versions are distinct records.
- [x] Evidence has source identity, content hash, location, excerpt and capture time.
- [x] Observations cite evidence and a resolved subject, with method and confidence.
- [x] Signal definitions belong to pack versions; signal observations cite observations.
- [x] Hypotheses record an episode, thesis, pack/scoring versions, dimensions and supporting IDs.
- [x] Repeated account/person pairs across products and episodes are accepted.
- [x] Missing/cross-product/cross-subject support is rejected by the repository boundary.

### T-003: Add SQLite storage and replay protection

- [x] Existing tables, IDs and legacy uniqueness stay intact.
- [x] Schema creation is additive and repeatable on new and existing databases.
- [x] Same ID/same content is a no-op; same ID/different content fails explicitly.
- [x] Multi-record creation rolls back on validation or relational failure.
- [x] Existing data survives two successive opens/migrations in the upgrade test.

### T-004: Prove Product Packs

- [x] Both packs implement one pure assessment interface and an explicit registry.
- [x] Succession reuses current lens/rubric and offers an exact legacy-profile mapping.
- [x] Workflow Audit is marked fixture-only and qualifies 20–250 employee
  professional-services firms with reported recurring manual work.
- [x] Missing facts, conflicting facts, insufficient work and excluded firms fail qualification.
- [x] Existing sample profiles retain legacy classifications/scores through the adapter.

### T-005: Add generic evaluation

- [x] Versioned cases name a pack version, neutral evidence/observations and expected decisions.
- [x] Positive and negative cases exist for both packs.
- [x] Evaluate expected classification, eligibility, signal keys, score ranges and citations.
- [x] Empty/malformed fixtures and missing source references fail rather than passing vacuously.
- [x] Unexpected and missing signals affect precision/recall.
- [ ] Redacted real cases receive independent labels and a reserved holdout split.

## Functional requirements

FR-1: Entity identity must remain independent of product participation; `companies` serves as Account.

FR-2: The generic layer must not inherit `UNIQUE(person_id, company_id)` from legacy opportunities.
A stable caller-assigned hypothesis ID handles replay. Episode grouping is separate from identity.

FR-3: Evidence and observations must have no product foreign key. They are stored before product
interpretation. New observations may be added to represent corrections; existing immutable
records may not be silently rewritten.

FR-4: Every signal must reference a known definition and observation. Every hypothesis must have
at least one signal and supporting observation; all signal references must be part of its support.

FR-5: A person-attributed observation may not support a different person's hypothesis. An
account-only observation can support a person/account hypothesis at that account.

FR-6: Unknown score dimensions remain null. Legacy Succession score must not be relabeled as
fit, probability, or a calibrated generic composite.

FR-7: Only deterministic service/repository paths write operational state. Pack assessment
receives records and returns a proposal; it receives no repository, credential or network handle.

FR-8: New hypotheses start `HYPOTHESIS_CREATED` and `unreviewed`. This slice provides no
transition to approval or sending. Current review/sync behavior continues to govern legacy records.

FR-9: Product Pack #2 is an architecture fixture. Its existence is not launch approval.

FR-10: Generic evaluation must execute without provider credentials or live network calls.

## Non-goals

External discovery/enrichment/verification providers; Postgres/Supabase migration; new CRM UI;
live outreach or replies; full lifecycle state machine; real cost ledger; generic CRM projection;
automatic corpus-wide backfill; account dedupe redesign; production multi-tenancy.

## Technical considerations

Use the current Python/Pydantic/SQLite stack. A separate `OpportunityRepository` uses the
existing connection factory and joins existing entity IDs. Keep product implementations at
the package edge and avoid importing Succession in generic models/schema/repository/service.
Do not intermingle legacy repository methods that call `commit()` inside a generic transaction.

## Metrics and remaining questions

The milestone measures regression preservation, structural acceptance and fixture decisions.
The north-star metric and production quality targets need labeled real outcomes; see
[scoring](SCORING_CALIBRATION.md) and [open questions](OPEN_QUESTIONS.md).
