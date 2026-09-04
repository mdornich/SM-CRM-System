# Qualification rubric — Growth (Succession)

**DRAFT v0 — assembled from Mitch's existing artifacts; Mitch to edit and ratify.** Lock D32 says
Mitch authors this. Cash reviews it later, not now (source: `docs/architecture/phase-13a-growth-os-lock.md` §5.6/D32/D13).

**Scope (D21).** Two wedges only — EOS Practitioner and Acquirer; the wedges' public professional
footprint, no personal data beyond professional contact fields, nothing behind a login (source: lock §6 D21).

**Proof law.** Every verdict carries a URL or document path with publication date and date read, plus
confidence `high`/`medium`/`low`/`unknown`. An inference alone is never a verdict; an unproved
criterion is UNKNOWN (source: `agents/profiles/growth-lead/roles/lead-researcher.md`).

## Wedge 1 — EOS Practitioner

**FIT** needs all four proved:
- Owner-led Professional or Certified EOS Implementer, or senior Implementer controlling
  recommendations — proof is the canonical EOS Implementer Directory profile URL (source: `succession/content/outreach/eos/implementer-list-build-runbook.md` §1,§3).
- Solo practice or small firm with an active recurring portfolio of leadership teams (source: `~/Documents/succession/gtm-personas.md` Persona 1 §Ideal firm and buyer profile).
- Public implementation-practice footprint with repeated Process Component references (source: same, §Online channel behavior "Targeting signals").
- Identity matched on name + firm + geography before a LinkedIn URL is attached (source: `implementer-list-build-runbook.md` §4,§6).

**UNFIT**, any one proved: one-off advisor with no active portfolio; wants a generic SOP binder; will
not sponsor access to the leadership team; expects Succession to own rollout; seeks official EOS
affiliation (source: `gtm-personas.md` Persona 1 "Disqualifiers" + §Qualification scorecard).

**UNKNOWN** is the default — directory profile found but portfolio unverified, or one source only.
Row stays `researching`, never `ready` (source: `implementer-list-build-runbook.md` §6).

Scoring aid Mitch already wrote: six criteria at 0/1/2, working threshold 8/12 for discovery (source: `gtm-personas.md` Persona 1 §Qualification scorecard).

## Wedge 2 — Acquirer

**Deferred per decision A5, 2026-09-04 (`docs/architecture/phase-13a-growth-os-system-architecture.md` §2). Phase 13A qualifies the EOS Implementer wedge only; this section is retained for S4+ and nothing is built or scored against it.**

**FIT** needs all four proved:
- Independent sponsor, search-fund operator, ETA buyer, small holdco, or family-office **direct**
  operator, targeting $1M–$25M-revenue businesses (source: `succession/content/docs/gtm/cold-outbound-requirements.md` §2; `content/outreach/acquirers/list-build-runbook.md` §Population definition).
- Direct operating involvement plus a visible thesis or ≥1 completed acquisition; zero-deal searchers
  are `nurture`, not FIT (source: `list-build-runbook.md` §Day 13).
- A referenceable `{custom_hook}` the prospect published or announced (source: `content/outreach/acquirers/outreach-sequence.md` §Personalization tokens; `list-build-runbook.md` §Launch gate).
- Identity verified against **two independent sources** before `ready` (source: `list-build-runbook.md` §Data hygiene).

**UNFIT**, any one proved: institutional PE (>$500M AUM or dedicated fund IV+); family-office
allocator not operator; broker, appraisal firm, or exit consultant; EOS implementer (route to the
other wedge); pre-LOI-only need; no seller access; passive financial buyer with no operating owner (source: `list-build-runbook.md` §Day 13 + §Anti-patterns; `gtm-personas.md` Persona 2 "Disqualifiers").

**UNKNOWN** — role ambiguous (titles fragment badly across this ICP), one source only, or no
publishable hook (source: `list-build-runbook.md` §Days 9–10, §Launch gate).

Scoring aid: six criteria at 0/1/2, threshold 8/12 (source: `gtm-personas.md` Persona 2 §Qualification scorecard).

## Mapping a verdict to Twenty

Wedge is a tag on the Person; Twenty is the single system of record (source: `succession/content/docs/gtm/gtm-crm-architecture.md` §1,§4).

| Verdict | `Wedge` | `Wedge-Primary` | `Source` | `Lifecycle Stage` |
|---|---|---|---|---|
| FIT | wedge(s) proved; both if both proved | wedge carrying the proof | harvest path: `cold-eos-list`, `cold-acquirer-list-podcast-harvest`, `cold-acquirer-list-searchfunder` | `Cold` on entry |
| UNFIT | unset or `Other` | `Other` | as above | `Lost` (do-not-contact / explicit no) or `Nurture` (right person, wrong time) |
| UNKNOWN | no proposal written | — | — | row stays `researching`; never enters Twenty |

Stages past `Cold` are earned by events, not verdicts: `Contacted` = first sequenced email delivered;
`Engaged` = open+click, reply-not-a-fit, or newsletter click; `Meeting` = booked; `Opportunity` =
meeting happened; `Customer` = deposit paid (source: `gtm-crm-architecture.md` §4 Transitions). The
agent proposes only; nothing reaches Twenty without Mitch's approve act, and every outreach artifact
carries `DRAFT — not sent` (source: `agents/profiles/growth-lead/SOUL.md`; lock D3/D4).

**Decisions (Mitch, 2026-09-04):** (a) v0 uses the FIT / UNFIT / UNKNOWN verdict only; the 0/1/2
scorecard is a reviewer aid, not the gate. (b) A criterion that is proved only partially is UNKNOWN,
never FIT. (c) Not applicable while only the EOS Implementer wedge is active.
