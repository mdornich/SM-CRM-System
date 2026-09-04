# Phase 13A C3 → C3b confidence mismatch

Status: implementation stopped under the ratified #1261 round-2 brief §7
(2026-09-04). This is a finding, not a completed integration contract.

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
`src/relationship_intel/cold_intake.py:38–53` likewise defines numeric
`QualifiedLead.confidence`, but that is the later assessment boundary.

The brief §2 requires confidence to be carried through C3b. The producer's
string cannot be carried unchanged into the existing Observation model.
Assigning a numeric interpretation to `"high"` would introduce a calibration
policy absent from these contracts. Fetch confidence must not silently become
commercial qualification confidence; see `SCORING_CALIBRATION.md`.

## Required follow-up

Existing tracked debt — owner: Mitch / #1261 and OE-01 pack workstream.
Ratify a separate brief specifying whether C3 changes its output or C3b applies
an explicit fetch-confidence mapping, including unknown/null handling and the
separate assessment-confidence semantics. The round-2 brief §7 explicitly says
to document a mismatch and stop; no producer, intake, schema, lifecycle or
approval behavior is changed here.

The pure mapper, mirrored C2–C4 fixtures, byte-hash guard, and scratch-database
contract test remain blocked by that decision. This finding does not satisfy
those acceptance criteria or close #1261. The canonical contract page and
980labsOS producer tests belong to the companion repository pass. No live
scraper, provider, or external request/response path was verified by this pass.
