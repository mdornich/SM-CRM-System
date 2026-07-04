# Data Model

Authoritative code: `src/relationship_intel/extraction/schemas.py` (Pydantic) and
`src/relationship_intel/store/db.py` (SQLite). This doc explains the shape and the rules.

## Closed vocabularies (defined once, in `schemas.py`)

| Enum | Values |
|---|---|
| `LeadType` | cold, warm, active, referral_source, partner, not_fit, unknown |
| `Stage` | new, nurture, discovery, qualified, active_opportunity, stalled, closed_won, closed_lost, not_fit |
| `Urgency` | low, medium, high, unknown |
| `TimingWindow` | immediate, 0_3_months, 3_6_months, 6_12_months, long_term, unknown |
| `IdentityConfidence` | high, medium, low |
| `ReviewStatus` (ORD-0003) | unreviewed, reviewed, corrected, confirmed |
| `ApprovalStatus` | proposed, approved, rejected, executed |

The lens prompt, the store, and the Twenty stage mapping all reference these —
one place to evolve.

## Extraction models

`ExtractedRelationshipIntelligence` = transcript metadata + people + companies +
lead profiles + conversation summary + recommended CRM actions, stamped with
`llm_provider` and `lens_version` provenance and `review_status: unreviewed`.

**Hard rule (validator-enforced):** a `SuccessionLeadProfile` with
`lead_type != unknown` must carry at least one evidence snippet. Unknown fields
are `None`/`unknown` — never invented.

## Canonical store (SQLite)

Pipeline **operational state only** — never canonical personal memory (Cairns
keeps that role; see `docs/architecture.md` §3.3). Tables: `transcripts`
(hash-unique), `people`, `companies`, `opportunities`, `lead_profiles`,
`interactions`, `crm_sync_state`, `plans`.

## Entity resolution (architecture.md §3.4, implemented in `repository.py`)

People, in authority order:

1. **Email match** (case-insensitive, exact).
2. **Normalized name + company** (lowercase, punctuation/honorifics stripped).
3. **Name-only with no company conflict** → same person, flagged
   `identity_confidence: medium`.
4. **New person**; flagged `needs_review` when edit-distance ≤ 2 from an
   existing normalized name.

Companies: normalized name (Inc/LLC/Co/… suffixes stripped); **website domain
match overrides name**. Ambiguity surfaces in the weekly plan's "Needs Review"
section — never silently merged.

## CRM sync idempotency

`crm_sync_state` stores `(provider, object_type, local_id) → crm_id +
last_pushed_hash`. Unchanged payload hash → the record is skipped entirely.
The adapter interface has **no delete methods** (test-enforced).
