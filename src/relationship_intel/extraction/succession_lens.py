"""The Succession extraction lens — stored as data, not code, so future lenses
(client development, investor relations, ...) are new lens modules, not new pipelines.
Prompt text is the contract from docs/build-prompt.md §"Succession extraction lens";
the cue tables below are what the deterministic mock honors (and what a real LLM
lens is evaluated against in Phase 1)."""

LENS_NAME = "succession"
LENS_VERSION = "succession-v0.1"

EXTRACTION_PROMPT = (
    "You are analyzing a meeting transcript for Succession pipeline intelligence. "
    "Identify whether any person or company discussed is a potential succession/advisory "
    "prospect, referral source, partner, or not a fit. Extract only facts supported by "
    "the transcript. Use null for unknown fields. Include evidence snippets for all "
    "important inferences. Separate stated facts from inferred signals. Do not overstate "
    "interest. Be conservative with lead warmth. If the transcript is not relevant, mark "
    "it not_fit or unknown."
)

RULES = [
    "Do not hallucinate names, emails, company names, or buying intent.",
    "If unclear, mark unknown.",
    "Every classification must include evidence.",
    "Prefer conservative warmth scoring.",
    "A referral source is not the same as a prospect.",
    "A business owner with no transition signal is not automatically warm.",
    "A warm lead must have some evidence of timing, pain, transition interest, "
    "or stated follow-up.",
]

# --- Cue tables (deterministic; checked as lowercase substrings per attributed sentence).

# Referral cues are checked FIRST; a sentence matching a referral cue is excluded
# from exit/transition scanning so "clients exploring a sale" never warms the referrer.
REFERRAL_CUES = [
    "happy to introduce",
    "happy to bring you as a guest",
    "i can connect you",
    "i will connect you",
    "i'll introduce",
    "i'll make an introduction",
    "send a couple of clients your way",
]

EXIT_CUES = [
    "next chapter",
    "thinking about selling",
    "step back from the business",
    "exit the business",
    "succession plan",
    "hand the business off",
]

TIMING_CUES = {
    "right away": "immediate",
    "in the next few months": "0_3_months",
    "three to six months": "3_6_months",
    "six to twelve months": "6_12_months",
    "next year": "6_12_months",
    "couple of years": "long_term",
    "few years down the road": "long_term",
}

PAIN_CUES = [
    "burned out",
    "no one to take over",
    "can't keep doing this",
    "tired of running",
]

BUYING_CUES = [
    "valuation",
    "what the business is worth",
    "what it would sell for",
]

FOLLOWUP_CUES = [
    "send me",
    "follow up next",
    "let's talk again",
    "set up another call",
]

OWNER_CUES = [
    "owner of",
    "owns",
    "founder of",
    "my business",
    "i started the company",
]

# Conservative-warmth scoring rubric (deterministic; capped at 100).
SCORE_WEIGHTS = {
    "exit": 30,
    "timing": 20,
    "pain": 15,
    "buying": 15,
    "followup": 10,
    "owner": 10,
}
WARM_THRESHOLD = 50
