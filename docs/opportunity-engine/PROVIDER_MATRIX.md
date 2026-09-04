# Provider build / buy / borrow matrix

Status: architecture allocation and future evaluation checklist. No external providers added.
This matrix makes no claims about current vendor prices, plans, API limits or license terms.
Named vendors in the handoff are candidates to investigate later, not selected dependencies.

| Capability | Build / buy / borrow | Current implementation or intended boundary | Admission gate |
|---|---|---|---|
| Identity and dedupe | Build/retain | Existing deterministic company/person resolution | No regression in identity tests |
| Canonical operational state | Borrow/retain | SQLite, existing connection factory, additive repository | Two-pack model and measured concurrency needs |
| Commercial hypotheses and gates | Build | Product-neutral deterministic services | Traceable support, versioning and negative tests |
| Product interpretation | Build | Reviewed pure Product Packs | Shared neutral inputs; no embedded provider logic |
| Transcript intake | Retain | Local folder and existing Granola adapter | Existing ingestion/retention contract |
| Account discovery | Buy/borrow later | Candidate provider response becomes ProviderObservation | Entity coverage, provenance, restrictions, actual unit cost |
| Search/research | Buy/borrow later | Bounded engine request and normalized evidence | Source quality, reproducible citations, budget control |
| Page extraction/crawling | Buy/borrow later | Capture source material before interpretation | Rendering fidelity, dedupe, source access policy, cost |
| Contact enrichment | Buy later if justified | Staged only after product/evidence qualification | Accuracy, coverage, permitted use, source provenance |
| Contact verification | Buy/borrow later | Deterministic verification policy and expiry | False-valid rate, freshness, operational burden |
| Model extraction/synthesis | Retain bounded adapter | Existing mock/Codex/Anthropic extraction paths | Schema validation and real gold-set quality |
| CRM engagement UI | Borrow/retain | Twenty via supported APIs; existing adapter | Explicit generic mapping and review semantics |
| Evidence archive | Borrow/retain | Obsidian/Cairns, existing review/promotion rules | Citation paths and retention policy |
| Scheduling/integration | Borrow | OS and optional n8n coarse orchestration | Idempotent trigger contract |
| Core waterfall/rate limit/cost policy | Build | Deterministic engine logic, OS budget reference | Offline retry/suppression tests and audited spend |
| Sending/replies | Defer | No new execution path | Separately authorized scope and measured review evidence |

## Why providers wait

The abstraction must work for Succession and the unrelated fixture before a provider can be
selected. Otherwise a vendor's account/contact schema can accidentally become the commercial
domain. The foundation exercises no discovery/enrichment API and requires no new credentials.
Apollo, Tavily, Firecrawl and comparable candidates remain unselected. Existing connected tools
or accounts do not constitute authorization to import contact datasets or run paid research.

## Future scorecard

For each candidate record: capability, supported regions/segments, observed coverage on a fixed
sample, provenance/citation fidelity, freshness, accuracy, rate-limit/retry semantics,
idempotency support, actual per-qualified-hypothesis cost, data retention/export policy,
license/operating constraints, failure modes and exit/migration path. Verify current details
against vendor primary documentation and an approved pilot before committing.

Compare managed service cost with self-hosted infrastructure, maintenance, reliability and
licensing. Do not equate open source with zero operational cost. Store trial evidence and
selection decisions, not unsupported price comparisons.

## Proposed provider waterfall

Low-cost account normalization → product fit gate → evidence discovery/capture → signal and
hypothesis evaluation → stakeholder resolution → contact enrichment → verification → review.
An engine policy determines which providers run, in what order, under what budget and retry
limit. Product Packs express needs and acceptable evidence, not network-specific branching.
The next provider proposal must include fake-provider contract tests before live configuration.
