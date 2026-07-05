"""Read-only environment preflight for go-live readiness."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from relationship_intel.config import Settings
from relationship_intel.obsidian.writer import VaultWriter

LAUNCHD_LABEL = "com.stablemischief.relationship-intel.daily"
PLIST_PATH = Path("launchd") / f"{LAUNCHD_LABEL}.plist"
DAILY_SCRIPT = Path("scripts") / "relationship-intel-daily.sh"

Status = str


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    message: str
    detail: str | None = None


def run_doctor(
    settings: Settings,
    *,
    repo_root: Path | None = None,
) -> dict:
    """Return a read-only readiness report."""
    repo_root = repo_root or Path.cwd()
    checks = [
        _check_obsidian(settings),
        _check_transcripts_inbox(settings),
        _check_db(settings),
        _check_llm(settings),
        _check_granola(settings),
        _check_twenty(settings),
        _check_launchd_files(repo_root),
        _check_launchd_installed(),
    ]
    summary = _summary(checks)
    return {
        "status": summary,
        "ok": sum(1 for check in checks if check.status == "ok"),
        "warn": sum(1 for check in checks if check.status == "warn"),
        "blocked": sum(1 for check in checks if check.status == "blocked"),
        "checks": [check.__dict__ for check in checks],
    }


def _summary(checks: list[Check]) -> str:
    if any(check.status == "blocked" for check in checks):
        return "blocked"
    if any(check.status == "warn" for check in checks):
        return "warn"
    return "ok"


def _check_obsidian(settings: Settings) -> Check:
    try:
        writer = VaultWriter(settings.obsidian_vault_path, settings.obsidian_mode)
    except ValueError as exc:
        return Check("obsidian", "blocked", str(exc))
    root = writer.root
    if root.exists():
        return Check("obsidian", "ok", f"vault target exists: {root}")
    return Check(
        "obsidian",
        "warn",
        f"vault target does not exist yet: {root}",
        "run init before first ingest",
    )


def _check_transcripts_inbox(settings: Settings) -> Check:
    path = settings.transcripts_inbox_dir
    if not path.exists():
        return Check(
            "transcripts_inbox",
            "warn",
            f"inbox directory does not exist: {path}",
            "create it or pass --source explicitly",
        )
    files = list(path.glob("*.md")) + list(path.glob("*.txt"))
    return Check(
        "transcripts_inbox",
        "ok",
        f"inbox exists with {len(files)} transcript file(s): {path}",
    )


def _check_db(settings: Settings) -> Check:
    path = settings.db_path
    if not path.exists():
        return Check("db", "warn", f"SQLite store does not exist yet: {path}", "run init")
    try:
        with sqlite3.connect(path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
    except sqlite3.Error as exc:
        return Check("db", "blocked", f"SQLite store is unreadable: {path}", str(exc))
    required = {"transcripts", "people", "companies", "opportunities"}
    missing = sorted(required - tables)
    if missing:
        return Check("db", "blocked", f"SQLite schema missing table(s): {', '.join(missing)}")
    return Check("db", "ok", f"SQLite store readable: {path}")


def _check_llm(settings: Settings) -> Check:
    if settings.llm_provider == "mock":
        return Check("llm", "warn", "LLM_PROVIDER=mock", "real extraction needs anthropic")
    if settings.llm_provider != "anthropic":
        return Check("llm", "blocked", f"unsupported LLM_PROVIDER={settings.llm_provider!r}")
    if not settings.anthropic_api_key:
        return Check("llm", "blocked", "ANTHROPIC_API_KEY is missing")
    return Check("llm", "ok", "Anthropic extraction configured")


def _check_granola(settings: Settings) -> Check:
    if settings.granola_api_key:
        return Check("granola", "ok", "GRANOLA_API_KEY is configured")
    return Check(
        "granola",
        "warn",
        "GRANOLA_API_KEY is missing",
        "local folder ingest still works while waiting for James",
    )


def _check_twenty(settings: Settings) -> Check:
    if settings.crm_provider != "twenty":
        return Check(
            "twenty",
            "warn",
            f"CRM_PROVIDER={settings.crm_provider}",
            "set CRM_PROVIDER=twenty for live sync",
        )
    if not settings.twenty_api_key:
        return Check("twenty", "blocked", "TWENTY_API_KEY is missing")
    try:
        from relationship_intel.crm.twenty_adapter import TwentyCRMAdapter

        TwentyCRMAdapter(settings.twenty_api_url, settings.twenty_api_key)._opportunity_metadata()
    except Exception as exc:  # noqa: BLE001 — readiness report degrades, never raises
        return Check("twenty", "blocked", "Twenty metadata API unreachable", str(exc))
    return Check("twenty", "ok", "Twenty metadata API reachable")


def _check_launchd_files(repo_root: Path) -> Check:
    plist = repo_root / PLIST_PATH
    script = repo_root / DAILY_SCRIPT
    missing = [str(path) for path in (plist, script) if not path.exists()]
    if missing:
        return Check("launchd_files", "blocked", f"missing file(s): {', '.join(missing)}")
    if not (script.stat().st_mode & 0o111):
        return Check("launchd_files", "blocked", f"daily script is not executable: {script}")
    return Check("launchd_files", "ok", "launchd plist and daily script are present")


def _check_launchd_installed() -> Check:
    installed = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
    if installed.exists():
        return Check("launchd_installed", "ok", f"LaunchAgent plist exists: {installed}")
    return Check(
        "launchd_installed",
        "warn",
        f"LaunchAgent plist is not installed: {installed}",
        "install/load the plist before unattended go-live",
    )
