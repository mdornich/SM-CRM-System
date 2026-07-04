# Build Prompt — Relationship Intelligence Pipeline (source contract)

> Provenance: original build prompt written by Mitch, reviewed and amended 2026-07-04.
> Where this prompt and `docs/architecture.md` disagree, **architecture.md governs**
> (it encodes the later decisions: mock-first LLM, port 3002, ORD-0003 compliance,
> Contract-1 union report, review_status model). This file is committed so plan/spec
> citations to its named sections (§"Obsidian note templates", §"Weekly plan rules",
> §"CLI commands", §"Succession extraction lens") resolve inside the repo.

You are acting as a senior product architect, full-stack engineer, AI workflow designer, and pragmatic startup CTO.

We are building a reusable Relationship Intelligence Pipeline for 980Labs.

This needs to be built today as a working proof of concept, not just designed.

Core principle:
- Obsidian is the relationship-intelligence archive and evidence layer.
- Twenty CRM is the operating CRM / pipeline execution layer.
- AI agents such as Dex and Thane are the reasoning, extraction, planning, and drafting layer.

First use case:
Succession pipeline for James Whitfield.

Long-term use case:
A reusable relationship-intelligence system for 980Labs that can later support:
- Succession leads
- client development
- investor relationships
- referral partners
- partnerships
- customer success
- internal relationship memory

Context:
James is generating Succession leads through conversations and meetings. Many meetings are captured in Granola. We want to extract meaningful lead intelligence from those transcripts, store the evidence and summaries in Obsidian, and push operational pipeline records into Twenty CRM. Then Thane/Dex should be able to generate beginning-of-week plans for follow-ups, retouches, nurture actions, and active opportunity movement.

Do not build "just another CRM."
Build the reusable transcript-to-relationship-intelligence layer, with Twenty as the first CRM execution backend.

IMPORTANT WORKSPACE RULE:
Build this in the SM-CRM-System repo. Do not modify existing 980Labs production repos unless explicitly told.

## Architecture

Build these layers:

1. Transcript Intake Layer
2. Obsidian Intelligence Archive Layer
3. Extraction / Lead Intelligence Layer
4. Internal Canonical Store
5. Twenty CRM Adapter Layer
6. Weekly Planning Layer
7. Human Approval / Execution Layer

## Storage responsibilities

### Obsidian responsibilities

Obsidian is the durable intelligence and evidence archive.

Use Obsidian for:
- raw transcript storage
- transcript metadata
- extracted relationship-intelligence notes
- evidence snippets
- meeting summaries
- prospect intelligence cards
- relationship history
- reasoning artifacts
- audit trail of why the AI classified someone a certain way

Suggested Obsidian structure:

    vault/
      relationship-intelligence/
        README.md
        transcripts/
          YYYY-MM-DD-source-title.md
        people/
          person-name.md
        companies/
          company-name.md
        opportunities/
          opportunity-name.md
        weekly-plans/
          YYYY-WW-james-succession-plan.md
        indexes/
          people.jsonl
          companies.jsonl
          opportunities.jsonl
          transcript-index.jsonl

If the user's vault uses a Cairns/L1/L2/L3 structure, support that too (see architecture.md §3.5 for the authoritative mapping).

For the MVP, make the Obsidian output path configurable.

Required Obsidian note behavior:
- Write Markdown files.
- Include YAML frontmatter.
- Include source transcript ID/hash.
- Include evidence snippets.
- Include confidence scores.
- Link people, companies, opportunities, and transcripts using Obsidian wikilinks.
- Never overwrite manually edited notes without making a backup or preserving custom sections.
- Make writes idempotent where possible.

### Twenty CRM responsibilities

Twenty is the operational CRM/pipeline execution layer.

Use Twenty for:
- Contacts / People
- Companies
- Opportunities / Deals
- Pipeline stages
- Tasks
- Follow-up due dates
- Owner assignment
- Notes / activities
- Tags
- CRM links for weekly plans

Twenty should not be the only place evidence lives.
Twenty should receive concise operational summaries and links back to Obsidian evidence notes.

Twenty is the field and scoreboard.
Obsidian is the film room and evidence locker.
Dex/Thane is the coach.

## Tools to use / install / investigate

Primary CRM:
- Twenty CRM (fork at ~/Documents/GitHub/twenty, running locally on port 3002)
  - GitHub: https://github.com/twentyhq/twenty
  - Docs: https://docs.twenty.com

