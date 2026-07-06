from __future__ import annotations

from pathlib import Path

import pytest

from relationship_intel.config import Settings

SAMPLES = Path(__file__).parent.parent / "examples" / "transcripts"


@pytest.fixture
def settings(tmp_path) -> Settings:
    # Default the review gate off in tests so pipeline-mechanics tests can drive
    # sync-crm without pre-approving every record. Tests that exercise the gate
    # itself flip it back to True (see test_review_required_sync_only_pushes_approved_items).
    return Settings(
        llm_provider="mock",
        obsidian_vault_path=tmp_path / "vault",
        db_path=tmp_path / "ri.db",
        mock_crm_path=tmp_path / "mock_crm",
        store_raw_transcripts=True,
        crm_review_required=False,
    )


@pytest.fixture
def samples_dir() -> Path:
    return SAMPLES


def tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }
