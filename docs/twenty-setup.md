# Connecting Real Twenty

**Local install (this machine):** fork `mdornich/twenty` at
`~/Documents/GitHub/twenty`, pinned reference commit `1a60d4ea` (v0.2.1,
2026-07-04). Non-standard ports because other services own the defaults:

| Service | Port |
|---|---|
| Backend (API) | **3002** (`NODE_PORT` in `packages/twenty-server/.env` — not 3000) |
| Frontend | 3001 |
| Postgres 16 (Docker) | 5433 |
| Redis 7 (Docker) | 6380 |

Start: `cd ~/Documents/GitHub/twenty && export PATH="$HOME/.nvm/versions/node/v24.16.0/bin:$PATH" && npx nx start`

## Wiring the adapter

1. In Twenty (http://localhost:3001) → **Settings → Developers → API Keys** →
   create a key (it's a signed JWT, sent verbatim as the Bearer token).
2. In this repo's `.env`:

   ```
   CRM_PROVIDER=twenty
   TWENTY_API_URL=http://localhost:3002
   TWENTY_API_KEY=<the key>
   ```

3. `python -m relationship_intel.cli sync-crm --crm twenty`

## API facts the adapter relies on (verified against the fork source, 2026-07-04)

- REST base path `/rest`; plural object routes: `/rest/people`, `/rest/companies`,
  `/rest/opportunities`, `/rest/tasks`, `/rest/notes`.
- Auth header: `Authorization: Bearer <api-key-jwt>`.
- Composite fields: `name: {firstName, lastName}`, `emails: {primaryEmail}`,
  `domainName: {primaryLinkUrl}` (a Links composite, not a plain string),
  `bodyV2: {markdown}` for note/task bodies.
- Filter DSL: `filter=emails.primaryEmail[eq]:x@y.com`, `and(...)`, dotted
  composite paths; pagination `limit` / `starting_after`.
- Envelopes: list → `{"data": {"people": [...]}}`; create →
  `{"data": {"createPerson": {...}}}` (verb-prefixed key).
- Default opportunity stages: `NEW SCREENING MEETING PROPOSAL CUSTOMER`.

## Stage mapping (spec vocabulary → Twenty)

| Spec stage | Twenty stage |
|---|---|
| new, nurture | NEW |
| discovery | SCREENING |
| qualified | MEETING |
| active_opportunity | PROPOSAL |
| closed_won | CUSTOMER |
| not_fit, stalled, closed_lost | *(no opportunity created — intentional)* |

## Known caveats (Phase 2 work)

- **Task/note linking** uses join tables (`taskTargets` / `noteTargets`) via a
  second POST with **target-prefixed FKs** (`targetPersonId`, `targetCompanyId`,
  `targetOpportunityId`) — verified live against the running fork on 2026-07-04
  (Phase 2 sync: POC dataset visible and correct in the Twenty UI, second sync
  a full no-op).
- A fresh Twenty workspace ships with built-in sample records (Notion/Anthropic/
  Airbnb/etc. people and demo opportunities); delete them in the UI if unwanted —
  the pipeline never touches records it didn't create.
- Tags: Twenty has no native tag object on core records; `tag_record` is a
  logged no-op pending a custom-field decision.
- Custom fields are provisioned additively by `sync-crm --crm twenty` through
  `/rest/metadata`: Opportunity gets `successionSignalScore` (NUMBER),
  `leadType` (SELECT), and `timingWindow` (SELECT); Person gets `wedge`
  (MULTI_SELECT), `wedgePrimary` (SELECT), `source` (TEXT) and `lifecycleStage`
  (SELECT). The API key role must have the DATA_MODEL settings permission, or
  schema provisioning fails before sync.

## Person GTM custom fields (Succession `gtm-crm-architecture.md` §4)

`PERSON_CUSTOM_FIELDS` in `twenty_adapter.py` mirrors the shape Twenty already
carries on the mini (values read live, GET only, 2026-09-03):

| Person dict key | Twenty field | Type | Allowed values |
|---|---|---|---|
| `wedge` | `wedge` | MULTI_SELECT | `EOS_PRACTITIONER` `ACQUIRER` `EXIT_PLANNER` `XPX` `OTHER` `NA` |
| `wedge_primary` | `wedgePrimary` | SELECT | same, minus `NA` |
| `source` | `source` | TEXT | free text (`warm-james`, `cold-eos-list`, ...) |
| `lifecycle_stage` | `lifecycleStage` | SELECT | `COLD` `CONTACTED` `ENGAGED` `MEETING` `OPPORTUNITY` `CUSTOMER` `LOST` `NURTURE` |

- Inputs are normalised: the option value, the human label, or a spaced/snake
  variant all fold onto the canonical value (`"EOS Practitioner"` →
  `EOS_PRACTITIONER`).
- An unrecognised select / multi-select value raises `ValueError` **before any
  HTTP request** — never a silent drop and never a partial write.
- Keys absent from the person dict are absent from the request body, so
  `find_or_create_contact` on an existing record and `update_contact` PATCH only
  what the caller named; manual edits in Twenty survive a re-sync.
- **Lifecycle transitions are not enforced.** §4 lists an ordered progression
  (`Cold → Contacted → Engaged → Meeting → Opportunity → Customer / Lost /
  Nurture`), but the adapter models no Person stage machine — it writes the value
  it is given. `LIFECYCLE_STAGE_ORDER` records the order for callers that want it.
- **Open item:** the live `wedge` field carries a sixth option `NA` that §4 does
  not list. The adapter supports it; whether it is ratified into the spec or
  removed from Twenty is Mitch's call.
- Upstream moves fast; after pulling the fork, re-verify the composite shapes
  before trusting the adapter.
