# Decision log / ADRs

Date: 2026-09-04. Scope: additive foundation. Accepted decisions below implement the user's
handoff; proposed decisions require review before a later milestone.

## ADR-001 — Product-neutral Opportunity Engine in SM-CRM-System

Accepted. Reuse the current working relationship-intelligence foundation. Succession is Product
Pack #1; the engine owns reusable commercial primitives. 980labsOS remains the control plane.
Consequence: new product behavior must not require copying identity or operational infrastructure.

Transcript check: consistent — Turn 7 requests unrelated products; Turn 8 separates platform, engine and product packs.

## ADR-002 — Strangler migration and SQLite retention

Accepted. Preserve existing pipeline and tables. Add generic tables and explicit opt-in services;
retain SQLite until domain and second-product usage justify revisiting persistence.
Consequence: temporary dual concepts and explicit projection boundaries. Do not infer production
parity from the existence of new models. Revisit after real multi-product concurrency measurements.

Transcript check: not discussed — the excerpt names possible Postgres schemas (Turn 18), but accepts no SQLite/migration decision.

## ADR-003 — Evidence before interpretation

Accepted. Evidence and observations have no product foreign key. Signals bind observations to a
versioned pack. Hypotheses cite signals and all supporting observations, including fit facts.
Consequence: source reuse, inspectable attribution and no product-specific copies of neutral facts.
The bridge labels legacy extraction provenance; it does not claim extracted statements are verified truth.

Transcript check: consistent — Turn 14 says evidence and company intelligence are globally reusable, interpretations product-specific.

## ADR-004 — Independent hypothesis identity

Accepted. Generic hypotheses have stable IDs plus a nonunique episode grouping key. No unique
person/company constraint. Existing opportunities retain their constraint for compatibility.
Consequence: multiple products and hypotheses over time are possible. Semantic duplicate/alternative
hypothesis management and north-star counting need an explicit later policy.

Transcript check: consistent — Turn 14 allows simultaneous and expired product hypotheses; exact ID/episode constraints are not discussed.

## ADR-005 — Separate generic repository on the existing store

Accepted for foundation. Use `OpportunityRepository` and the existing SQLite connection factory.
Do not inflate legacy row/view models or mix generic records into legacy writer/planner queries.
Consequence: callers must deliberately choose the new path; generic transactions must not invoke
legacy methods that commit. Revisit a common repository facade only when consumers need one.

Transcript check: not discussed — repository/connection implementation boundaries do not appear in the excerpt.

## ADR-006 — Immutable versioned foundation records

Accepted. Same ID/same content is a no-op; changed content is a conflict. Corrections require new
records and policy changes new versions. Cross-row subject/pack invariants live in the repository.
Consequence: audit history is preserved, but explicit supersession/correction semantics are needed
before production use. Direct raw SQL is outside the domain API.

Transcript check: not discussed — immutable record, conflict and correction semantics do not appear in the excerpt.

## ADR-007 — Hypotheses begin with evidence

Proposed target-boundary refinement; implemented narrowly in the foundation. Upstream discovery,
normalization and fit work should be assessment/work items, not empty hypotheses. Creation starts
at HYPOTHESIS_CREATED, unreviewed. No lifecycle transitions ship here.
Consequence: the suggested long lifecycle is retained as workflow vocabulary, pending ownership
by assessment, hypothesis and engagement. Review before implementing the full state machine.

Transcript check: consistent — Turn 14 distinguishes entities from evidence-backed hypotheses; Turn 18 leaves lifecycle design for specification.

## ADR-008 — Pure packs and unrelated fixture

Accepted. The shared protocol takes observations and returns assessments. Registry pins exact
versions. Workflow Automation Audit is fixture-only for 20–250 employee professional services.
Consequence: architecture test success does not authorize a new commercial offering or campaign.
No better existing implemented 980labs product pack was found in this repository.

Transcript check: consistent — Turn 18 requests an unrelated hypothetical product stress test; exact protocol and employee range are not discussed.

## ADR-009 — Preserve legacy scoring; postpone generic composite

Accepted. Map Succession score only to timing/signal strength. Keep other dimensions null.
Do not invent a calibrated composite or reinterpret model confidence as commercial probability.
Consequence: production ranking and autonomous action remain blocked on labels/policy, even though
foundation hypotheses can be stored and evaluated deterministically.

Transcript check: not discussed — Turn 8 lists separate scores but the excerpt defines no legacy mapping, weights or calibrated composite.

## ADR-010 — Supported CRM APIs and review boundaries

Accepted. Keep existing Twenty adapter and gate. Generic hypotheses do not automatically sync,
update existing CRM pair-unique opportunities, or enter weekly plans. First-touch outbound remains
a future human-approved capability; this repo still has no new send path.
Consequence: generic CRM projection, review UI and archive rendering require explicit design/tests.

Transcript check: consistent — Turn 14 places human approval before engagement; Turn 18 calls for an explicit Twenty projection boundary.

## ADR-011 — No providers before abstraction evidence

Accepted. No new discovery, enrichment, crawling or verification provider in the foundation.
Consequence: provider evaluation remains a scorecard, not implementation or vendor selection.
Revisit after real second-pack/domain acceptance with approved budget and test cases.

Transcript check: consistent — Turn 18 says “Define the evaluation harness before providers.”

## ADR-012 — Keep governing docs unchanged during reconciliation

Accepted. New documentation lives in this directory and records drift against current code.
Do not silently replace the governing architecture, source contract or existing production guides.
Consequence: a later reviewed docs update must reconcile authority and remove stale statements,
including broad claims about delete-free provisioning and completeness of source attribution.

Transcript check: not discussed — governing-document preservation is an implementation governance decision, absent from the excerpt.

## ADR-013 — Cold qualification is Succession Pack #1

Accepted under the Mitch-ratified Phase 13A cold-pack brief (2026-09-04), architecture
§1/§2 A1/A5 and §3.5. `succession:cold-v0` is Pack #1 for cold EOS Implementer
qualification; Acquirers remain deferred. The warm transcript pack stays unscheduled,
unchanged at registry ID `succession:foundation-v1` / scoring version `succession-v0.1`.
Both versions share product `succession`, canonical subjects and neutral evidence.
The department pack v0 supplies policy provenance, not a second commercial product.
No new provider, scheduled invocation, lifecycle transition or CRM projection is authorized.
ADR-001…012 above retain their original text; checks compare only the archived excerpt,
not missing portions of the conversation. Architecture §7's IPP correction to ADR-008
is acknowledged; implementation of IPP remains a separate brief.

Transcript check: consistent — Turn 14 calls Succession the first product to prove the engine; the cold EOS priority is a later A1/A5 decision, not discussed in the genesis excerpt.
