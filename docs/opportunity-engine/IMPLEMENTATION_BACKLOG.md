# Implementation backlog

The foundation remains on a feature branch for review. "Delivered" means implemented locally
with tests; it does not mean merged, deployed, commercially validated or enabled in production.

## Delivered foundation

| Item | Result | Verification |
|---|---|---|
| Repository reconciliation and baseline | Additive docs package; governing docs intact | Baseline 226 tests plus lint/format |
| Product-neutral models | Product, version, Evidence, Observation, definition/signal, hypothesis | Validation and source/subject tests |
| Additive SQLite | `oe_*` tables, FKs, support joins, immutable repository | Existing DB upgrade, replay, conflict, rollback |
| Shared pack boundary | Protocol, exact-version registry, deterministic assessment service | Two products and multiple episodes for one subject |
| Succession adapter | Lens reuse, profile mapping and opt-in exact-quote projection | Sample parity and unchanged legacy state |
| Unrelated fixture | Workflow Audit ICP/workload gates | Positive/excluded/missing/conflicting cases |
| Generic gold format | Strict JSON cases, findings and signal precision/recall | Six synthetic cases and malformed/negative tests |

## Next reviewable changes, in dependency order

### OE-01 — Approve boundaries and strengthen provenance versioning

Decide pre-hypothesis assessment ownership, episode identity, predicate vocabulary and validation
roles. Add typed unit/as-of/source attribution fields where actual inputs require them, plus
policy/code digests and a schema-version ledger before modifying foundation tables.

Acceptance: ADRs approved, version changes detect executable policy changes, old records still read,
invalid units/times rejected, migrations rerun safely.

### OE-02 — Neutral intake and resumable shadow backfill

Add a product-neutral observation extraction contract and an explicit resumable command over
completed legacy transcripts. Capture stable source timestamps, resolve IDs through existing
rules, record checkpoints and route ambiguous/unsupported attribution to review. Preserve
legacy dedupe/retry behavior and do not backfill by person display name alone.

Acceptance: interruptions resume without duplicates; existing ingest/review/sync outputs remain
unchanged; repeated/approximate quotes hold for review; corrections preserve provenance.

### OE-03 — Real two-pack gold set and calibration report

Collect independent redacted labels and account/time-separated holdout cases. Record disagreements,
false positives, source attribution, per-product breakdowns and review burden. Map legacy plan
feedback only where the meaning is explicit.

Acceptance: strict holdout separation, no silent empty results, reviewer-approved thresholds,
repeatable versioned score comparison. Passing synthetic fixtures is not sufficient.

### OE-04 — Generic lifecycle and review decisions

Implement explicit allowed transitions on the appropriate aggregates. Persist decisions with actor,
authority, expected version, reviewed payload hash and reason. Keep validation, CRM approval,
contact permission and memory promotion distinct. Model correction/supersession and expiry.

Acceptance: every edge tested, invalid shortcuts fail, changed payload invalidates approval,
concurrent stale decisions fail, holding states cannot leak into engagement.

### OE-05 — Human read models and generic CRM projection

Design product-aware archive/review surfaces and supported Twenty API mapping. Keep separate
external identities for hypotheses and legacy opportunities. Add generic metrics without changing
Contract-1's current required shapes. Obtain concrete review of the mapping before live writes.

Acceptance: same account with two products renders distinctly; citations are accessible; no raw
transcripts in CRM; approved-only idempotent sync; legacy demo/plans/Contract-1 remain green.

### OE-06 — ProviderObservation and a costed provider pilot

Only after OE-01 through OE-03 acceptance, choose one provider using the scorecard. Add normalized
request/result provenance, budget references, cost ledger, verification state and deterministic
retry/waterfall rules. Keep secrets and model routing in the control plane.

Acceptance: fake-provider coverage, budget/rate/retry failures tested, measured coverage and actual
cost, explicit live-pilot authorization. No wholesale contact-list import as an incidental step.

### OE-07 — Engagement/outcome and learning

Design product-aware campaigns, approved first-touch execution, suppression, replies and labeled
outcomes as a separate scoped milestone. Do not add sending code to this foundation. Amend governing
safety constraints only through a reviewed, explicitly authorized capability change.

Acceptance: human approval remains default; suppression/verification/expiry tested; costs and
outcomes attributed without double-counting shared research or alternate hypotheses.

### OE-08 — Persistence and operational scale review

Measure concurrent writers, queue pressure, read latency, backup/restore and retention requirements
after real second-product usage. Compare SQLite with migration alternatives only from those needs.

Acceptance: documented measurements and migration/rollback plan; no simultaneous domain rewrite
and persistence replacement.

## Review gates for this branch

1. Read design package and inspect the two small changes to the existing DB module.
2. Review new models/repository independently of pack logic.
3. Review Succession compatibility and Workflow Audit fixture as separate interpretations.
4. Run canonical checks and generic gold command; inspect new negative tests.
5. Merge only when the additive scope is accepted. Production rollout/backfill is a separate step.
