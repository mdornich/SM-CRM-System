# Open questions / next-session decisions

These questions are recorded so the foundation can be reviewed without inventing commercial,
operational or policy answers. None requires adding a provider now.

## Decisions before the next implementation slice

| Question | Proposed direction | Why a decision matters |
|---|---|---|
| Where do pre-hypothesis stages live? | Assessment/work item, separate from evidence-backed hypothesis | Avoid empty hypotheses and clarify transition ownership |
| What constitutes one commercial episode? | Explicit stable episode reference, alternatives linked later | Prevent duplicate validated-opportunity counts |
| Who validates a commercial hypothesis? | Product owner/commercial reviewer; separate from CRM export approval | Defines the north-star numerator and authority |
| Should shadow projection become an ingest option or a batch command? | Resumable batch command first | Stable timestamps, retry checkpoints and ambiguous-evidence review |
| Which real second-product cases are available? | Keep Workflow Audit synthetic until owner supplies redacted cases | Fixture success does not establish abstraction quality in use |
| What is the neutral observation vocabulary? | Small versioned predicates, units and source attribution rules | Prevent pack-specific interpretations masquerading as facts |
| How are corrections and contradictory sources represented? | Append observations plus explicit supersession/review links | Immutable records need a usable correction workflow |

## Decisions before generic production use

- Required evidence freshness, source reliability and corroboration for each product.
- Firm size convention: total employees, contractors, practice unit or legal entity, and as-of date.
- Stakeholder map and authority evidence; an owner is not universally the buyer.
- Generic Twenty representation: distinct hypotheses/custom object versus API-supported
  opportunity fields, external IDs, product/version visibility and payload-bound review.
- Generic archive/read views: evidence references, product interpretation notes and reviewed
  Cairns promotion behavior without overwriting current Succession artifacts.
- Lifecycle edges, holding states, reversal/reopening, expected-version concurrency and approval expiry.
- Evidence retention/access controls, sensitive source storage, and policy-owner-approved geography
  and contact constraints. No compliance regime is inferred from this fixture.
- Product-specific label owners, holdout size, false-positive tolerance, review capacity and
  acceptance thresholds. Existing plan feedback is not automatically a gold label.
- Actual cost units, currency, retry costs and allocation of shared research across products.
- When fixture-only packs may be promoted; promotion must be an explicit versioned decision.

## Gaps deliberately not hidden

No ProviderObservation/Engagement/Outcome implementation, provider waterfall, cost ledger,
full lifecycle, outbound/reply execution, generic CRM export, generic vault renderer, real holdout
set, schema-version ledger or production multi-tenancy. The current `policy` JSON is a reviewed
snapshot, not a validated full product-manifest language or code fingerprint.

The legacy bridge rejects nonexact or repeated snippets and assumes the caller supplies already
resolved canonical identities. A successful substring check alone cannot verify that an LLM
attributed a quote to the right speaker. That must be tested on real sources before automatic use.

## Tomorrow's suggested review agenda

1. Review the Product Brief/PRD and current-versus-target boundary.
2. Accept or revise the assessment/hypothesis distinction and episode semantics.
3. Choose the next small slice: neutral intake + resumable shadow projection, before providers.
4. Identify reviewers and redacted data for Succession and the provisional unrelated fixture.
5. Confirm generic review/CRM direction before anyone changes existing operational behavior.
