# Phase 13A C3 → C3b contract mismatches

Status: only the C3 → C3b mapper is stopped under the ratified #1261 round-2
brief §7 (2026-09-04). Independent fixture and C4 intake coverage is implemented.
This is a finding, not a completed integration contract.

## Observed contracts

The merged 980labsOS producer at commit
`74d189a932f9c63e85ca0c270914e95bd0e75962`,
`scripts/n8n/succession_enrichment.py:254–266`, emits the literal string
`"high"` as each successful evidence record's `confidence`. Its committed
`tests/fixtures/phase13a/succession-enrichment-v0-output.json` also carries
`"confidence": "high"`.

The SM-CRM consumer at commit `0e92e1ff916a40c0fcf6bc825fb01ee4beff5119`,
`src/relationship_intel/opportunity_engine/models.py:51–56`, requires
`Observation.confidence` to be a finite float in `[0, 1]`.
It has no default and does not accept null; independently,
`src/relationship_intel/opportunity_engine/schema.py:26` requires
`confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1)`.
`src/relationship_intel/cold_intake.py:36–50` likewise defines numeric
`QualifiedLead.confidence`, but that is the later assessment boundary.

The brief §2 requires confidence to be carried through C3b. The producer's
string cannot be carried unchanged into the existing Observation model.
Assigning a numeric interpretation to `"high"` would introduce a calibration
policy absent from these contracts. Fetch confidence must not silently become
commercial qualification confidence; see `SCORING_CALIBRATION.md`.

Two independent blockers also prevent the proposed mapping:

- C3 carries no `locator`. `Evidence.locator` is a required nonempty `Key`
  (`src/relationship_intel/opportunity_engine/models.py:9,34`), and
  `src/relationship_intel/opportunity_engine/schema.py:17–19` requires a non-null
  locator and includes it in evidence uniqueness. A locator derivation policy
  must be specified rather than silently substituting `source_ref`.
- C3 carries the external string person ID `"person-fetchable"`.
  `SubjectRecord.person_id` accepts a positive local integer or null, but requires
  an account or person (`models.py:40–47`); the fixture supplies no account.
  `schema.py:23,27` references `people.id` and requires a subject.
  Resolving this external identity requires the `people_external_ids` database
  crosswalk (`src/relationship_intel/store/repository.py:234–249`). That lookup
  is I/O, making AC4b internally inconsistent if the no-I/O mapper must resolve
  identity itself. The planner must define a separate resolution boundary that
  supplies an already-resolved subject to the pure mapper, or revise the
  constraint in a separately ratified brief. No local ID is invented here.

## Required follow-up

Existing tracked debt — owner: Mitch / #1261 and OE-01 pack workstream.
All three mismatches predate this PR in the merged contracts cited above.
Ratify a separate brief specifying whether C3 changes its output or C3b applies
an explicit fetch-confidence mapping, including unknown/null handling and the
separate assessment-confidence semantics, locator derivation, and the identity
resolution boundary. Return AC4b's no-I/O inconsistency to the #1261 planner.
The round-2 brief §7 explicitly says
to document a mismatch and stop; no producer, intake, schema, lifecycle or
approval behavior is changed here.

The pure mapper and its successful row-mapping test remain blocked by
these three unresolved contracts (acceptance criterion 4b). This PR does not close #1261 or claim
merge readiness. No C3b rows or numeric fetch-confidence conversion are invented.

## Independent contract coverage

`tests/test_phase13a_contracts.py` hashes the local fixture bytes, loads C4 with
the production `load_qualified_lead` / `QualifiedLead` consumer, checks shared
person identity and evidence reference across C2/C3/C4, and runs the real
`intake-lead` CLI twice on a scratch database. It checks pending review state,
identity crosswalks, replay, and preservation of null optional metadata.

All files below live in `tests/fixtures/phase13a/contracts/`:

| Fixture | SHA-256 |
| --- | --- |
| `succession-enrichment-v0-input.json` | `e42c31f2293bfc43fc8089ded465175e0e74b153755888b4d134b295b9e921e2` |
| `succession-enrichment-v0-output.json` | `2848bc0ee5965253ef4f96759aee8c9e300599f9e117d91a44eaa468be5db9c8` |
| `qualified-lead-v0.json` | `6bae54567acc98c15ff4a173150f4b539fb3d47cf6763592dfbd64ff9413706e` |

The C2 input and C3 output are verbatim Git blobs from 980labsOS commit
`74d189a932f9c63e85ca0c270914e95bd0e75962`, under `tests/fixtures/phase13a/`.
The existing three-person fixture includes one successful synthetic person,
`person-fetchable`, plus failed and blocked cases. C4 follows that successful
person. Its professional fields and 0.92 assessment confidence are authored
synthetic test inputs, not an executed assessment or a live API response.
Its shape is consumed by `cold_intake.py:36–50`; accepted wedge/lifecycle values
come from `crm/twenty_adapter.py:127–129`. Optional fields remain null because
this fixture does not assert an existing pack, draft, email, or title.

`SHA256SUMS.json` pins the bytes for the local hash test. Planned future work —
owner: 980labsOS #1261 companion builder: mirror these files and the hash manifest
into the companion `contracts/` directory, add its local hash guard, and record
these hashes in the canonical contract page. That directory was absent from the
companion worktree at inspection; cross-repo completion is not claimed here.
This is independent of the three mapper blockers above.

The canonical contract page, enrichment validation, and nine decision answers
(criteria 1, 3, 5) belong to the 980labsOS companion pass under brief §2.
No live scraper, provider, or external request/response path was verified by
this offline pass. Planned future work — owner: #1261 integration workstream:
verify real provider behavior before any live-capability claim.

## #1277 ingestion builder follow-up (2026-09-04)

The ratified #1277 brief §2 resolves the original confidence, page locator and
identity-boundary decisions. `opportunity_engine/ingest.py` now maps whole-page
records without I/O, resolves existing Twenty identities at the command boundary,
and writes OE rows in a file transaction. Unknown confidence retains its label and
uses the mandated numeric floor. Receipt counts do not create evidence.

Two acceptance gaps remain; this implementation is not merge-ready:

- **PR-introduced blocker — owner: Mitch / #1277 planner and #25 pack workstream.**
  The brief requires presence values `{present: true, url, confidence_label}` and
  prohibits pack changes. `SuccessionColdPack.assess` accepts only boolean presence
  values and explicitly holds objects at UNKNOWN. The new regression starts with
  the FIT example, ingests its evidence, retains its full reviewer proofs, and
  demonstrates UNKNOWN with unreadable proof. It does not claim the requested FIT
  acceptance passed. Ratify the producer/consumer value alignment before merge.
- **Environment-only limitation — owner: #1281 producer / #1277 planner.**
  The referenced `980labsOS/docs/operations/phase-13a-brief-intel-gathering.md` §2A
  is absent in the available companion checkout and its HEAD. `gh api` could not
  connect to api.github.com to retrieve it. The brief lists observation predicates
  but does not define their source linkage, span field names, or value shape.
  Nonempty `observations[]` therefore fail before any resolution or writes;
  pass-through and `chars:<start>-<end>` support remain unimplemented pending the
  real contract. No replacement producer fixture or wire format was invented.

Whole-page source mapping uses `eos_profile`, `website`, and `linkedin`; only
`eos_profile` is present in the pinned producer output. The other two names follow
its input fields and are an unverified integration assumption, not verified live
behavior (**planned future work — owner: #1277/#1281 integration workstream**).
Unknown source types fail validation. No external request path is enabled here.
Changed source content must carry its changed producer content hash; changing
excerpt metadata under the same immutable source/hash/locator is rejected.
