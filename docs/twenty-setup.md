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
  second POST — this is the least-verified adapter path; the Phase 2 exit
  criterion is the POC dataset visible and correct in the Twenty UI.
- Tags: Twenty has no native tag object on core records; `tag_record` is a
  logged no-op pending a custom-field decision.
- Custom fields for `succession_signal_score` / `lead_type` / `timing_window`:
  decide when provisioning the workspace (architecture.md open question 2).
- Upstream moves fast; after pulling the fork, re-verify the composite shapes
  before trusting the adapter.
