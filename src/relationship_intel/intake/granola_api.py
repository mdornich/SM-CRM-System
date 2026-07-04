"""Granola API source — Phase 3 stub implementing the TranscriptSource protocol.

Connection options (documented in docs/granola-ingestion.md):
  1. Granola API (notes list -> note with transcript) — plan-gated access
  2. Folder-based export watched by LocalFolderSource
  3. Zapier/webhook trigger writing into the local folder
  4. Granola MCP, if/when available

Until one of those is wired, this source raises NotConfiguredError and the
local folder remains the ingestion path."""

from __future__ import annotations

from relationship_intel.errors import NotConfiguredError
from relationship_intel.intake.local_folder import RawTranscript


class GranolaAPISource:
    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def iter_transcripts(self) -> list[RawTranscript]:
        raise NotConfiguredError(
            "Granola API ingestion is not configured (Phase 3). "
            "Use local folder ingestion: see docs/granola-ingestion.md"
        )
