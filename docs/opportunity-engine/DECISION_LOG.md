# Decision log / ADRs

Date: 2026-09-04. Scope: additive foundation. Accepted decisions below implement the user's
handoff; proposed decisions require review before a later milestone.

## ADR-001 — Product-neutral Opportunity Engine in SM-CRM-System

Accepted. Reuse the current working relationship-intelligence foundation. Succession is Product
Pack #1; the engine owns reusable commercial primitives. 980labsOS remains the control plane.
Consequence: new product behavior must not require copying identity or operational infrastructure.

## ADR-002 — Strangler migration and SQLite retention

Accepted. Preserve existing pipeline and tables. Add generic tables and explicit opt-in services;
retain SQLite until domain and second-product usage justify revisiting persistence.
Consequence: temporary dual concepts and explicit projection boundaries. Do not infer production
parity from the existence of new models. Revisit after real multi-product concurrency measurements.

## ADR-003 — Evidence before interpretation

Accepted. Evidence and observations have no product foreign key. Signals bind observations to a
versioned pack. Hypotheses cite signals and all supporting observations, including fit facts.
Consequence: source reuse, inspectable attribution and no product-specific copies of neutral facts.
The bridge labels legacy extraction provenance; it does not claim extracted statements are verified truth.

## ADR-004 — Independent hypothesis identity

Accepted. Generic hypotheses have stable IDs plus a nonunique episode grouping key. No unique
person/company constraint. Existing opportunities retain their constraint for compatibility.
Consequence: multiple products and hypotheses over time are possible. Semantic duplicate/alternative
hypothesis management and north-star counting need an explicit later policy.

## ADR-005 — Separate generic repository on the existing store

Accepted for foundation. Use `OpportunityRepository` and the existing SQLite connection factory.
Do not inflate legacy row/view models or mix generic records into legacy writer/planner queries.
Consequence: callers must deliberately choose the new path; generic transactions must not invoke
legacy methods that commit. Revisit a common repository facade only when consumers need one.

## ADR-006 — Immutable versioned foundation records

Accepted. Same ID/same content is a no-op; changed content is a conflict. Corrections require new
records and policy changes new versions. Cross-row subject/pack invariants live in the repository.
Consequence: audit history is preserved, but explicit supersession/correction semantics are needed
before production use. Direct raw SQL is outside the domain API.

## ADR-007 — Hypotheses begin with evidence

Proposed target-boundary refinement; implemented narrowly in the foundation. Upstream discovery,
normalization and fit work should be assessment/work items, not empty hypotheses. Creation starts
at HYPOTHESIS_CREATED, unreviewed. No lifecycle transitions ship here.
Consequence: the suggested long lifecycle is retained as workflow vocabulary, pending ownership
by assessment, hypothesis and engagement. Review before implementing the full state machine.

## ADR-008 — Pure packs and unrelated fixture

Accepted. The shared protocol takes observations and returns assessments. Registry pins exact
versions. Workflow Automation Audit is fixture-only for 20–250 employee professional services.
Consequence: architecture test success does not authorize a new commercial offering or campaign.
No better existing implemented 980labs product pack was found in this repository.

## ADR-009 — Preserve legacy scoring; postpone generic composite

Accepted. Map Succession score only to timing/signal strength. Keep other dimensions null.
Do not invent a calibrated composite or reinterpret model confidence as commercial probability.
Consequence: production ranking and autonomous action remain blocked on labels/policy, even though
foundation hypotheses can be stored and evaluated deterministically.

## ADR-010 — Supported CRM APIs and review boundaries

Accepted. Keep existing Twenty adapter and gate. Generic hypotheses do not automatically sync,
update existing CRM pair-unique opportunities, or enter weekly plans. First-touch outbound remains
a future human-approved capability; this repo still has no new send path.
Consequence: generic CRM projection, review UI and archive rendering require explicit design/tests.

## ADR-011 — No providers before abstraction evidence

Accepted. No new discovery, enrichment, crawling or verification provider in the foundation.
Consequence: provider evaluation remains a scorecard, not implementation or vendor selection.
Revisit after real second-pack/domain acceptance with approved budget and test cases.

## ADR-012 — Keep governing docs unchanged during reconciliation

Accepted. New documentation lives in this directory and records drift against current code.
Do not silently replace the governing architecture, source contract or existing production guides.
Consequence: a later reviewed docs update must reconcile authority and remove stale statements,
including broad claims about delete-free provisioning and completeness of source attribution.
