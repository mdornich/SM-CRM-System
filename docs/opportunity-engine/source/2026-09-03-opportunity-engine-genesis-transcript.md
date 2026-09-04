# Opportunity Engine genesis — source transcript

> Status: primary-source brainstorming evidence, not a canonical specification.
>
> Source conversation: **Lead Gen Handoff Review**
>
> ChatGPT conversation ID: `6a9a49c7-3184-83ea-aca7-3350a673bec8`
>
> Source URL: <https://chatgpt.com/c/6a9a49c7-3184-83ea-aca7-3350a673bec8>
>
> Source date: 2026-09-03 (America/Chicago)
>
> Captured: 2026-09-04
>
> Coverage: focused verbatim excerpt covering the multi-product architecture pivot and
> the naming of the Opportunity Engine. The surrounding thread also contains the
> initial Succession research report, repo-placement discussion, generated package
> handoffs, and GitHub connector troubleshooting.

This is the visible user/assistant exchange in which the architecture stopped being a
Succession-centered lead-generation system and became a product-agnostic 980labs
Opportunity Engine. Typos, capitalization, and wording are preserved. UI-only empty
assistant turns are omitted. The stable ChatGPT turn and message IDs are retained so
the excerpt can be checked against the source conversation.

## Turn 7 — User

Message ID: `32faefce-b66b-4cbd-ab7c-437bca2f3c3c`

> That architecture seems like it’s built around Succession and not 980labs. I want to be able to plug other product opportunities unrelated to succession into the toolset to sell them separately from Succession

## Turn 8 — Assistant

Message ID: `e218c75a-dbd4-4501-b0a0-4a04226f3cb5`

You're right. The architecture I gave you still makes Succession the center of gravity, with 980labs acting as infrastructure beneath it.

That is backwards for what you're trying to build.

The better model is:

980labs owns the prospecting/opportunity engine. Succession is only one product configuration running on top of it.

You should be able to add another product later—completely unrelated to succession—without rebuilding discovery, research, scoring, contact resolution, outreach, CRM sync, or learning infrastructure.

The architecture should look more like this:

```text
                         ┌──────────────────────────┐
                         │        TWENTY CRM        │
                         │ Companies / People /     │
                         │ Opportunities / Activity │
                         └────────────▲─────────────┘
                                      │
                                CRM Adapter
                                      │
┌─────────────────────────────────────┴────────────────────────────────────┐
│                         980labs REVENUE ENGINE                           │
│                                                                          │
│  Account Discovery       Entity Resolution       Contact Resolution      │
│  Enrichment Waterfalls   Evidence Store           Research Engine         │
│  Signal Engine           Qualification Engine     Opportunity Engine      │
│  Scoring Engine          Campaign Engine          Outreach Engine         │
│  Reply Processing        Experimentation          Learning / Analytics    │
│                                                                          │
└───────────────────────────▲──────────────────────────────────────────────┘
                            │
              Product-specific configuration / plugins
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
   ┌─────────────┐    ┌─────────────┐   ┌─────────────┐
   │ Succession  │    │ Product B   │   │ Product C   │
   │             │    │             │   │             │
   │ ICPs        │    │ ICPs        │   │ ICPs        │
   │ Signals     │    │ Signals     │   │ Signals     │
   │ Messaging   │    │ Messaging   │   │ Messaging   │
   │ Offers      │    │ Offers      │   │ Offers      │
   │ Campaigns   │    │ Campaigns   │   │ Campaigns   │
   │ Scoring cfg │    │ Scoring cfg │   │ Scoring cfg │
   └─────────────┘    └─────────────┘   └─────────────┘

                            │
┌───────────────────────────┴──────────────────────────────────────────────┐
│                         980labs PLATFORM                                 │
│                                                                          │
│ Agent/task runtime │ Model routing │ Budgets │ Secrets │ Permissions     │
│ Scheduling         │ Approvals     │ Memory  │ Observability │ Tooling    │
└──────────────────────────────────────────────────────────────────────────┘
```

The key distinction is that there are really three layers, not two.

### 1. 980labs Platform

This is the lowest-level reusable infrastructure.

It should know nothing about leads, companies, campaigns, succession, or sales.

It owns things such as:

- task execution
- model routing
- tool permissions
- agent runtime
- budgets
- secrets
- approvals
- scheduling
- observability
- event logging
- memory/context
- retries
- rate limiting

This is your generic Agentic OS.

### 2. 980labs Revenue Engine

This is the layer I was missing.

This is a reusable commercial-opportunity platform that can support any product you want to sell.

It owns concepts such as:

- Account
- Person
- Evidence
- Signal
- Opportunity
- Product
- Offer
- Campaign
- Message
- Interaction
- Outcome

