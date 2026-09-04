# Scoring and calibration

## Separate dimensions

Each hypothesis has a `ScoreDimensions` object. Each quality dimension ranges 0–100, or null
when unknown. The foundation deliberately does not invent evidence/reachability scores from
snippet count or extraction confidence.

| Dimension | Meaning | Typical evidence requirement |
|---|---|---|
| Fit | Match to product ICP, after hard exclusions | Firm characteristics, product-specific exclusion facts |
| Timing/Signal Strength | Why pursuit could matter now | Product-relevant observations, timing and strength |
| Evidence Quality | Reliability, specificity, freshness and corroboration | Source/provenance, dates, independence and verification |
| Stakeholder Relevance | Subject's role in the hypothesized need/decision | Attributed role and decision-process evidence |
| Reachability | Availability of an appropriate permitted contact route | Verified route and applicable policy decision |
| Contradiction Penalty | Material unresolved contrary evidence | Conflicting observations retained with source references |
| Cost-to-Pursue | Estimated marginal research/engagement cost | Explicit monetary unit and costing version |

`cost_to_pursue` is an optional nonnegative cost value, not a 0–100 quality score. Currency and
pricing-basis metadata must be specified before operational use; the current packs leave it null.
Scores are not calibrated probabilities. Source confidence does not mean purchase probability.

## Implemented scoring

Succession's shadow cue path reuses weights: exit 30, timing 20, pain 15, buying 15,
follow-up 10, owner 10. Each cue category counts once, total capped at 100. Referral statements
are excluded from transition scanning; any referral cue keeps the result a referral source.
Warm requires at least 50 and timing/pain/exit/follow-up support. This minimalist cue path is a
shadow probe, not a claim of full legacy extractor parity.

The legacy compatibility mapping preserves the exact existing score under `timing_signal`,
with `scoring_version=succession-v0.1`; other dimensions remain null. A legacy prospect can
create an unreviewed shadow hypothesis, but its old lead type is not proof of generic validation.

Workflow fixture: hard fit is 20–250 employees and `professional_services`. Missing or malformed
required facts return insufficient evidence. Conflicting values return a contradiction hold.
At least five manual hours/week is required; fixture timing strength is `min(100, hours * 5)`.
Fit is 100 for matching firms and 0 for explicit exclusions. These numbers are artificial
architecture-test values, not commercial weights. No production ranking uses them.

C3 ingestion maps high/medium/low to 0.9/0.6/0.3 and stores unknown as 0.0
with `value.confidence_label="unknown"` as the truth (ratified #1277 brief §2);
this schema-preserving floor is not measured zero confidence or qualification.

Cold pack `succession:cold-v0` uses the committed `source/qualification.md` rubric:
all four complete reviewer proofs yield `fit` / fit 100; any proved exclusion yields
`unfit` / fit 0 (even with contradictory denial); everything else is `unknown` / fit null.
All other dimensions stay null under `succession-cold-v0`. `human_label` observations
carry `{criterion: <signal key>, proved: true|false|null}`; true asserts the whole
rubric criterion and its proof law. Directory presence and website/LinkedIn presence
corroborate, but never substitute for, reviewer proof. Statements alone infer nothing.
One evidence reference cannot establish FIT; distinct references are only a necessary
check, not verification of source independence. Reviewers own URLs, publication/read
dates, source independence and complete compound proof (including repeated Process
Component references and name + firm + geography). A `human_label` the pack cannot read
(unknown criterion key, non-boolean `proved`, non-object value) or a presence fact that is
not a boolean is never discarded: it holds the verdict at `unknown`, so a mistyped
exclusion can never leave a subject scored `fit`. Observation confidence is preserved
through hypothesis observation IDs and never converted to a score. This pack performs
no acquisition or live source verification. Acquirer qualification/routing is deferred;
a referral is UNFIT only when an EOS exclusion is proved, otherwise UNKNOWN.

## Proposed deterministic composite

Do not enable a composite until required dimensions and labels are agreed. A future scoring
version may compute a weighted average of explicitly required dimensions, subtract a bounded
contradiction penalty, and clamp to 0–100. Store the dimension inputs, weights, missingness,
penalty and version with the result. Never silently renormalize around missing dimensions:
missing required evidence should hold the assessment, not improve its apparent score.

Hard gates are evaluated before ranking: excluded fit, missing mandatory evidence, stale or
unresolved evidence, suppression, unauthorized geography, and missing approval cannot be
compensated for by a high numerical score. State transitions must check the gates explicitly.
The foundation implements only the pack fixture/creation gates; suppression and outbound gates
are requirements for later execution capabilities, which do not exist here.

## Calibration plan

1. Define product-specific labels: fit accepted/rejected/unknown; signal present/absent;
   source supported/unsupported; stakeholder relevant/irrelevant/unknown; reviewer validates,
   rejects or requests research; eventual commercial outcome and reason.
2. Label representative redacted examples including true negatives, referrals, conflicting
   sources, stale evidence, missing contact routes and two-product overlap. Record labeler,
   policy version, date and reasons. Resolve disagreements explicitly.
3. Separate development and holdout by account/time so one company's repeated transcripts do
   not leak into both. Synthetic development fixtures cannot count as holdout evidence.
4. Report per-product/per-version precision/recall, false positive volume, evidence attribution
   errors, calibration by score band, reviewer acceptance and missing-label coverage. Use
   uncertainty intervals when sample size permits; do not declare precision from a handful of cases.
5. Tune deterministic weights/thresholds against the chosen review capacity and false-positive
   cost. Publish a new scoring version; retain prior results for reproducibility.
6. Compare prospectively on an untouched cohort before changing any autonomy or promotion rule.
   Outcomes can lag; record censoring and selection bias from only pursuing high-scored accounts.

Minimum production quality thresholds and the validation label owner are unresolved. Do not
invent a target percentage or claim the six development fixtures answer those questions.

## Learning and cost attribution

The existing `plan_feedback` is useful operational feedback but it is linked to weekly-plan
items, not generic hypothesis outcomes. Preserve it and introduce an explicit mapping before
reusing it as ground truth. "acted_on" is not a won deal or validated hypothesis.

Future costs should distinguish planned budget, estimated spend and actual charged spend, track
retries and provider waterfalls, and allocate shared research once across products using a
published rule. Until that ledger exists, the north-star ratio is unmeasured. Never report
zero spend merely because the foundation uses synthetic offline fixtures.
