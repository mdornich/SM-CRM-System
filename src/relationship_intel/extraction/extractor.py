"""Extraction orchestration: RawTranscript -> validated ExtractedRelationshipIntelligence.
Provenance (llm_provider, lens_version) is stamped here so every downstream artifact
can label itself honestly. Logging references transcript_hash only (R9)."""

from __future__ import annotations

import json
import logging

from relationship_intel.config import Settings
from relationship_intel.extraction import succession_lens as lens
from relationship_intel.extraction.llm_client import make_client
from relationship_intel.extraction.schemas import ExtractedRelationshipIntelligence
from relationship_intel.intake.local_folder import RawTranscript

logger = logging.getLogger(__name__)


class Extractor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = make_client(
            settings.llm_provider,
            settings.anthropic_api_key,
            settings.codex_model,
            settings.anthropic_model,
        )

    def extract(self, raw: RawTranscript) -> ExtractedRelationshipIntelligence:
        meta = {
            "source_system": raw.source_system,
            "source_id": raw.source_id,
            "title": raw.title,
            "meeting_date": raw.meeting_date.isoformat() if raw.meeting_date else None,
            "owner": raw.owner or self.settings.default_owner,
            "attendees": raw.attendees,
            "transcript_hash": raw.transcript_hash,
        }
        # JSON payload, not tag delimiters — a transcript quoting literal
        # </transcript> text must never truncate what the client sees.
        user = json.dumps({"metadata": meta, "transcript": raw.raw_text})
        result = self.client.complete(
            system=lens.EXTRACTION_PROMPT + "\n" + "\n".join(f"- {r}" for r in lens.RULES),
            user=user,
            response_schema=ExtractedRelationshipIntelligence.model_json_schema(),
        )
        eri = ExtractedRelationshipIntelligence.model_validate(result)
        eri.llm_provider = self.settings.llm_provider
        eri.lens_version = lens.LENS_VERSION
        logger.info(
            "Extracted transcript hash=%s: %d people, %d profiles",
            raw.transcript_hash[:12],
            len(eri.people),
            len(eri.lead_profiles),
        )
        return eri