And reusable capabilities such as:

- company discovery
- company normalization
- entity resolution
- contact discovery
- provider waterfalls
- research
- evidence extraction
- signal evaluation
- account qualification
- opportunity generation
- scoring
- message generation
- outbound
- reply classification
- CRM synchronization
- experimentation
- learning

Succession should consume those primitives, not own them.

### 3. Product modules

Succession then becomes a product package.

A product package answers:

What are we selling, to whom, why would they care, what evidence indicates they may care now, who should we contact, and what should we say?

A Succession package might contain:

```text
Product
  name: Succession

ICPs
  founder-led manufacturer
  multi-generation family business
  founder-dependent professional services firm
  ...

Signals
  leadership_transition
  first_external_coo
  generational_transfer
  owner_retirement_language
  key_person_dependency
  sale_preparation
  ...

Stakeholders
  founder
  owner
  CEO
  president
  family successor
  board member

Offers
  succession assessment
  continuity planning
  leadership transition engagement
  ...

Campaigns
  founder transition
  professionalization
  generational succession
  ...

Scoring configuration
  fit weights
  signal weights
  decay curves
  minimum evidence
```

Now suppose you launch something completely unrelated, say a product selling AI workflow automation to regional accounting firms.

You should only need to create:

```text
Product: AI Workflow Automation

ICPs:
  20–200 person accounting firms

Signals:
  hiring automation roles
  rapid headcount growth
  software migration
  repetitive hiring
  PE acquisition
  margin pressure
  ...

Stakeholders:
  managing partner
  COO
  CIO
  director of operations

Offers:
  automation audit
  workflow implementation
```

Everything else should continue working.

### The deeper architectural change

The most important concept should therefore not be `SuccessionOpportunity`.

It should be a generic:

```text
OpportunityHypothesis
```

with something like:

```text
OpportunityHypothesis
---------------------
id
product_id
account_id

icp_id

hypothesis_type
hypothesis

evidence_ids[]
signal_ids[]
contradiction_ids[]

fit_score
timing_score
evidence_score
reachability_score
overall_score

recommended_offer_id
recommended_campaign_id

state
created_at
expires_at
```

That immediately makes the platform multi-product.

Same with Signals.

Avoid:

```text
succession_signal
```

Use:

```text
SignalObservation
-----------------
account_id
product_id
signal_definition_id
evidence_ids
strength
confidence
observed_at
expires_at
```

The definition of the signal lives in the product package.

The signal engine itself lives in 980labs Revenue Engine.

### Products should be first-class entities

I'd make `Product` one of the core objects.

```text
Product
-------
id
name
slug
status
owner

default_crm_pipeline
default_sender_profile

qualification_policy_id
scoring_policy_id
research_policy_id
outreach_policy_id
approval_policy_id
```

Then underneath it:

```text
Product
 ├── ICPs
 ├── Signal Definitions
 ├── Stakeholder Definitions
 ├── Offers
 ├── Campaigns
 ├── Messaging Policies
 ├── Landing Pages
 ├── Research Instructions
 ├── Qualification Policies
 └── Scoring Policies
```

This gives you a very powerful operating model.

You can tell 980labs:

Run opportunity discovery for Product X against this market universe.

The platform doesn't care what Product X is.

### A better abstraction for ICPs

Even ICP logic should be generic.

Instead of hardcoding succession rules, define reusable criteria:

```text
ICPDefinition

firmographic_rules
technographic_rules
geographic_rules
ownership_rules
behavioral_rules
exclusion_rules
required_signals
preferred_signals
stakeholder_rules
```

The qualification engine executes the rules.

Product configuration determines their values.

For Succession:

```text
ownership_rules:
  founder_led = preferred
```

For another product:

```text
technographic_rules:
  uses_salesforce = required
```

Same engine.

### The Signal Engine should also be product-agnostic

This is important because a single observed fact may matter differently to multiple products.

Suppose the evidence says:

ABC Manufacturing hired its first COO.

For Succession:

```text
signal:
management_professionalization

weight:
high
```

For an executive recruiting product:

```text
signal:
leadership_team_expansion

weight:
medium
```

For an ERP consulting product:

maybe irrelevant.

Therefore you want:

```text
Evidence
    ↓
Signal Evaluators
    ↓
Product-specific interpretations
```

rather than:

```text
Evidence
    ↓
Succession Signal
```

The evidence itself should be globally reusable.

That gives you another major benefit.

If 980labs has already researched ABC Manufacturing for Succession, and six months later you create a different product targeting that same company, you shouldn't pay to rediscover:

- company size
- ownership
- executives
- website
- locations
- technology
- news
- leadership changes

You already own that intelligence.

That means the actual durable asset isn't merely the Succession Opportunity Graph.

