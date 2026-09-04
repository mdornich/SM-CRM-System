# Architecture and additive migration

## Reconciliation with the repository

Baseline: `98f16f12c02d5c3fa9001bd775b662d0d5e5824c`, clean local `main` at inspection.
The baseline canonical CI commands passed: lint, format and 226 tests.

| Area | Current code reality | Foundation decision |
|---|---|---|
| Intake | Local files and Granola produce `RawTranscript`; content hash dedupes | Retain. Generic evidence may represent other source types |
| Extraction | `schemas.py` and `Extractor` explicitly use Succession profiles/lens | Preserve; add pure packs and explicit legacy projection |
| Identity | `store/repository.py` resolves companies/people deterministically | Reuse canonical IDs; no duplicate Account/Person tables |
| Operational store | SQLite owns identity, review items, sync hashes and planning state | Add `oe_*` tables via existing `connect()` |
| Opportunity identity | `opportunities` has `UNIQUE(person_id, company_id)` | Leave legacy alone; generic hypothesis IDs are independent |
| Evidence | Quotes in interactions/profile JSON and vault, tied to transcripts | Add product-neutral Evidence/Observation records |
| CRM | API adapter and provisioning include Succession opportunity and Person GTM fields | Generic hypotheses do not enter legacy sync |
| Review | Queue, reviewer payload edits, approve/reject and sync gates exist | Keep unchanged; generic approval requires a later explicit contract |
| Archive | Plain and Cairns modes, managed blocks and backups, promotion proposals | Preserve; generic rendering is a later opt-in projection |
| Evaluation | Legacy frontmatter expectations check selected Succession fields | Keep CLI unchanged; add strict generic JSON gold cases |
| Planning | Weekly groups, feedback, drafts and read-side queries are Succession-oriented | Retain; do not mix unreviewed generic hypotheses into weekly priorities |
| Fleet | Contract-1 emits union of fleet/morning-brief shapes | Preserve; generic metrics need an additive report design |
| Deployment | CLI, launchd and Docker scripts operate current pipeline | No deployment/scheduler changes in this slice |

## Important code/document gaps

The governing architecture's draft date predates current review-in-Twenty provisioning, Person
GTM sync and weekly feedback code. The general "no delete" description is too broad for the
entire repository: the CRMAdapter has no destructive interface, but the separate provisioner
contains metadata cleanup and explicit legacy backfill operations. Those pre-existing paths
are not invoked or changed by this work.

Legacy repository writes often commit individually, so the current ingest is not a single
end-to-end transaction. The new generic repository uses savepoints and can compose an atomic
batch on its own connection; it must not promise atomicity around legacy methods that commit.

Existing evaluation can produce an empty result set or have unasserted profiles. The new generic
format requires nonempty cases and explicit signal sets; the old format is preserved to avoid
changing established CLI behavior in this slice.

A nonempty quote is not proof of attribution or truth. The legacy schema requires snippets but
does not itself prove source offsets. The optional bridge checks exact occurrence and refuses
ambiguous repeated snippets; source attribution still originates in legacy extraction and is
labeled as such. It is not a fresh, verified neutral extraction system.

## Ownership

```text
980labsOS control plane
  requests / budgets / scheduling / approvals infrastructure / audit
    |
Opportunity Engine deterministic services
  resolved identity -> Evidence -> Observation
                                  |
                           versioned Product Pack
                                  |
                         SignalObservation -> Hypothesis
                                  |
                         future human validation
                                  |
                         future CRM projection
    |
SQLite operational state       Cairns evidence / reviewed memory
```

Product Packs own ICP, exclusions, interpretation, evidence requirements, stakeholder policies,
offers and eventual research/messaging configuration. The engine owns enforcement, persistence,
provider sequencing and cost arithmetic. Control-plane approval infrastructure does not define
what constitutes a valid commercial hypothesis; the engine must validate that domain decision.

## Lifecycle boundary: challenge to the proposed design

The suggested lifecycle begins with discovery and normalization. At those stages there is not
yet an evidence-backed commercial hypothesis. Putting an empty Hypothesis row into `DISCOVERED`
would weaken the central thesis and force nullable evidence everywhere.

This foundation therefore creates hypotheses only at `HYPOTHESIS_CREATED`. Proposed discovery,
normalization and fit/evidence work belongs to a future **assessment/work item**, keyed by
subject, product and run. The downstream proposed stages remain:

`HYPOTHESIS_CREATED → RESEARCH_PENDING → VALIDATED → STAKEHOLDER_PENDING → CONTACT_READY →
REVIEW_REQUIRED → APPROVED → ENGAGING → ENGAGED → SALES_OPPORTUNITY → WON/LOST`.

The upstream stages (`DISCOVERED`, `NORMALIZED`, `FIT_QUALIFIED`, `EVIDENCE_PENDING`,
`SIGNAL_QUALIFIED`) and holding/terminal outcomes (`REJECTED_FIT`, `NO_SIGNAL`,
`INSUFFICIENT_EVIDENCE`, `NO_CONTACT`, `NURTURE`, `SUPPRESSED`, `EXPIRED`, `DISQUALIFIED`)
remain vocabulary proposals. A decision is needed on which belong to an assessment, hypothesis,
or engagement. There is no implicit numeric stage ordering or permissive transition API today.

## Migration phases

1. **Foundation, implemented:** additive docs, models, tables, repository, pure packs,
   shadow creation, optional exact-quote projection and development gold fixtures.
2. **Shadow ingest:** separately schedule/provide an explicit command that resolves existing
   IDs, captures neutral observations and projects completed transcripts. Add a checkpoint,
   stable timestamps and resumable batches. Reject ambiguous evidence into a review queue.
3. **Parity and second-product review:** use real labeled data to compare legacy classifications,
   attribution, hypotheses, negative cases and human review workload. Fixture success is only
   a structural gate; do not retire legacy extraction on that basis.
4. **Generic review/read projection:** introduce explicit transition guards, versioned decisions,
   evidence details in archive, product-aware UI and a separate generic CRM mapping. Re-review
   when the reviewed payload changes. Preserve Contract-1's existing consumer contract.
5. **Provider pilot:** only after domain/second-pack acceptance, add one budgeted provider behind
   the generic observation boundary, with offline tests and recorded cost/verification policy.
6. **Persistence reassessment:** evaluate concurrency, latency and operational burden after a
   real second pack. Keep SQLite unless measurements justify a separate migration.

## Operational rollout and rollback

Use a feature branch. Before production rollout, back up SQLite with a consistent SQLite backup
and retain the legacy application version; copying an actively written file is not a consistent
backup strategy. The test upgrade uses an isolated legacy database, never production output.

`connect()` retains legacy schema/column migration then applies a transactional, idempotent
`SCHEMA_V2` script. It creates only new tables/indexes; existing rows and constraints are untouched.
Opening a DB creates tables but does not register packs or populate generic evidence.

Rollback application code to the legacy version and leave new tables in place. Do not drop them
as a routine rollback. They contain shadow state and are ignored by old queries. Hypothesis
creation and legacy projection are opt-in Python APIs; there is no automatic dual-write switch.

## Known foundation limits

Immutable append-only records have no correction/supersession workflow, expiry enforcement,
retention deletion, access-control layer or cross-process job queue yet. Observation predicates
are extensible strings rather than a completed shared ontology. Database foreign keys protect
existence; cross-product and subject rules are enforced by the repository, not arbitrary raw SQL.
No API exposes the database connection to an LLM. Generic records cannot yet be browsed in Twenty
or rendered by the legacy vault writer. These are explicit follow-up slices, not hidden parity claims.
