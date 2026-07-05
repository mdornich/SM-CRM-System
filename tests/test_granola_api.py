"""Granola API source tests use httpx.MockTransport only; no real Granola calls."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from relationship_intel.errors import NotConfiguredError
from relationship_intel.intake.granola_api import GranolaAPISource


def test_granola_api_requires_key_before_request():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"notes": []})

    source = GranolaAPISource("", transport=httpx.MockTransport(handler))
    with pytest.raises(NotConfiguredError, match="GRANOLA_API_KEY"):
        source.iter_transcripts()
    assert calls == 0


def test_granola_api_lists_pages_and_fetches_transcripts():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/notes"):
            if "cursor" not in request.url.params:
                assert request.url.params["created_after"] == "2026-07-01"
                assert request.url.params["folder_id"] == "fol_4y6LduVdwSKC27"
                return httpx.Response(
                    200,
                    json={
                        "notes": [{"id": "not_11111111111111"}],
                        "hasMore": True,
                        "cursor": "next-page",
                    },
                )
            return httpx.Response(
                200,
                json={
                    "notes": [{"id": "not_22222222222222"}],
                    "hasMore": False,
                    "cursor": None,
                },
            )
        note_id = request.url.path.rsplit("/", 1)[-1]
        assert request.url.params["include"] == "transcript"
        return httpx.Response(
            200,
            json={
                "id": note_id,
                "title": "Succession Talk",
                "owner": {"name": "James"},
                "created_at": "2026-07-03T12:00:00Z",
                "calendar_event": {"scheduled_start_time": "2026-07-02T15:30:00Z"},
                "attendees": [{"name": "James"}, {"name": "Bob Smith"}],
                "transcript": [
                    {
                        "speaker": {"diarization_label": "Speaker A"},
                        "text": "Bob owns Smith HVAC.",
                    },
                    {
                        "speaker": {"source": "speaker"},
                        "text": "He is thinking about succession.",
                    },
                ],
            },
        )

    source = GranolaAPISource(
        "grn_test",
        created_after="2026-07-01",
        folder_id="fol_4y6LduVdwSKC27",
        transport=httpx.MockTransport(handler),
    )

    transcripts = source.iter_transcripts()

    assert len(transcripts) == 2
    assert transcripts[0].source_system == "granola-api"
    assert transcripts[0].source_id == "not_11111111111111"
    assert transcripts[0].title == "Succession Talk"
    assert transcripts[0].owner == "James"
    assert transcripts[0].meeting_date == date(2026, 7, 2)
    assert transcripts[0].attendees == ["James", "Bob Smith"]
    assert "Speaker A: Bob owns Smith HVAC." in transcripts[0].raw_text
    assert "speaker: He is thinking about succession." in transcripts[0].raw_text
    assert [request.url.path for request in calls] == [
        "/v1/notes",
        "/v1/notes/not_11111111111111",
        "/v1/notes",
        "/v1/notes/not_22222222222222",
    ]


def test_granola_api_skips_notes_without_transcript_text():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/notes":
            return httpx.Response(
                200,
                json={
                    "notes": [{"id": "not_11111111111111"}],
                    "hasMore": False,
                    "cursor": None,
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "not_11111111111111",
                "title": "No transcript",
                "transcript": [],
            },
        )

    source = GranolaAPISource("grn_test", transport=httpx.MockTransport(handler))
    assert source.iter_transcripts() == []
