# Succession Extraction Lens

Authoritative code: `src/relationship_intel/extraction/succession_lens.py`. The lens
is **data, not code** — a future lens (client development, investor relations,
referral partners) is a new lens module reusing the same pipeline.

## The prompt (used verbatim by the real LLM path in Phase 1)

> You are analyzing a meeting transcript for Succession pipeline intelligence.
> Identify whether any person or company discussed is a potential
> succession/advisory prospect, referral source, partner, or not a fit. Extract
> only facts supported by the transcript. Use null for unknown fields. Include
> evidence snippets for all important inferences. Separate stated facts from
> inferred signals. Do not overstate interest. Be conservative with lead warmth.
> If the transcript is not relevant, mark it not_fit or unknown.

Plus the rules from `docs/build-prompt.md` §"Succession extraction lens"
(no hallucinated names/emails/intent; every classification needs evidence;
a referral source is not a prospect; an owner with no transition signal is not
automatically warm; warm requires timing, pain, transition interest, or stated
follow-up).

## The mock's cue grammar (Phase 0)

`MockLLMClient` is deterministic: it attributes dialogue to speakers
(`Name: ...` lines), scans each person's own sentences against the lens cue
tables (referral cues checked **first** — a referral sentence is excluded from
exit-signal scanning, so "clients exploring a sale" never warms the referrer),
and scores conservatively:

| Signal | Weight |
|---|---|
| exit/transition phrase | 30 |
| timing phrase | 20 |
| pain phrase | 15 |
| buying phrase (valuation, …) | 15 |
| stated follow-up | 10 |
| business-owner signal | 10 |

`warm` requires score ≥ 50 **and** at least one of timing/pain/transition/
follow-up (the lens's conservative-warmth rule). Every artifact is stamped
`llm_provider: mock` — the mock proves plumbing, not extraction quality.

## What Phase 1 changes

Only `LLM_PROVIDER=anthropic` + a key. The `AnthropicClient` sends the same
prompt + JSON schema; validation, evidence rules, storage, and planning are
identical. Exit criterion: extraction quality accepted by Mitch/James on ≥ 5
real (redacted) Granola transcripts.
