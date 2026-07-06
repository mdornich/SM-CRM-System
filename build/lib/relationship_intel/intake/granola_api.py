"""Granola API source implementing the TranscriptSource protocol.

API shape verified against https://docs.granola.ai on 2026-07-04:
- GET /v1/notes with cursor pagination
- GET /v1/notes/{note_id}?include=transcript for note details
- Bearer auth with Granola API keys
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from relationship_intel.errors import NotConfiguredError
from relationship_intel.intake.local_folder import RawTranscript
from relationship_intel.util.hashing import content_hash


class GranolaAPISource:
    BASE_URL = "https://public-api.granola.ai/v1"

    def __init__(
        self,
        api_key: str = "",
        *,
        base_url: str = BASE_URL,
        created_after: str | None = None,
        created_before: str | None = None,
        updated_after: str | None = None,
        folder_id: str | None = None,
        page_size: int = 30,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key
        self.created_after = created_after
        self.created_before = created_before
        self.updated_after = updated_after
        self.folder_id = folder_id
        self.page_size = page_size
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
            transport=transport,
        )

    def iter_transcripts(self) -> list[RawTranscript]:
        if not self.api_key:
            raise NotConfiguredError(
                "GRANOLA_API_KEY is not set. Create a Granola API key in "
                "Settings -> Connectors -> API keys, or use local folder ingestion."
            )

        transcripts: list[RawTranscript] = []
        cursor: str | None = None
        while True:
            payload = self._request("GET", "/notes", params=self._list_params(cursor))
            for note in payload.get("notes", []):
                note_id = note["id"]
                detail = self._request("GET", f"/notes/{note_id}", params={"include": "transcript"})
                raw = _note_to_transcript(detail)
                if raw is not None:
                    transcripts.append(raw)
            cursor = payload.get("cursor")
            if not payload.get("hasMore") or not cursor:
                return transcripts

    def _list_params(self, cursor: str | None) -> dict:
        params = {"page_size": self.page_size}
        if self.created_after:
            params["created_after"] = self.created_after
        if self.created_before:
            params["created_before"] = self.created_before
        if self.updated_after:
            params["updated_after"] = self.updated_after
        if self.folder_id:
            params["folder_id"] = self.folder_id
        if cursor:
            params["cursor"] = cursor
        return params

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _speaker_label(item: dict[str, Any]) -> str:
    speaker = item.get("speaker") or {}
    return (
        speaker.get("name")
        or speaker.get("diarization_label")
        or speaker.get("source")
        or "Speaker"
    )


def _note_to_transcript(note: dict) -> RawTranscript | None:
    transcript = note.get("transcript")
    if not transcript:
        return None
    lines = [
        f"{_speaker_label(item)}: {item.get('text', '').strip()}"
        for item in transcript
        if item.get("text")
    ]
    raw_text = "\n".join(lines).strip()
    if not raw_text:
        return None

    calendar_event = note.get("calendar_event") or {}
    owner = note.get("owner") or {}
    attendees = [
        attendee.get("name") for attendee in note.get("attendees", []) if attendee.get("name")
    ]
    meeting_date = _parse_date(calendar_event.get("scheduled_start_time")) or _parse_date(
        note.get("created_at")
    )
    return RawTranscript(
        source_system="granola-api",
        source_id=note["id"],
        title=note.get("title") or calendar_event.get("event_title") or note["id"],
        raw_text=raw_text,
        transcript_hash=content_hash(raw_text),
        meeting_date=meeting_date,
        owner=owner.get("name"),
        attendees=attendees,
        source_path=None,
    )
