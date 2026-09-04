# Product Pack contract

## Implemented Python interface

`opportunity_engine/packs.py` defines:

```python
class ProductPack(Protocol):
    product: Product
    version: ProductPackVersion
    definitions: tuple[SignalDefinition, ...]

    def assess(self, observations: tuple[Observation, ...]) -> Assessment: ...
```

`Assessment` contains signals, separate score dimensions, classification, eligibility, reason
and scoring version. It is a proposal, not a persisted opportunity. `PackRegistry.register`
rejects duplicate versions, mismatched product/definition ownership and duplicate signal IDs/keys.
Retrieval requires an exact version ID; there is no floating `latest` policy.

Packs are trusted, reviewed Python implementations. The protocol is not a sandbox for arbitrary
third-party plugins. Packs receive one resolved subject's observations, not a database handle.
They must perform no network calls, identity resolution, approval transitions or canonical writes.
`create_hypothesis` loads persisted observations, runs assessment, verifies cited input IDs and
persists product/version/definitions/signals/hypothesis atomically through the repository.

## Version semantics

Product identifies a commercial offering; ProductPackVersion identifies a fixed interpretation
policy. Its `policy` stores the relevant rubric and metadata. Existing version content cannot
be overwritten: same ID/different content fails, and `(product_id, version)` is unique. Change
policy under a new version and re-assess into new records. Historical signals retain their
original definition/version.

There is no automatic code-to-policy fingerprinting yet. Review must ensure the version changes
whenever executable semantics change. The foundation version metadata is not a complete
reproducible runtime snapshot; recording code revision and policy digests is a backlog item.

## Current packs

### Succession

`SuccessionPack` reuses the existing lens prompt, rules, cue tables, weights and threshold.
`assess` supplies a conservative shadow cue path over attributed `statement` observations.
It is not a replacement for legacy extraction: contextual identity and non-fit handling in the
mock extractor are richer than this minimal shadow assessment.

`from_profile` maps an already extracted `SuccessionLeadProfile` without recomputing its
classification or score. It requires every legacy snippet to be present as an observation.
It records a `legacy_assessment` interpretation, not an invented decomposition of the legacy
aggregate into per-dimension evidence. Referral/partner/not-fit/unknown profiles do not become
prospect hypotheses through this adapter.

`project_legacy_profile` adds a source-grounded persistence bridge. It takes a transcript,
profile, resolved account/person IDs, source lens/provider and stable capture timestamp. It
accepts only the current supported lens version and unique exact source snippets; missing or
repeated text fails for review. It stores neutral statements before the legacy interpretation,
then creates an unreviewed hypothesis only for evidence-backed legacy prospect types.

### Workflow Automation Audit, provisional fixture

Product ID: `workflow-audit`; version: `workflow-audit:fixture-v1`; `fixture_only=true`.

Inputs: `employee_count` (integer), `industry` (controlled fixture value
`professional_services`), and `manual_hours_week` (nonnegative number). Each is an observation
with source evidence. Qualification requires 20–250 employees, matching industry and at least
five manual hours weekly. Conflicting values hold for review; missing or invalid fields are
insufficient evidence. The fixture does not infer ownership, exit interest, personal contact
information or buying intent.

The offer is a provisional workflow audit. No landing page, campaign, approved geography,
validated pricing, message sequence or commercialization decision is implied.

## Future complete manifest, not yet executable

| Section | Product-owned content | Engine-owned enforcement |
|---|---|---|
| Identity | Product/version, owner, artifact references | Version integrity and historical references |
| ICP/exclusions | Allowed segments and hard exclusions | Deterministic gates, missing-data handling |
| Discovery | Source priorities, search policy, geography | Provider waterfall, rate limits, dedupe and budgets |
| Signals | Definitions, allowed evidence, freshness | Citation integrity, observation lineage and expiry |
| Qualification | Dimensions, thresholds, contradiction policy | Arithmetic, inspectable results and transition guards |
| Stakeholders | Roles, relevant decision makers, relevance criteria | Identity resolution and verification policy |
| Offer | Value proposition, deliverables, commercial constraints | Required review and version binding |
| Messaging/campaigns | Audience, sequence, templates and experiments | Suppression, approvals and eventual execution gates |
| Research | Bounded tasks, schemas and acceptable sources | Model routing through OS, cost/permission checks |
| Learning | Label taxonomy, outcomes and evaluation splits | Leakage prevention, reports and replay |
| Geography/compliance | Approved operating policy references | Fail-closed eligibility checks; policy owner approval |

Unimplemented sections are not accepted as arbitrary executable configuration. Add a typed,
validated contract for each when its first operational consumer is implemented. A large free-form
manifest now would imply capabilities and enforcement that do not exist.

## Cross-product acceptance

Use the same canonical account/person and source observations with both packs. Store separate
signals and hypotheses, retain the evidence once, permit a later episode for either product,
and assert that generic modules do not import Succession types or field names.
