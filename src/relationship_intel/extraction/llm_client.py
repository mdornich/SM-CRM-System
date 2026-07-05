"""LLM client layer.

MockLLMClient is the Phase 0 default: a deterministic, cue-driven extractor that
exercises the full schema so plumbing/storage/planning are fully proven. It proves
nothing about extraction quality on messy real transcripts — that is Phase 1, and
every artifact it produces is labeled llm_provider="mock".

AnthropicClient is implemented but inert without a key; it is never called by tests."""

from __future__ import annotations

import json
import re
from json import JSONDecodeError
from typing import Any

from relationship_intel.errors import NotConfiguredError
from relationship_intel.extraction import succession_lens as lens

_SPEAKER_RE = re.compile(r"^([A-Z][\w.'-]*(?: [A-Z][\w.'-]*)+):\s*(.*)$")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_NAME = r"[A-Z][a-z]+(?: [A-Z][a-z]+)+"
_CO = r"[A-Z][A-Za-z&'-]*(?: [A-Z][A-Za-z&'-]*)*"
_OWNER_OF_RE = re.compile(rf"({_NAME}), (?:the )?(owner|founder) of ({_CO})")
_TITLE_AT_RE = re.compile(rf"({_NAME}), (?:an? )?([a-z][a-z ]+?) at ({_CO})")


class LLMClient:
    def complete(self, system: str, user: str, response_schema: dict) -> dict:
        raise NotImplementedError


class AnthropicClient(LLMClient):
    """Real extraction path (Phase 1). Inert without ANTHROPIC_API_KEY."""

    API_URL = "https://api.anthropic.com/v1/messages"
    MODEL = "claude-sonnet-5"
    DEFAULT_MAX_OUTPUT_TOKENS = 4096
    DEFAULT_MAX_INPUT_CHARS = 120_000
    # Conservative ceiling guard; exact billing is provider-side, but this blocks
    # accidental huge transcript spends before the request leaves the machine.
    DEFAULT_MAX_COST_USD = 1.00
    INPUT_DOLLARS_PER_MILLION_TOKENS = 3.00
    OUTPUT_DOLLARS_PER_MILLION_TOKENS = 15.00

    def __init__(
        self,
        api_key: str = "",
        *,
        transport: Any | None = None,
        max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
        max_cost_usd: float = DEFAULT_MAX_COST_USD,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ):
        self.api_key = api_key
        self.transport = transport
        self.max_input_chars = max_input_chars
        self.max_cost_usd = max_cost_usd
        self.max_output_tokens = max_output_tokens

    def complete(self, system: str, user: str, response_schema: dict) -> dict:
        if not self.api_key:
            raise NotConfiguredError(
                "ANTHROPIC_API_KEY is not set; LLM_PROVIDER=anthropic requires it. "
                "Phase 0 runs with LLM_PROVIDER=mock."
            )
        import httpx  # imported here: this path is intentionally inert in Phase 0

        user = self._truncate_user_payload(user)
        estimated_cost = self._estimate_cost_usd(
            system=system,
            user=user,
            response_schema=response_schema,
        )
        if estimated_cost > self.max_cost_usd:
            raise RuntimeError(
                f"Anthropic request estimate ${estimated_cost:.4f} exceeds "
                f"configured max ${self.max_cost_usd:.4f}"
            )

        client = httpx.Client(transport=self.transport, timeout=120)
        try:
            return self._complete_with_client(client, system, user, response_schema)
        finally:
            client.close()

    def _complete_with_client(
        self,
        client,
        system: str,
        user: str,
        response_schema: dict,
    ) -> dict:
        base_system = (
            f"{system}\n\nRespond with JSON matching this schema:\n{json.dumps(response_schema)}"
        )
        last_text = ""
        for attempt in range(2):
            system_prompt = base_system
            if attempt == 1:
                system_prompt += (
                    "\n\nYour previous response was not valid JSON. Return only valid JSON, "
                    "with no prose or markdown fences."
                )
            response = client.post(
                self.API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.MODEL,
                    "max_tokens": self.max_output_tokens,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user}],
                },
            )
            response.raise_for_status()
            last_text = response.json()["content"][0]["text"]
            try:
                return json.loads(last_text)
            except JSONDecodeError:
                if attempt == 1:
                    raise
        raise JSONDecodeError("Invalid JSON", last_text, 0)

    def _truncate_user_payload(self, user: str) -> str:
        try:
            payload = json.loads(user)
        except JSONDecodeError:
            return user[: self.max_input_chars]
        transcript = payload.get("transcript")
        if not isinstance(transcript, str) or len(transcript) <= self.max_input_chars:
            return user
        keep_head = self.max_input_chars // 2
        keep_tail = self.max_input_chars - keep_head
        payload["transcript"] = (
            transcript[:keep_head]
            + "\n\n[... transcript truncated by relationship-intel before LLM call ...]\n\n"
            + transcript[-keep_tail:]
        )
        metadata = payload.setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata["transcript_truncated"] = True
            metadata["original_transcript_chars"] = len(transcript)
            metadata["sent_transcript_chars"] = len(payload["transcript"])
        return json.dumps(payload)

    def _estimate_cost_usd(self, system: str, user: str, response_schema: dict) -> float:
        input_text = (
            system
            + "\n"
            + user
            + "\n"
            + json.dumps(response_schema, separators=(",", ":"), sort_keys=True)
        )
        input_tokens = max(1, len(input_text) // 4)
        return (
            input_tokens / 1_000_000 * self.INPUT_DOLLARS_PER_MILLION_TOKENS
            + self.max_output_tokens / 1_000_000 * self.OUTPUT_DOLLARS_PER_MILLION_TOKENS
        )


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]


