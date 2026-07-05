"""Environment-driven settings. Env names are the contract from docs/architecture.md §6."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from relationship_intel.errors import NotConfiguredError


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    llm_provider: str = "mock"
    codex_model: str = ""
    anthropic_api_key: str = ""
    obsidian_vault_path: Path = Path("./output/obsidian-vault")
    obsidian_mode: str = "plain"
    store_raw_transcripts: bool = True
    crm_provider: str = "mock"
    crm_review_required: bool = False
    twenty_api_url: str = "http://localhost:3002"
    twenty_api_key: str = ""
    granola_api_key: str = ""
    transcripts_inbox_dir: Path = Path("./examples/transcripts")
    default_owner: str = "James"
    stall_threshold_days: int = 21
    db_path: Path = Path("./output/relationship_intel.db")
    mock_crm_path: Path = Path("./output/mock_crm")


def load_settings(env_file: str | Path | None = None) -> Settings:
    if env_file is not None:
        load_dotenv(env_file, override=True)
    else:
        load_dotenv()
    env = os.environ
    raw_stall = env.get("STALL_THRESHOLD_DAYS") or 21
    try:
        stall_threshold_days = int(raw_stall)
    except ValueError as exc:
        raise NotConfiguredError(
            f"STALL_THRESHOLD_DAYS must be an integer, got {raw_stall!r}"
        ) from exc
    return Settings(
        llm_provider=env.get("LLM_PROVIDER", "mock").strip() or "mock",
        codex_model=env.get("CODEX_MODEL", "").strip(),
        anthropic_api_key=env.get("ANTHROPIC_API_KEY", ""),
        obsidian_vault_path=Path(env.get("OBSIDIAN_VAULT_PATH") or "./output/obsidian-vault"),
        obsidian_mode=env.get("OBSIDIAN_MODE", "plain").strip() or "plain",
        store_raw_transcripts=_bool(env.get("STORE_RAW_TRANSCRIPTS"), True),
        crm_provider=env.get("CRM_PROVIDER", "mock").strip() or "mock",
        crm_review_required=_bool(env.get("CRM_REVIEW_REQUIRED"), False),
        twenty_api_url=env.get("TWENTY_API_URL", "http://localhost:3002").strip()
        or "http://localhost:3002",
        twenty_api_key=env.get("TWENTY_API_KEY", ""),
        granola_api_key=env.get("GRANOLA_API_KEY", ""),
        transcripts_inbox_dir=Path(env.get("TRANSCRIPTS_INBOX_DIR") or "./examples/transcripts"),
        default_owner=env.get("DEFAULT_OWNER", "James").strip() or "James",
        stall_threshold_days=stall_threshold_days,
        db_path=Path(env.get("RI_DB_PATH") or "./output/relationship_intel.db"),
        mock_crm_path=Path(env.get("RI_MOCK_CRM_PATH") or "./output/mock_crm"),
    )
