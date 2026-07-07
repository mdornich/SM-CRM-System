# Coolify Deployment

This deployment runs two separate systems:

- **Twenty CRM**: the self-hosted CRM application and its own database/storage.
- **SM-CRM-System**: this Python pipeline and review UI. It stores its own state in
  SQLite and talks to Twenty through `TWENTY_API_URL` + `TWENTY_API_KEY`.

SM-CRM does not need Supabase for the current single-instance deployment.

## Coolify Shape

Create SM-CRM as a Coolify **Application** using the **Dockerfile** build pack.

Recommended settings:

| Setting | Value |
|---|---|
| Base directory | `/` |
| Dockerfile | `Dockerfile` |
| Port exposes | `8765` |
| Start command | leave empty, or `scripts/docker/start-review-ui.sh` |
| Persistent storage | Docker volume or bind mount to `/data/smcrm` |

Coolify storage can be either a Docker volume or a host bind mount. The container
only requires one mounted data directory:

```text
/data/smcrm/
  relationship_intel.db
  transcripts-inbox/
  processed-transcripts/
  failed-transcripts/
  obsidian-vault/
    relationship-intelligence/
  mock_crm/
```

`transcripts-inbox/` is input staging. The SQLite DB and generated
`obsidian-vault/relationship-intelligence/` output are durable state.

## Environment

Set runtime environment variables in Coolify. For secrets, disable "Build
Variable" and keep only "Runtime Variable" enabled.

```env
SMCRM_DATA_DIR=/data/smcrm

LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=

CRM_PROVIDER=twenty
CRM_REVIEW_REQUIRED=true
TWENTY_API_URL=https://twenty.example.com
TWENTY_API_KEY=

OBSIDIAN_VAULT_PATH=/data/smcrm/obsidian-vault
OBSIDIAN_MODE=plain
STORE_RAW_TRANSCRIPTS=false

TRANSCRIPTS_INBOX_DIR=/data/smcrm/transcripts-inbox
RI_DB_PATH=/data/smcrm/relationship_intel.db
RI_MOCK_CRM_PATH=/data/smcrm/mock_crm

DEFAULT_OWNER=James
STALL_THRESHOLD_DAYS=21

# Optional: set false if another sync process should manage inbox cleanup.
SMCRM_ARCHIVE_PROCESSED_TRANSCRIPTS=true
SMCRM_PROCESSED_TRANSCRIPTS_DIR=/data/smcrm/processed-transcripts
```

## Scheduled Job

Create a Coolify scheduled task against the SM-CRM app using standard cron
syntax. A daily 5 AM run:

```text
0 5 * * *
```

Command:

```sh
scripts/docker/daily.sh
```

The job runs:

1. `init`
2. `ingest`
3. `review-queue`
4. `weekly-plan` and `report` on Mondays

After a fully successful ingest, `scripts/docker/daily.sh` archives `.md` and
`.txt` files from `transcripts-inbox/` into a timestamped folder under
`processed-transcripts/`. If ingest fails, the script exits before archiving so
the source files remain retryable.

## Sync Contract

Use Syncthing, Tailscale + rsync, or another file sync outside SM-CRM.

Input sync:

```text
James Mac: JamesVault/smcrm-inbox/
VPS:       /data/smcrm/transcripts-inbox/
```

Output sync:

```text
VPS:       /data/smcrm/obsidian-vault/relationship-intelligence/
James Mac: JamesVault/relationship-intelligence/
```

Only selected transcript files should enter `smcrm-inbox/`. SM-CRM processes any
`.md` or `.txt` file in the inbox regardless of recording source.

## Access Control

The review UI has no built-in authentication. Do not expose it publicly without
an outer access layer such as Cloudflare Access, Coolify/Traefik basic auth, or
Tailscale/VPN-only routing.

## Verify

From a Coolify terminal or container shell:

```sh
python -m relationship_intel.cli doctor --json
python -m relationship_intel.cli init --json
python -m relationship_intel.cli review-queue --json
```

From outside:

```sh
curl -I https://smcrm.example.com/
```
