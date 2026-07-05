# First Real Ingest Checklist

Use this when James has Granola access or a batch of exported transcripts.

## 1. Confirm Inputs

- James provides 5-10 representative Succession conversations.
- Each transcript has a clear meeting date, title, owner, and attendees.
- Redact anything not needed for extraction-quality review.
- If using the API path, set `GRANOLA_API_KEY` in `.env`.
- If using exports, place `.md`/`.txt` files in `TRANSCRIPTS_INBOX_DIR`.

## 2. Preflight

```bash
python -m relationship_intel.cli doctor --json
```

Expected before live acceptance:

- `llm` is `ok` for real extraction, or intentionally `warn` when testing the
  deterministic mock.
- `twenty` is `ok` before live CRM sync.
- `granola` is `ok` for API ingest, or `warn` when using folder export.
- `transcripts_inbox` points at the real vault inbox when using folder ingest.

## 3. Clear Sample State

The pipeline has no delete path by design.

```bash
scripts/reset-local-output.sh --yes
```

Then manually remove sample records from Twenty:

- Bob Smith
- Sarah Chen
- Tom Rivera
- Smith HVAC
- BrightPixel
- Smith HVAC - Succession opportunity

## 4. Dry-Run Extraction Quality

For redacted fixtures with `expected.profiles` frontmatter:

```bash
python -m relationship_intel.cli eval --source redacted-evals --json
```

Review misses before syncing live CRM data. Minimum acceptance for the first
batch:

- Lead type is correct for prospect vs. referral vs. not-fit.
- Timing window is not overstated.
- Next action is useful and non-sending.
- Every classification has evidence from the transcript.

## 5. Real Ingest

Folder/export path:

```bash
python -m relationship_intel.cli ingest --json
```

Granola API path:

```bash
python -m relationship_intel.cli ingest --source-type granola --created-after YYYY-MM-DD --json
```

## 6. Review Before CRM Sync

- Spot-check generated transcript notes and entity cards.
- Confirm `review_status: unreviewed` is present.
- Confirm no raw transcript body is written if `STORE_RAW_TRANSCRIPTS=false`.
- Run:

```bash
python -m relationship_intel.cli query pipeline --json
python -m relationship_intel.cli query who-to-call --owner James --json
```

## 7. Sync and Plan

```bash
python -m relationship_intel.cli sync-crm --crm twenty --json
python -m relationship_intel.cli weekly-plan --owner James --json
python -m relationship_intel.cli report --json
```

After sync:

- Twenty people/companies/opportunities are additive and deduped.
- Opportunity custom fields are populated.
- Notes/tasks link to the right targets.
- The Contract-1 report validates for `crm-source`.
