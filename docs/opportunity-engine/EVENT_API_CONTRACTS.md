# Event and API contracts

## Implemented local APIs

These are Python interfaces, not HTTP endpoints. There is no event bus or deployed server in
this foundation.

| Operation | Inputs | Result and constraints |
|---|---|---|
| `OpportunityRepository.put` | Validated supported record | Stable ID; identical replay no-op; changed immutable content raises `ValueError` |
| `get` | Model type and ID | Validated model; absent record raises `KeyError` |
| `hypotheses` | Optional account/person filter | Ordered hypothesis records, retaining product/version and episode |
| `transaction` | Block of generic repository operations | Savepoint atomicity, rollback on failure |
| `ProductPack.assess` | One subject's observations | Pure Assessment, no writes or external effects |
| `PackRegistry.register/get` | Reviewed implementation / exact version ID | Reject duplicate/mismatched definitions; fail unknown version |
| `create_hypothesis` | Repository, pack, stored observation IDs, stable hypothesis ID, episode, thesis, resolved IDs, creation time | Gated atomic hypothesis creation |
| `project_legacy_profile` | Raw transcript/profile, resolved IDs, lens/provider, stable capture time | Optional unreviewed hypothesis and provenance chain; no legacy writes |
| `run_gold_evaluation` | JSON file/directory and registry | Findings, pass counts, signal precision/recall |

Missing parents fail through repository checks or SQLite foreign keys. Callers must treat both
as failed commands; they must not silently retry with weaker evidence. Changed immutable IDs,
unknown versions and mismatched subjects are permanent validation failures until corrected.
SQLite transient lock handling is not yet a job retry policy; no provider retry loop is added.

## Proposed command envelope, for the orchestration milestone

```json
{
  "schema_version": 1,
  "command_id": "stable-id-for-this-request",
  "command_type": "AssessSubject",
  "correlation_id": "research-run-id",
  "causation_id": "source-event-id",
  "requested_at": "2026-09-04T12:00:00Z",
  "actor": {"kind": "service", "id": "crm-source"},
  "pack_version_id": "workflow-audit:fixture-v1",
  "subject": {"account_id": 42, "person_id": null},
  "input": {"observation_ids": ["observation-id"]},
  "policy_refs": {"budget_id": "os-budget-id", "permission_decision_id": "os-decision-id"}
}
```

Illustrative shape only. A real AssessSubject request needs the pack's required observations;
one ID in this example does not establish qualification. Do not forward credentials, whole raw
transcripts or unrestricted instructions in command metadata. The engine validates business
inputs; 980labsOS validates execution permissions and budget availability.

## Proposed events and delivery rules

Potential committed facts: `EvidenceRecorded`, `ObservationRecorded`, `AssessmentCompleted`,
`HypothesisCreated`, `HypothesisReviewed`, `EngagementRecorded`, `OutcomeRecorded`.
Only the first four align with current domain concepts; no events are emitted today.

A future envelope should include event ID/type/schema version, aggregate ID/version,
correlation/causation IDs, occurred/recorded times, actor, pack/scoring versions where applicable,
and references to evidence instead of full source bodies. Write state and an outbox row in one
transaction. Publish after commit; retries reuse the event ID. Consumers track processed IDs
and validate payload hashes; same ID with different content is a conflict.

Assume at-least-once delivery. Do not claim exactly-once network effects. Use deterministic
provider request keys, adapter sync state, bounded retries and explicit reconciliation for
ambiguous remote successes. Consumer-specific ordering and stale aggregate versions must be
checked before a transition; timestamps alone are not concurrency control.

## Approval and integration contracts

The eventual approval command must bind reviewer identity, policy authority, expected aggregate
version, reviewed payload hash, decision and reason. A content change must invalidate or renew
approval. CRM export approval, commercial validation, canonical-memory promotion and permission
to contact are distinct decisions; one cannot silently imply the others.

Twenty remains behind supported APIs/webhooks and `CRMAdapter`. Generic export needs an explicit
product-aware external identity and field mapping. Do not flatten multiple hypotheses into the
legacy pair-unique opportunity, or write to Twenty's internal database. Existing sync is unchanged.

n8n may deliver schedule/webhook triggers and coarse integration steps. Suppression, rate limits,
identity resolution, score arithmetic, provider waterfalls and cost accounting belong in engine
code. Agents may suggest bounded research/interpretation; they do not issue raw SQLite writes.
Contract-1 keeps its current output; generic metrics will be additive and consumer-tested later.
