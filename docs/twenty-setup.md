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
| `wedge` | `wedge` | MULTI_SELECT | `EOS_PRACTITIONER` `ACQUIRER` `EXIT_PLANNER` `XPX` `OTHER` |
| `wedge_primary` | `wedgePrimary` | SELECT | same five values |
| `source` | `source` | TEXT | free text (`warm-james`, `cold-eos-list`, ...) |
| `lifecycle_stage` | `lifecycleStage` | SELECT | `COLD` `CONTACTED` `ENGAGED` `MEETING` `OPPORTUNITY` `CUSTOMER` `LOST` `NURTURE` |

- Inputs are normalised: the option value, the human label, or a spaced/snake
  variant all fold onto the canonical value (`"EOS Practitioner"` →
  `EOS_PRACTITIONER`).
- An unrecognised select / multi-select value raises `ValueError` **before any
  HTTP request** — never a silent drop and never a partial write.
- Keys absent from the person dict are absent from the request body, so
  `find_or_create_contact` on an existing record and `update_contact_gtm_fields`
  PATCH only what the caller named; manual edits in Twenty survive a re-sync.
- **Only an email match is written on.** The `and(firstName, lastName)` fallback
  is a dedup heuristic, not an identity — two "John Smith" rows are ordinary — so
  a name-path match reuses the ref but skips the GTM write and logs why.
- **Lifecycle writes move forward only.** §4's progression
  (`Cold → Contacted → Engaged → Meeting → Opportunity → Customer`, plus
  `Any → Lost` / `Any → Nurture`) is enforced: a regression, a no-op rewrite of
  the current stage, or an auto-revival out of `Lost`/`Nurture` is dropped and
  logged, so a repeated sync can never walk a manual edit backwards. The other
  three fields still write in that same PATCH.
- `find_contact` **omits** a field Twenty has unset rather than reporting
  `None`/`[]`, because a present key means "write this" on the update path.
- **There are no clearing semantics.** A key that is absent *or explicitly
  `None`* is omitted from the request. Clearing a GTM field is a human action in
  the Twenty UI, never a sync side effect (base.py's additive/update-safe
  contract).
- **`wedge` writes merge, they don't replace.** A MULTI_SELECT PATCH replaces the
  whole array, so a plain write would drop a tag a human added. The adapter reads
  the current tags and merges (server order first, then anything new), skipping
  the write when it would add nothing. Consequence: **a sync can never remove a
  wedge tag** — do that in the Twenty UI.
- **The guards fail closed.** `lifecycleStage` and `wedge` both depend on
  Twenty's current value. If that value can't be read (404, permission error,
  envelope change) the adapter **skips those two fields and logs why** rather
  than guessing from empty state — guessing would let an arbitrary stage
  regression through and would PATCH a wedge array that drops every human-added
  tag. `source` and `wedgePrimary` need no server state and still write.
- A GTM write that fails on an already-matched contact is contained per record
  and counted in the sync stats as `gtm_write_failed`; the person still syncs and
  its notes/tasks still land.

### What this does not yet do

Nothing in this repo *produces* these four keys. `pipeline.py` and `sync.py`
build person payloads from name / email / title / company only, so the write
path is reachable only by a caller that adds them. Lighting it up needs an
upstream change in extraction — `extraction.py`'s person schema plus the
`pipeline.py` payload builder — to emit `wedge` / `wedge_primary` / `source` /
`lifecycle_stage`, or a bulk importer that calls
`update_contact_gtm_fields` directly.
- Upstream moves fast; after pulling the fork, re-verify the composite shapes
  before trusting the adapter.
