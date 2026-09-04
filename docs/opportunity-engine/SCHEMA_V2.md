# Generic Schema v2

Authoritative implementation: `opportunity_engine/models.py`, `schema.py`, `repository.py`.
All new tables use `oe_` names to avoid colliding with legacy `opportunities` and simplify review.
The exact executable DDL is in `schema.py`; this document describes its contract.

## Entity mapping

| Domain | Storage | Key and important constraints |
|---|---|---|
| Account | existing `companies` | Existing integer ID and entity resolution |
| Person | existing `people` | Existing integer ID; no product affiliation required |
| Product | `oe_products` | Text ID, name, description |
| ProductPackVersion | `oe_pack_versions` | Text ID, product FK, unique product/version, policy JSON, fixture flag |
| Evidence | `oe_evidence` | Text ID, source type/ref, hash, locator, excerpt, capture/occurrence times |
| Observation | `oe_observations` | Text ID, evidence FK, account/person FKs, predicate, JSON value, method/confidence |
| SignalDefinition | `oe_signal_definitions` | Text ID, pack version FK, key, description; unique version/key |
| SignalObservation | `oe_signal_observations` | Text ID, definition FK, observation FK, strength/rationale; unique definition/observation |
| OpportunityHypothesis | `oe_hypotheses` | Text ID, account/person FKs, pack version FK, episode, thesis, creation time, scores/version, state/review |
| Hypothesis support | `oe_hypothesis_signals`, `oe_hypothesis_observations` | FK joins with stable position and no duplicates |

ProviderObservation, Engagement and Outcome are deferred domain concepts, not empty tables
pretending to implement provider or outreach workflows. Future ProviderObservation should record
request/response provenance, provider identity, observed/captured times, request hash, verification
state and actual cost. Evidence derived from it should reference that provenance. Engagement
should belong to a hypothesis and approved campaign; Outcome should preserve labeled events and
attribution rather than overwrite the hypothesis thesis.

## Required fields and meaning

Evidence source identity and content hash describe captured source material, not an LLM summary.
`locator` identifies the excerpt location (for the legacy bridge, character start/end).
`captured_at` is timezone-aware; `occurred_at` is optional and must not be invented from a
capture date. The bridge leaves it null because the current transcript date has no timezone.
Excerpts are retained evidence, not whole raw transcript storage; existing raw-body settings
continue to govern the legacy archive.

Observation records say what was observed and by what method, about at least one known subject.
`statement` is a verbatim attributed quote; persistence checks it occurs in the source excerpt.
Other predicates require trustworthy extraction/labels but are not semantically verified against
source prose by the foundation. For example, numeric firm size may be human-extracted from a
quoted sentence. Confidence represents the extraction/observation confidence, not sales success.

SignalObservation is product interpretation of an Observation under a SignalDefinition. Its
strength is bounded 0–100. Hypothesis keeps all supporting observations, including fit evidence
that may not itself produce a timing signal. This prevents losing the source of qualification.

Scores are named dimensions, not a single opaque total. Null dimensions are unknown. JSON is
used for extensible policy, observation values and the typed score object; relations remain FKs
and explicit join tables. No nested blob replaces evidence or subject references.

## Identity and deduplication

- Products and pack versions use explicit namespaced IDs chosen by their reviewed implementations.
- Evidence has natural uniqueness `(source_type, source_ref, content_hash, locator)`.
  Same content from different sources remains separate provenance; global does not mean collapsing
  independent witnesses into one source.
- Callers should use stable evidence/observation IDs. The bridge hashes source identity, content
  hash and location, then derives observation IDs from evidence, subject and extraction method.
- Generic hypotheses use stable command-assigned IDs. `episode_key` groups a commercial episode;
  it is not unique. There is intentionally no unique account/person or account/person/product key.
- A changed thesis, interpretation, evidence or policy requires a new immutable record/version.
  Automatic same-episode semantic dedupe and supersession are deferred. Multiple alternative
  hypotheses are allowed, but must not later inflate the north-star validated-opportunity count.

Natural-key aliases with different IDs fail explicitly rather than silently returning another
record. A future ingestion API may canonicalize aliases before `put`; it must not conceal conflicts.

## Integrity and transactions

Pydantic rejects extra fields, empty identifiers, invalid scores, absent subjects and invalid
hypothesis state. `put` revalidates inputs even when supplied with unchecked model construction.
SQLite foreign keys enforce parent existence, numeric checks bound stored strengths/confidence,
and required text/subject columns are non-null where appropriate.

The repository additionally ensures every signal belongs to the hypothesis pack version, cites
a supporting observation, and matches the hypothesis subject. An account-only observation can
support a person/account hypothesis; another person's observation cannot. Raw SQL is not a
supported domain mutation API and can bypass these cross-row application validations.

`transaction()` uses savepoints so a failed multi-record service rolls back its own work. Use a
dedicated connection from `store.db.connect`, whose foreign keys are enabled; do not mix
commit-calling legacy repository writes into the same generic transaction.

## Migration and reversibility

On connect, existing schema/migrations still run; then a transactional `CREATE ... IF NOT EXISTS`
script creates the new tables/indexes. There are no renames, drops, copies or constraints added
to legacy rows. Repeated application does not add records. Tests construct a populated old
schema, open it twice and verify prior dump statements and referential integrity are preserved.

This v2 foundation uses the repo's create-on-connect convention rather than introducing a second
migration framework. A schema-version ledger and ordered migration runner should precede any
future alteration of the new tables; `IF NOT EXISTS` alone cannot upgrade an existing definition.
Downgrade application code without deleting shadow data. Production backup and explicit rollout
remain operational steps outside this development change.