class MockLLMClient(LLMClient):
    """Deterministic rule-based extraction keyed off the succession lens cue tables."""

    def complete(self, system: str, user: str, response_schema: dict) -> dict:
        payload = json.loads(user)
        return self._extract(payload["metadata"], payload["transcript"].strip())

    # -- rule engine ---------------------------------------------------------

    def _extract(self, meta: dict, transcript: str) -> dict:
        owner = (meta.get("owner") or "").strip()
        lines = transcript.split("\n")

        # Speaker-attributed dialogue; narration lines carry identity patterns.
        utterances: dict[str, list[str]] = {}
        for line in lines:
            m = _SPEAKER_RE.match(line.strip())
            if m:
                utterances.setdefault(m.group(1), []).append(m.group(2))

        people_info: dict[str, dict] = {}
        for name in meta.get("attendees") or []:
            people_info.setdefault(str(name), {})
        for name in utterances:
            people_info.setdefault(name, {})

        companies: dict[str, dict] = {}
        for m in _OWNER_OF_RE.finditer(transcript):
            name, role, company = m.group(1), m.group(2), m.group(3)
            info = people_info.setdefault(name, {})
            info["company"] = company
            info["owner_of_company"] = True
            info["title"] = role.capitalize()
            info["identity_evidence"] = m.group(0)
            companies.setdefault(
                company,
                {"ownership_context": f"{name} is the {role}", "evidence": [m.group(0)]},
            )
        for m in _TITLE_AT_RE.finditer(transcript):
            name, title, company = m.group(1), m.group(2), m.group(3)
            info = people_info.setdefault(name, {})
            info.setdefault("company", company)
            info.setdefault("title", title.strip().title())
            info.setdefault("identity_evidence", m.group(0))
            companies.setdefault(company, {"ownership_context": None, "evidence": [m.group(0)]})

        # Emails attach to the speaker of the line containing them.
        for speaker, texts in utterances.items():
            for text in texts:
                email = _EMAIL_RE.search(text)
                if email:
                    people_info.setdefault(speaker, {})["email"] = email.group(0).lower()

        # Per-person signal scan over their own sentences (referral cues first;
        # referral sentences are excluded from exit scanning per the lens rule).
        profiles = []
        for name, info in people_info.items():
            # Token-based owner match: exact full-name match, or a single-token
            # owner ("James") matching the first-name token. Substring matching
            # would silently drop unrelated attendees ("Janet" for owner "Jan").
            if owner and (name == owner or (len(owner.split()) == 1 and name.split()[0] == owner)):
                info["is_owner"] = True
                continue
            sentences = [s for text in utterances.get(name, []) for s in _sentences(text)]
            profiles.append(self._classify(name, info, sentences))

        people = [
            {
                "name": name,
                "email": info.get("email"),
                "title": info.get("title"),
                "relationship_to_owner": "self" if info.get("is_owner") else None,
                "confidence": 0.9 if info.get("email") or info.get("company") else 0.6,
                "evidence": [info["identity_evidence"]] if info.get("identity_evidence") else [],
            }
            for name, info in people_info.items()
        ]

        follow_ups = [
            s
            for texts in utterances.values()
            for s in _sentences(" ".join(texts))
            if _matches(s, lens.FOLLOWUP_CUES)
        ]
        summary = {
            "concise_summary": f"Meeting: {meta.get('title', '')} — "
            f"attendees: {', '.join(sorted(people_info))}.",
            "key_quotes": [q for p in profiles for q in p["evidence_snippets"]][:10],
            "decisions": [],
            "open_questions": [],
            "follow_up_items": follow_ups,
            "who_owes_what": follow_ups,
        }

        actions = []
        for p in profiles:
            if p["lead_type"] in ("warm", "active", "cold"):
                actions.append(
                    {
                        "action": "create_or_update_opportunity",
                        "target": p["person_name"],
                        "detail": p["next_best_action"],
                    }
                )
            if p["next_best_action"]:
                actions.append(
                    {
                        "action": "create_task",
                        "target": p["person_name"],
                        "detail": p["next_best_action"],
                    }
                )

        return {
            "transcript_metadata": {
                "source_system": meta.get("source_system", "local"),
                "source_id": meta.get("source_id", ""),
                "title": meta.get("title", ""),
                "meeting_date": meta.get("meeting_date"),
                "owner": meta.get("owner"),
                "attendees": meta.get("attendees") or [],
                "transcript_hash": meta.get("transcript_hash", ""),
            },
            "people": people,
            "companies": [
                {
                    "name": name,
                    "ownership_context": c["ownership_context"],
                    "confidence": 0.8,
                    "evidence": c["evidence"],
                }
                for name, c in companies.items()
            ],
            "lead_profiles": profiles,
            "conversation_summary": summary,
            "recommended_crm_actions": actions,
            "recommended_obsidian_notes": [f"people/{n}" for n in people_info],
        }

    def _classify(self, name: str, info: dict, sentences: list[str]) -> dict:
        referral_sents = [s for s in sentences if _matches(s, lens.REFERRAL_CUES)]
        scannable = [s for s in sentences if s not in referral_sents]

        exit_sents = [s for s in scannable if _matches(s, lens.EXIT_CUES)]
        pain_sents = [s for s in scannable if _matches(s, lens.PAIN_CUES)]
        buying_sents = [s for s in scannable if _matches(s, lens.BUYING_CUES)]
        followup_sents = [s for s in scannable if _matches(s, lens.FOLLOWUP_CUES)]
        owner_sents = [s for s in scannable if _matches(s, lens.OWNER_CUES)]
        is_owner = bool(owner_sents) or info.get("owner_of_company", False)

        timing, timing_sents = "unknown", []
        for cue, window in lens.TIMING_CUES.items():
            hits = [s for s in scannable if cue in s.lower()]
            if hits:
                timing, timing_sents = window, hits
                break

        score = 0
        for key, present in (
            ("exit", bool(exit_sents)),
            ("timing", timing != "unknown"),
            ("pain", bool(pain_sents)),
            ("buying", bool(buying_sents)),
            ("followup", bool(followup_sents)),
            ("owner", is_owner),
        ):
            if present:
                score += lens.SCORE_WEIGHTS[key]
        score = min(score, 100)

        evidence = (
            referral_sents + exit_sents + timing_sents + pain_sents + buying_sents + followup_sents
        )
        if info.get("identity_evidence"):
            evidence = evidence + [info["identity_evidence"]]

        has_transition_evidence = bool(exit_sents or timing_sents or pain_sents or followup_sents)
        if referral_sents:
            lead_type, stage = "referral_source", "nurture"
        elif score >= lens.WARM_THRESHOLD and has_transition_evidence:
            lead_type, stage = "warm", "discovery"
        elif is_owner:
            # A business owner with no transition signal is not automatically warm.
            lead_type, stage = "unknown", "new"
        elif sentences:
            lead_type, stage = "not_fit", "not_fit"
            evidence = evidence or [sentences[0]]
        else:
            lead_type, stage = "unknown", "new"

        if timing in ("immediate", "0_3_months"):
            urgency = "high"
        elif timing == "3_6_months" or pain_sents:
            urgency = "medium"
        elif lead_type in ("warm", "referral_source"):
            urgency = "low"
        else:
            urgency = "unknown"

        action, due, cadence, message = None, None, None, None
        if lead_type == "warm":
            action = f"Send {name.split()[0]} a short personal check-in"
            due, cadence = "this_week", "weekly"
            message = (
                f"{name.split()[0]}, enjoyed our conversation — the point you raised "
                f"stuck with me. Worth a quick follow-up call this week?"
            )
        elif lead_type == "referral_source":
            action = f"Thank {name.split()[0]} and agree an introduction plan"
            due, cadence = "this_week", "monthly"
            message = (
                f"{name.split()[0]}, thank you for offering to make introductions — "
                f"I'd love to set up a simple way to do that well."
            )

        return {
            "person_name": name,
            "company_name": info.get("company"),
            "lead_type": lead_type,
            "stage": stage,
            "succession_signal_score": score,
            "urgency": urgency,
            "timing_window": timing,
            "business_owner_signal": is_owner if (is_owner or sentences) else None,
            "exit_or_transition_signal": bool(exit_sents) if sentences else None,
            "pain_points": pain_sents,
            "stated_goals": [],
            "objections": [],
            "buying_signals": buying_sents,
            "risks": [],
            "next_best_action": action,
            "next_action_due_window": due,
            "recommended_cadence": cadence,
            "suggested_message": message,
            "confidence": 0.9 if evidence else 0.3,
            "evidence_snippets": evidence,
        }


def _matches(sentence: str, cues: list[str]) -> bool:
    lowered = sentence.lower()
    return any(cue in lowered for cue in cues)


def make_client(provider: str, anthropic_api_key: str = "") -> LLMClient:
    if provider == "anthropic":
        return AnthropicClient(anthropic_api_key)
    return MockLLMClient()