It becomes a broader:

### 980labs Commercial Intelligence Graph

Something closer to:

```text
                   Company
                  /   |    \
                 /    |     \
             People Evidence Attributes
                |       |
                |       ▼
                |    Observations
                |       |
                |       ▼
                └─── Signals
                      / | \
                     /  |  \
                 Product A Product B Product C
                    |        |        |
                 Hypothesis Hypothesis Hypothesis
                    |        |        |
                 Campaign  Campaign  Campaign
                    \        |       /
                     \       |      /
                         Outcomes
```

That becomes much more strategically interesting.

### Twenty should also be multi-product

Twenty should not have a Succession-specific CRM architecture at its root either.

I would likely structure CRM around:

```text
Companies
→ universal

People
→ universal

Opportunities
→ universal
```

## Turn 9 — User

Message ID: `cad5f6fa-4a08-4251-adc1-d11c91bcb10a`

> Didn’t the prompt tell you that already?

## Turn 10 — Assistant

Message ID: `67707e15-181e-4e36-8e82-71d0fcb9e2e6`

Yes. Your prompt explicitly said Succession should not be designed as an isolated application and that this lead-gen system should potentially be the first serious production workload on the broader 980labs agentic fleet.

I underweighted that constraint and made the architecture too Succession-centric. The cleaner framing is:

980labs should own the generalized commercial intelligence and outbound platform. Succession should be one product configuration running on top of it.

That means capabilities like account discovery, entity resolution, enrichment waterfalls, evidence collection, signal detection framework, scoring framework, contact resolution, research orchestration, personalization infrastructure, outbound sequencing, reply classification, learning loops, approvals, budgets, observability, and Twenty integration should mostly be 980labs platform capabilities.

Succession should contribute only its domain layer: its ICPs, succession-specific signal taxonomy, qualification rules, opportunity definitions, messaging strategy, campaigns, artifacts, landing pages, and product-specific learning labels.

So the conceptual architecture should look more like:

```text
980labs Revenue / Opportunity Engine
│
├── Shared data & identity
├── Account discovery
├── Signal framework
├── Research & evidence
├── Contact resolution
├── Qualification/scoring framework
├── Campaign orchestration
├── Outreach infrastructure
├── Reply processing
├── CRM integration (Twenty)
├── Learning/experimentation
├── Agent/task runtime
├── Models / tools / budgets / approvals
└── Observability
          │
          ├──────── Succession Product Pack
          │          ├ ICPs
          │          ├ succession signals
          │          ├ opportunity logic
          │          ├ messaging
          │          ├ campaigns
          │          └ landing pages
          │
          ├──────── Product B Pack
          │
          └──────── Product C Pack
```

A new opportunity should ideally be pluggable by defining something like a Product Pack, rather than cloning the Succession system.

That was in your original brief, and I should have made it the primary architectural boundary rather than a secondary consideration.

## Turn 11 — User

Message ID: `4d24f9d6-69c1-426b-a224-5c3728d36c21`

> Follow the prompt….

## Turn 12 — Assistant

Message ID: `49bdea22-0155-462f-a728-7115e218a300`

The visible response began a second, generalized research synthesis titled
“980labs Commercial Opportunity Engine — Research + Product Brief + PRD +
Architecture + Red-Team.” In the live conversation, the rendered message ends
mid-response after introducing `Commercial Observation → Evidence → Product`.
That partial response is not reproduced here because Turn 13 immediately redirects
and sharpens the concept; the source conversation and message ID retain the exact
rendered partial text.

## Turn 13 — User

Message ID: `494bfe06-39e2-4c7d-96c7-d9ebcfc78c2c`

> Having said that, I do like your reframe from Leads to Opportunities, so I’m not trying to stifle that approach. Same concept applies to any product

## Turn 14 — Assistant

Message ID: `78083b5f-4405-41fa-a6cd-468e1cb9b9d4`

Yes — and I think that actually sharpens the product definition.

The generalized 980labs system should not be a “lead-generation platform.” It should be an Opportunity Engine.

The abstraction becomes:

For any product we want to sell, identify organizations where there is credible evidence of both fit and a reason to care now; determine the appropriate people; formulate an evidence-backed opportunity hypothesis; and then decide whether and how to engage.

Succession is simply the first product used to prove that engine.

So I’ll preserve the Leads → Opportunities reframe throughout the research and PRD, but make it product-agnostic. The core reusable chain becomes:

```text
Product
   ↓
ICP / Market Definition
   ↓
Account Discovery
   ↓
Canonical Identity
   ↓
Fit Qualification
   ↓
Evidence Collection
   ↓
Signal Detection
   ↓
Product × Account Interpretation
   ↓
Opportunity Hypothesis
   ↓
Opportunity Qualification / Scoring
   ↓
Stakeholder Resolution
   ↓
Research / Verification
   ↓
Offer + Campaign Selection
   ↓
Human Approval / Policy
   ↓
Engagement
   ↓
Response / Intent
   ↓
Twenty Opportunity
   ↓
Commercial Outcome
   ↓
Learning
```

