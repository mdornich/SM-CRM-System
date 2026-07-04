"""Full-pipeline idempotency: a second run on unchanged input changes nothing —
vault tree byte-for-byte, canonical store counts, and mock CRM contents."""

from __future__ import annotations

from datetime import date

from conftest import tree_snapshot

from relationship_intel import pipeline

RUN_DATE = date(2026, 7, 4)


def _full_run(settings, samples_dir):
    pipeline.run_ingest(settings, samples_dir)
    pipeline.run_sync(settings, "mock")
    pipeline.run_weekly_plan(settings, run_date=RUN_DATE)


def test_double_run_is_a_no_op(settings, samples_dir):
    _full_run(settings, samples_dir)
    vault_before = tree_snapshot(settings.obsidian_vault_path)
    crm_before = tree_snapshot(settings.mock_crm_path)
    counts_before = pipeline.open_repo(settings).counts()

    _full_run(settings, samples_dir)

    assert tree_snapshot(settings.obsidian_vault_path) == vault_before
    assert tree_snapshot(settings.mock_crm_path) == crm_before
    assert pipeline.open_repo(settings).counts() == counts_before
    # No backups on a clean re-run — nothing was manually edited.
    assert not list(
        (settings.obsidian_vault_path / "relationship-intelligence" / ".ri-backups").rglob("*")
    )
