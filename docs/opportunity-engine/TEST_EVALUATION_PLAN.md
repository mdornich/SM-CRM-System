# Test and evaluation plan

## Baseline before code changes

Repository: `SM-CRM-System`, commit `98f16f12c02d5c3fa9001bd775b662d0d5e5824c`.
Clean `main` at inspection on 2026-09-04. Python 3.12.4, pytest 9.1.1.
Canonical commands from `CLAUDE.md` and `.github/workflows/ci.yml`:

```bash
ruff check . && ruff format --check . && pytest
```

Result: lint passed; 63 files formatted; **226 tests passed in 5.05 seconds**. No baseline failures.
No live provider, Twenty workspace or production database was used to establish this baseline.

## Existing regression coverage retained

Extraction honesty and mock/provider boundaries; transcript idempotency and identity resolution;
CLI/demo and evaluation; review queue/UI and approval-gated sync; CRM API/mapping and Person GTM
fields; vault plain/Cairns rendering, manual-edit preservation and raw-body setting; weekly plan,
feedback, queries and Contract-1; logging/no-send structural rules. Keep these tests, not a
replacement suite for the new abstraction.

## Foundation verification

| Risk | Test coverage / acceptance |
|---|---|
| Single-product identity leaks | Same account/person gets two products and a later episode |
| Evidence duplication | Shared source rows remain constant across hypotheses |
| Missing lineage | Missing evidence and missing hypothesis support rejected |
| Cross-product contamination | Wrong pack's signal cannot support a hypothesis |
| Cross-person contamination | Other person's observations fail and service rolls back |
| Premature contact requirement | Account-only hypotheses work |
| Silent overwrite | Identical replay no-op; changed immutable ID/version rejected |
| Partial writes | Service and outer transaction rollback remove all new batch rows |
| Unsafe migration | Populated legacy schema survives two connects; FK check passes |
| Approval bypass | Foundation accepts only HYPOTHESIS_CREATED/unreviewed |
| Fake numeric certainty | Out-of-range/non-finite scores rejected; unknown dimensions null |
| Succession behavior drift | Adapter preserves all sample profile types/scores |
| Implicit backfill | Optional projection tested separately; default ingest stays legacy |
| Legacy state changes | Before/after legacy SQL dump matches during shadow projection |
| Hidden ICP assumptions | Workflow positive, excluded, missing, conflicting and low-signal cases |
| Vacuous evaluation | Empty/malformed/untraceable gold sets fail |
| Missing negatives | Signal comparison measures false positives and false negatives |

The optional bridge verifies exact unique source snippets. Production evidence may contain
paraphrases or repeated text and will require explicit review rather than automatic conversion.
There is no claim that sample parity proves real LLM extraction quality or source attribution.

## Generic gold format v1

One JSON object per file under `examples/opportunity-engine/`: `schema_version`, stable case ID,
exact pack version, evidence records, observation records, expected classification/eligibility/
signal keys and optional timing bounds, labeler and split. The six committed cases are synthetic
**development** cases. None is an independent holdout.

```bash
python -m relationship_intel.opportunity_engine.evaluation --source examples/opportunity-engine
```

Exit 0: all expectations pass. Exit 1: at least one expectation fails. Exit 2: malformed input,
missing/unknown pack, empty directory or read error. JSON report contains per-case findings,
actual classifications/dimensions and aggregate signal precision/recall. Undefined precision or
recall is null when its denominator is zero. Metrics compare signal **keys per case**, not
per-quote extraction recall or real-world opportunity yield.

Legacy `python -m relationship_intel.cli eval` continues to support its existing transcript
frontmatter format. The generic module reuses the Finding shape without changing legacy outputs.

## Real acceptance before expansion

Collect redacted data from both products, including exclusions and ambiguous cases. Label it
independently of the implementation, adjudicate disagreements and reserve account/time-separated
holdout cases. Validate source attribution, fit, material contradictions, stakeholder relevance,
reviewer acceptance and cost coverage. Product-specific quality thresholds and label owners
remain decisions, not implied by passing development fixtures.

Do not run paid-provider or real CRM write tests as part of this foundation. Before later generic
sync, add adapter contract tests for multiple hypotheses per account, product fields, payload-bound
approval, idempotent retry and old Contract-1 consumers. Before later lifecycle code, test every
permitted edge and forbidden shortcut, including suppression and changed approvals.

## Development results

- Storage/service slice: 14 new tests passed.
- Packs/generic evaluation slice: 19 new tests passed; full suite 245 passed.
- That intermediate full check found one long test string in lint; it was corrected.
- Optional legacy projection added a further test; final results are recorded below after the
  canonical check. These results exercise an isolated development copy, not production rollout.

Final canonical verification: **246 tests passed in 5.30 seconds** (226 existing plus 20 new),
lint passed and all 75 Python files passed formatting. Generic evaluation: **6/6 development
cases passed**. No provider calls or production data migrations were performed.

After documentation PR #20 merged, the implementation was reapplied to `ebdba34` (including
Mac mini review-gate PR #19). Reconciliation check: **262 tests passed in 9.80 seconds**;
lint and formatting passed for all 76 Python files, and **6/6 generic development cases passed**.
The added review-gate tests remain intact. This is local validation; hosted CI is a separate gate.