And there's an important conceptual distinction I'll carry into the specification:

**A lead is an entity. An opportunity is a hypothesis.**

A company or person can exist in the 980labs commercial intelligence graph without being an opportunity for anything. An opportunity only exists when the engine can say something like:

Product X may solve Problem Y for Account Z now, because evidence A/B/C supports that hypothesis, stakeholder Q is plausibly responsible, and our confidence is N.

The same company could simultaneously have:

- a strong opportunity for Succession,
- no opportunity for Product B,
- a developing opportunity for Product C,
- and an expired opportunity for Product D.

That means evidence and company intelligence should be globally reusable, while signals, interpretations, hypotheses, scores, offers, and campaigns can be product-specific.

It also changes the north-star metric. The generalized 980labs engine shouldn't optimize for leads generated. It should optimize for something closer to:

Validated commercial opportunities discovered per unit of research/outreach cost.

Then each product—including Succession—can have its own downstream definition of a validated opportunity.

That is the framing I'll use for the research, architecture, PRD, build/buy/borrow analysis, and red-team rather than reverting to a conventional AI-SDR architecture.

## Turn 15 — User

Message ID: `a9fe0f1b-de3a-41ba-8836-d034c298c0f2`

> Proceed

## Turn 16 — Assistant

Message ID: `39198e6d-8b3e-447c-9fcf-7898ae45f033`

The live ChatGPT DOM exposes this as an empty assistant turn. No text is inserted or
reconstructed here.

## Turn 17 — User

Message ID: `9c9f445a-b762-481b-900a-f73fb89c4446`

> This makes sense. What’s the next step

## Turn 18 — Assistant

Message ID: `7d6c3c3a-377a-47ba-943d-7e8d298f0717`

The next step is to turn the concept into a testable product specification for the 980labs Opportunity Engine before building infrastructure.

I would do that in this order:

Define the canonical domain model. Lock down the meaning and lifecycle of Product, Account, Person, Evidence, Observation, Signal, OpportunityHypothesis, Opportunity, Offer, Campaign, Interaction, and Outcome. This is the foundation everything else depends on.

Design the Product Pack contract. We need to prove that Succession is genuinely just configuration. A new product should be pluggable by supplying ICPs, signals, stakeholders, offers, qualification/scoring policies, research rules, campaigns, artifacts and landing pages—not by writing a new prospecting application.

Specify the Opportunity lifecycle and state machine. For example:
candidate → fit-qualified → signal-qualified → hypothesis → researched → validated → approved → engaged → opportunity → won/lost/nurture.
We should explicitly define what evidence is required to cross every boundary.

Design the shared intelligence/evidence layer. This is where we decide what 980labs learns once about a company and can reuse across every product versus what is interpreted specifically for Product X. This is probably the most strategically important part of the architecture.

Set the Twenty boundary. Define exactly what lives canonically in the Opportunity Engine and what gets projected into Twenty. We should also determine where Twenty workflows are preferable to n8n rather than reflexively making n8n responsible for all orchestration.

Define the evaluation harness before providers. Build a labeled corpus of accounts/opportunities and use it to measure account discovery, signal precision, research correctness, opportunity precision, contact resolution and cost. Then Apollo vs other sources, Firecrawl vs Crawl4AI, etc. can be evaluated empirically instead of philosophically.

Only then produce the implementation architecture. Actual Postgres schemas, APIs/events, n8n workflows, Twenty objects/fields, 980labs task types, model boundaries, provider adapters and build/buy/borrow decisions.

The most useful immediate deliverable is therefore a 980labs Opportunity Engine v1 PRD, not code.

Its most important section should be the Product Pack interface, because that's the architectural test of everything we've just agreed on. If I can define Succession through that interface and then define a completely unrelated hypothetical product through the same interface without changing the core engine, we've probably chosen the right abstractions.

I’d use Succession as the first concrete fixture throughout the PRD, plus one deliberately unrelated second product as an architectural stress test. That will expose Succession-specific assumptions hiding in supposedly generic components very quickly.

So that's what I recommend we do next: canonical domain model → Product Pack contract → Opportunity state machine → data ownership/Twenty boundary → evaluation harness → detailed PRD/build plan.

## Interpretation boundary

The transcript records how the concept emerged. Current requirements, ownership
boundaries, and implementation status live in the other documents in this directory.
If this transcript conflicts with a later decision record or implemented contract, the
later ratified artifact governs.
