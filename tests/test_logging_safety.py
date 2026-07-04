"""Logging safety (KTD-8b, R9): a full pipeline run never emits transcript body
content into log output — log lines reference transcript hashes only."""

from __future__ import annotations

import logging
from datetime import date

from relationship_intel import pipeline

# Distinctive substrings from each sample transcript body.
TRANSCRIPT_MARKERS = [
    "thinking a lot about the next chapter",
    "Twenty-two years running this company",
    "happy to introduce you to two clients",
    "rebuild the Stable Mischief site",
    "retainer starts at two thousand",
    "bob@smithhvac.com",
]


def test_full_pipeline_run_leaks_no_transcript_content_into_logs(settings, samples_dir, caplog):
    with caplog.at_level(logging.DEBUG):
        pipeline.run_ingest(settings, samples_dir)
        pipeline.run_sync(settings, "mock")
        pipeline.run_weekly_plan(settings, run_date=date(2026, 7, 4))

    assert caplog.records  # the pipeline does log — just never transcript content
    for record in caplog.records:
        message = record.getMessage()
        for marker in TRANSCRIPT_MARKERS:
            assert marker not in message, f"transcript content leaked into logs: {marker!r}"
