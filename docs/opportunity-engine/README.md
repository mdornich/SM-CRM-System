# 980labs Opportunity Engine

Status: additive foundation and proposed target architecture, 2026-09-04.
Reconciled against SM-CRM-System commit `98f16f12c02d5c3fa9001bd775b662d0d5e5824c`.

**A lead is an entity. An opportunity is an evidence-backed commercial hypothesis.**

This package lives in SM-CRM-System. It extends the working relationship-intelligence
pipeline into a product-agnostic Opportunity Engine, with Succession as Product Pack #1.
The Workflow Automation Audit pack is an architecture fixture, not a product commitment.

The existing [governing architecture](../architecture.md) and [source contract](../build-prompt.md)
remain unchanged. This directory documents the additive boundary and explicitly distinguishes
implemented foundation behavior from future product capabilities. It is reconstructed from the
user's authoritative handoff and inspected repository; it does not claim to reproduce the
unavailable downloadable v0.2/v0.3 documents verbatim.

## Reading order

| Document | Purpose |
|---|---|
| [Product Brief](PRODUCT_BRIEF.md) | Problem, users, product thesis, success metric |
| [PRD](PRD.md) | Requirements and verifiable acceptance criteria |
| [Architecture and migration](ARCHITECTURE_MIGRATION.md) | Current code reconciliation, ownership, rollout |
| [Product Pack contract](PRODUCT_PACK_CONTRACT.md) | Executable interface and future manifest boundary |
| [Generic Schema v2](SCHEMA_V2.md) | Actual tables, relationships, IDs and future domain |
| [Event/API contracts](EVENT_API_CONTRACTS.md) | Current Python API and proposed asynchronous envelope |
| [Scoring and calibration](SCORING_CALIBRATION.md) | Separate dimensions, gates, labels and calibration |
| [Provider matrix](PROVIDER_MATRIX.md) | Build/buy/borrow boundaries and future selection gates |
| [Test/evaluation plan](TEST_EVALUATION_PLAN.md) | Baseline, regressions, structural acceptance, quality gaps |
| [Decision log](DECISION_LOG.md) | ADRs with consequences and revisit criteria |
| [Open questions](OPEN_QUESTIONS.md) | Decisions needed before the next milestone |
| [Implementation backlog](IMPLEMENTATION_BACKLOG.md) | Delivered foundation and sequenced remaining slices |

## What runs now

The default CLI, extraction, Twenty sync, review queue, vault output, weekly planning and
Contract-1 report keep using the existing pipeline. Opening SQLite adds empty `oe_*` tables.
Nothing automatically backfills existing transcripts or exports generic hypotheses to Twenty.

New Python modules under `src/relationship_intel/opportunity_engine/` provide validated models,
a separate repository using the same connection factory, two pure packs, a registry, a
hypothesis-creation service, an explicit legacy projection and generic evaluation.

Run the generic development gold set after installing the existing development dependencies:

```bash
python -m relationship_intel.opportunity_engine.evaluation --source examples/opportunity-engine
```

Run the existing checks:

```bash
ruff check . && ruff format --check . && pytest
```

These synthetic cases prove architectural separation and deterministic fixture decisions.
They do not establish commercial accuracy, calibrated probabilities, live CRM correctness,
or permission to automate outreach. See [validation details](TEST_EVALUATION_PLAN.md).