Transcript source:
- Granola (https://docs.granola.ai/introduction)
  - For MVP, support local transcript folder ingestion first.
  - Design Granola API ingestion as a pluggable source.

Optional/future CRM adapters: EspoCRM, HubSpot, Attio, Affinity.
Automation/future: n8n or Zapier may later be used for folder/webhook triggers; not required for the MVP.

## MVP goal for today

Build a local working proof of concept that can:

1. Ingest transcript files from a local folder.
2. Analyze transcripts with a Succession lead-intelligence lens.
3. Extract structured prospect/company/opportunity/follow-up data.
4. Write intelligence notes into an Obsidian-compatible folder.
5. Store canonical records locally in SQLite or JSONL.
6. Create or simulate CRM records through a Twenty adapter.
7. Generate a beginning-of-week follow-up plan for James as Markdown and JSON.
8. Include sample transcripts and tests.
9. Include docs for connecting real Granola and real Twenty later.
10. Be runnable from the command line.

Important:
If Twenty cannot be fully installed/configured today, do not block the MVP.
Create:
- crm/base.py
- crm/twenty_adapter.py
- crm/mock_adapter.py

The mock adapter must work today.
The Twenty adapter should be as complete as possible based on current docs.

## Preferred tech stack

Use Python for the orchestration pipeline.

Use:
- Python 3.11+
- Pydantic for schemas
- SQLite for internal canonical store
- Markdown files for Obsidian output
- pytest for tests
- httpx for APIs (requests is banned in this repo)
- python-dotenv for env vars
- optional Typer or argparse for CLI

Do not require a web app for the MVP.

## Expected repo structure

See architecture.md §"Output Structure" in the Phase 0 plan for the authoritative layout (repo root is the project root).

## CLI commands

Implement commands like:

    # initialize local store and output folders
    python -m relationship_intel.cli init

    # ingest local transcripts and write Obsidian intelligence notes
    python -m relationship_intel.cli ingest --source examples/transcripts --vault ./output/obsidian-vault

    # sync extracted records to CRM
    python -m relationship_intel.cli sync-crm --crm mock

    # generate weekly plan
    python -m relationship_intel.cli weekly-plan --owner James --week-start 2026-07-06 --vault ./output/obsidian-vault

    # run full local POC
    python -m relationship_intel.cli run-demo

## Environment variables

Use `.env.example` (authoritative trimmed version in architecture.md §6):

    LLM_PROVIDER=mock
    ANTHROPIC_API_KEY=
    GRANOLA_API_KEY=
    OBSIDIAN_VAULT_PATH=./output/obsidian-vault
    OBSIDIAN_MODE=plain
    CRM_PROVIDER=mock
    TWENTY_API_URL=http://localhost:3002
    TWENTY_API_KEY=

## Extraction schema

Use Pydantic models.

For each transcript, extract:

### TranscriptMetadata
- source_system, source_id, title, meeting_date, owner, attendees, transcript_hash

### Person
- name, email, phone, title, role_in_opportunity, relationship_to_owner, confidence, evidence

### Company
- name, website, industry, location, size_estimate, ownership_context, confidence, evidence

### SuccessionLeadProfile
- lead_type: cold | warm | active | referral_source | partner | not_fit | unknown
- stage: new | nurture | discovery | qualified | active_opportunity | stalled | closed_won | closed_lost | not_fit
- succession_signal_score: integer 0-100
- urgency: low | medium | high | unknown
- timing_window: immediate | 0_3_months | 3_6_months | 6_12_months | long_term | unknown
- business_owner_signal: true | false | null
- exit_or_transition_signal: true | false | null
- pain_points: list
- stated_goals: list
- objections: list
- buying_signals: list
- risks: list
- next_best_action
- next_action_due_window
- recommended_cadence
- suggested_message
- confidence
- evidence_snippets

### ConversationSummary
- concise_summary, key_quotes, decisions, open_questions, follow_up_items, who_owes_what

### ExtractedRelationshipIntelligence
- transcript_metadata, people, companies, lead_profiles, conversation_summary, recommended_crm_actions, recommended_obsidian_notes

## Succession extraction lens

Create a reusable extraction prompt:

"You are analyzing a meeting transcript for Succession pipeline intelligence. Identify whether any person or company discussed is a potential succession/advisory prospect, referral source, partner, or not a fit. Extract only facts supported by the transcript. Use null for unknown fields. Include evidence snippets for all important inferences. Separate stated facts from inferred signals. Do not overstate interest. Be conservative with lead warmth. If the transcript is not relevant, mark it not_fit or unknown."

Rules:
- Do not hallucinate names, emails, company names, or buying intent.
- If unclear, mark unknown.
- Every classification must include evidence.
- Prefer conservative warmth scoring.
- A referral source is not the same as a prospect.
- A business owner with no transition signal is not automatically warm.
- A warm lead must have some evidence of timing, pain, transition interest, or stated follow-up.

## Obsidian note templates

### Transcript note

Frontmatter:

    ---
    type: transcript
    source_system: granola
    source_id:
    date:
    owner:
    transcript_hash:
    processed: true
    ---

Body:

    # Transcript: {title}
    ## Metadata
    ## Raw Transcript
    ## Extraction Links
    - People:
    - Companies:
    - Opportunities:

### Person intelligence note

Frontmatter:

    ---
    type: person
    name:
    email:
    company:
    lead_type:
    stage:
    owner:
    confidence:
    last_interaction:
    next_action:
    next_action_due:
    crm_id:
    ---

Body:

    # {Person Name}
    ## Snapshot
    ## Relationship Context
    ## Succession Signals
    ## Evidence
    ## Conversation History
    ## Next Actions
    ## CRM Links

### Company intelligence note

Frontmatter:

    ---
    type: company
    name:
    industry:
    location:
    stage:
    owner:
    crm_id:
    ---

Body:

    # {Company Name}
    ## Snapshot
    ## Ownership / Succession Context
    ## People
    ## Opportunities
    ## Evidence
    ## Conversation History

### Opportunity note

Frontmatter:

    ---
    type: opportunity
    name:
    company:
    primary_contact:
    stage:
    lead_type:
    succession_signal_score:
    urgency:
    timing_window:
    owner:
    next_action:
    next_action_due:
    crm_id:
    ---

Body:

    # {Opportunity Name}
    ## Current Read
    ## Why It Matters
    ## Succession Signals
    ## Risks / Objections
    ## Next Best Action
    ## Evidence
    ## Timeline
    ## CRM Links

### Weekly plan note

Frontmatter:

    ---
    type: weekly_plan
    owner:
    week_start:
    week_end:
    generated_at:
    ---

Body:

    # Weekly Succession Follow-Up Plan — {week_start}
    ## Top Plays This Week
    ## Overdue
    ## Warm Follow-Ups
    ## Cold Retouches
    ## Referral / Partner Nurture
    ## Stalled
    ## Suggested Time Blocks
    ## Risks

## Weekly plan rules

Generate a weekly plan that groups pipeline records into:

- Hot / urgent
- Overdue
- Warm follow-ups
- Cold retouches
- Referral / partner nurture
- Stalled
- Long-term nurture
- Not ready

Each item should include:
- contact, company, current stage, priority, why now, next action, suggested message, due date/window, evidence, CRM link if available, Obsidian link

The weekly plan must be readable and action-oriented, not a data dump.

Example:

    ## Top Plays This Week

    1. Bob Smith — Warm / 3–6 month timing
       - Why now: Bob said he is "trying to figure out the next chapter" and asked about valuation.
       - Next action: James sends a short check-in Tuesday morning.
       - Draft: "Bob, enjoyed the conversation last week…"
       - Evidence: [[Transcript - 2026-07-01 Bob Smith]]
       - If no reply: schedule 14-day retouch.

## Twenty adapter requirements

Build `CRMAdapter` interface with:

    class CRMAdapter:
        def find_or_create_contact(...)
        def find_or_create_company(...)
        def create_or_update_opportunity(...)
        def attach_note(...)
        def create_task(...)
        def tag_record(...)
        def get_pipeline_items(...)

Build `MockCRMAdapter` that works today.

Build `TwentyCRMAdapter` that:
- reads `TWENTY_API_URL`, reads `TWENTY_API_KEY`
- uses official Twenty API if available
- logs requests/responses safely
- handles missing API key gracefully
- never prints secrets
- has idempotency safeguards

If Twenty API integration cannot be completed today:
- Leave clear TODOs.
- Document current Twenty API assumptions.
- Make mock adapter fully functional.

## Granola ingestion requirements

Build `GranolaAPIIngestor` as a pluggable source.

If API access is not available:
- Implement local transcript folder ingestion.
- Document how to connect Granola later: API notes list; get note with transcript; folder-based export; Zapier/webhook trigger; MCP if available.

Do not block the MVP on Granola API access.

## Testing requirements

Create tests for:

1. Transcript with clear warm succession prospect.
2. Transcript with referral source but not direct prospect.
3. Transcript with no relevant lead.
4. Duplicate transcript handling.
5. Same person across multiple transcripts.
6. Same company across multiple transcripts.
7. Obsidian note creation.
8. Obsidian idempotent write behavior.
9. Weekly plan prioritization.
10. Mock CRM adapter idempotency.
11. Unknown fields are null, not hallucinated.
12. Human approval rule: no external sends.

## Security/privacy requirements

- Meeting transcripts may contain sensitive personal/business info.
- Do not log full transcripts unnecessarily.
- Do not send external emails/messages automatically.
- Store raw transcripts only if configured.
- Allow raw transcript storage to be disabled.
- Store source hash and metadata.
- Keep secrets in environment variables.
- No secrets in repo.
- No auto CRM destructive actions.
- CRM writes should be additive/update-safe.

## Acceptance criteria

The project is done for MVP when:

1. `python -m relationship_intel.cli run-demo` works.
2. Sample transcripts are ingested.
3. Obsidian-compatible notes are generated.
4. Mock CRM records are created.
5. Weekly plan Markdown and JSON are generated.
6. Tests pass.
7. README explains exactly how to run.
8. Docs explain how to connect real Granola.
9. Docs explain how to connect real Twenty.
10. The architecture clearly separates:
    - Obsidian evidence archive
    - Twenty operational CRM
    - AI reasoning/planning layer
