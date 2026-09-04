# Product Brief: 980labs Opportunity Engine

## Problem and thesis

SM-CRM already turns transcripts into evidence-backed relationship intelligence. Its useful
identity, review, archive, CRM and planning infrastructure is broader than Succession, but
its extraction schemas and opportunity identity still embed Succession assumptions. Adding a
second product through another prompt alone would leave those assumptions in storage and sync.

The Opportunity Engine discovers and evaluates commercial hypotheses against shared entities
and evidence. One firm might need succession advice this year and a workflow audit next year.
Those are separate hypotheses, even when they involve the same person. A source observation
can inform both without copying it into separate product databases.

## Users and jobs

- 980labs operator: configure product criteria, inspect why an account merits attention,
  compare research costs and prioritize reviewable opportunities.
- Product owner or commercial reviewer: accept, correct or reject a hypothesis using its
  evidence, exclusions, contradictions and rationale.
- Relationship owner: use Twenty for approved contacts, summaries, stages and follow-up work.
- 980labsOS agent: request bounded research or analysis, receive operational reports and route
  approvals without becoming the owner of commercial state.

## Value proposition

Reuse account/person identity, evidence capture, qualification machinery and evaluation across
products. Keep the reason for pursuing an opportunity inspectable. Learn from labeled decisions
and eventual outcomes, with deterministic costs and scoring, instead of scaling unmeasured lead lists.

## Product boundaries

980labsOS owns task execution, model routing, permissions, budgets, secrets, scheduling,
context/memory coordination, approvals infrastructure and audit/observability. The Opportunity
Engine owns the meaning of commercial evidence, signals, hypotheses, scoring, stakeholder
resolution and eventual engagement/outcome records. Product Packs supply policies and commercial
interpretation. Twenty is the human-facing CRM; Cairns is the evidence archive and canonical
memory destination through its established promotion review.

SQLite remains the canonical operational store in this milestone. The engine does not become
Mitch's canonical identity/knowledge memory. n8n may trigger coarse work but cannot replace
transactional rules or qualification logic. LLMs propose extractions and synthesis; validated,
deterministic services own canonical writes.

## Milestone deliverable

An additive domain foundation with evidence and observation separation, versioned products,
product-specific signals, multiple hypotheses per subject, a Succession compatibility adapter,
and an unrelated second pack fixture. Existing product workflows continue unchanged. The
foundation is reviewed before adopting any generic projection as the production default.

## Success

North star: **Validated commercial opportunities discovered per unit of research + outreach cost.**
A future validated opportunity must have traceable evidence, pass product qualification,
resolve material contradictions and receive the defined validation decision. Merely creating
an unreviewed hypothesis does not count. Report by product, policy version, cohort and time window.

Include actual provider and model costs, plus an explicitly documented allocation of operator
time if used. Avoid counting retries or alternate hypotheses for the same commercial episode
as independent wins. Unknown cost is missing coverage, not zero cost. Neither real cost
accounting nor the validated-stage metric is implemented in this foundation.

Milestone success is narrower: green legacy regressions; two unrelated packs through the same
service and tables; evidence reuse; additive repeatable migration; and no route from a generic
hypothesis to unapproved external action.
