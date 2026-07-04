# Connecting Real Granola (Phase 3)

Phase 0 ingests from a local folder (`examples/transcripts` or any directory of
`.md`/`.txt` files). That path stays forever — it also covers manual paste and
exports from other tools. Granola becomes a second `TranscriptSource`
(`src/relationship_intel/intake/granola_api.py`, currently a documented stub).

## Transcript file format (local folder)

Optional YAML frontmatter (all fields optional; filename fallback is
`YYYY-MM-DD-source-title.md`):

```markdown
---
title: Bob Smith — Succession Intro
date: 2026-06-30
owner: James
source_system: granola-export
source_id: granola-note-0001
attendees: [James Whitfield, Bob Smith]
---
<dialogue, one speaker per line: "Name: what they said">
```

Dedupe is by content hash — re-dropping the same transcript is a no-op.

## Options for wiring Granola, in likely order of preference

1. **Granola API** (`https://docs.granola.ai`): list notes → fetch note with
   transcript. API access may be plan-gated — verify James's workspace plan.
   Implement `GranolaAPISource.iter_transcripts()` against it; the protocol is
   already in place.
2. **Folder-based export**: Granola/desktop export lands files in a watched
   folder → the existing `LocalFolderSource` picks them up unchanged. Zero new
   code; an n8n/Zapier/cron job moves files.
3. **Zapier/webhook trigger**: on new Granola note → write the transcript into
   the watched folder (same as option 2 downstream).
4. **Granola MCP**, if/when available: an agent (Dex or this pipeline's Phase 4
   fleet incarnation) pulls transcripts on schedule.

Whichever lands, the contract is unchanged: produce `RawTranscript` objects;
everything downstream (extraction → vault → CRM → plan) is source-agnostic.

## Privacy note

Granola transcripts contain sensitive personal/business content. Keep
`STORE_RAW_TRANSCRIPTS=true` only if the vault location is private; evidence
snippets are always retained as the audit trail (spec §7).
