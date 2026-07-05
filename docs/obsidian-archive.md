# Obsidian Archive

The vault is the evidence layer. Point Obsidian at `output/obsidian-vault`
(or set `OBSIDIAN_VAULT_PATH` to a folder inside an existing vault).

## Layout (`plain` mode — Phase 0 default)

```
<vault>/relationship-intelligence/
  README.md
  transcripts/YYYY-MM-DD-<title-slug>.md
  people/<person-slug>.md
  companies/<company-slug>.md
  opportunities/<opportunity-slug>.md
  weekly-plans/YYYY-Wnn-<owner>-succession-plan.{md,json}
  promotion-proposals/YYYY-Wnn-<owner>-l1-promotion-proposal.{md,json}
  indexes/{people,companies,opportunities,transcript-index}.jsonl
  reports/CRM-YYYY-MM-DD.json          # Contract-1 department report
  .ri-backups/                         # pre-rewrite backups of edited notes
```

`cairns` mode maps the same content onto the 980labsOS L1/L2/L3 convention
without changing the pipeline contract:

```
<vault>/
  raw/relationships/transcripts/*.md
  card-catalog/L2/relationships/{people,companies,opportunities,weekly-plans}/*
  manifests/relationship-intelligence/promotion-proposals/*
  manifests/relationship-intelligence/{indexes,reports}/*
```

The writer intentionally does not write `cairns/L1/succession-pipeline.md`
directly. L1 waypoint updates are canonical-memory promotion candidates and
must be reviewed first; the promotion proposal folder contains the review
packet and proposed content — see `docs/architecture.md` §3.5 and §4.

## Managed sections — how your edits survive

Every generated note wraps its AI content in markers:

```
<!-- ri:begin main -->   ...AI-managed, replaced on re-runs...   <!-- ri:end main -->
```

- Anything you write **outside** the markers survives every re-run.
- If a file you edited must be rewritten, a backup lands in
  `.ri-backups/<note>/<timestamp>.md` first (capped at the 10 most recent per
  note — prune the folder if you want a shorter retention window; backups can
  contain transcript-derived content, so treat them as sensitive).
- If markers get deleted/mangled, the writer treats the whole file as yours:
  it skips the rewrite, logs a warning, and still writes a backup.
- Unchanged input → byte-for-byte identical output (test-enforced).

## Frontmatter contract

Every generated note carries `generated_by: relationship-intel`,
`review_status: unreviewed` (ORD-0003: AI synthesis is unreviewed until a human
promotes it), `llm_provider` (honesty label: `mock` in Phase 0), and
`content_hash` (the managed region's hash — how manual edits are detected).

## Privacy

`STORE_RAW_TRANSCRIPTS=false` omits raw transcript bodies from transcript notes
(hash + metadata + evidence snippets are always kept — they are the audit trail).
