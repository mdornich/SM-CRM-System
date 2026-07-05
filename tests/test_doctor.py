from __future__ import annotations

from pathlib import Path

from relationship_intel import doctor
from relationship_intel.config import Settings
from relationship_intel.crm.twenty_adapter import TwentyCRMAdapter
from relationship_intel.doctor import run_doctor


def _repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "launchd").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "launchd" / "com.stablemischief.relationship-intel.daily.plist").write_text(
        "<plist />",
        encoding="utf-8",
    )
    script = root / "scripts" / "relationship-intel-daily.sh"
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    script.chmod(0o755)
    return root


def test_doctor_reports_warns_without_live_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    settings = Settings(
        obsidian_vault_path=tmp_path / "vault",
        transcripts_inbox_dir=tmp_path / "inbox",
        db_path=tmp_path / "ri.db",
        mock_crm_path=tmp_path / "mock_crm",
    )

    report = run_doctor(settings, repo_root=_repo_root(tmp_path))

    assert report["status"] == "warn"
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["llm"]["status"] == "warn"
    assert checks["granola"]["status"] == "warn"
    assert checks["twenty"]["status"] == "warn"
    assert checks["launchd_installed"]["status"] == "warn"


def test_doctor_blocks_when_twenty_configured_but_unreachable(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    settings = Settings(
        crm_provider="twenty",
        twenty_api_key="test-key",
        obsidian_vault_path=tmp_path / "vault",
        transcripts_inbox_dir=tmp_path / "inbox",
        db_path=tmp_path / "ri.db",
    )

    def boom(self):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(TwentyCRMAdapter, "_opportunity_metadata", boom)

    report = run_doctor(settings, repo_root=_repo_root(tmp_path))

    checks = {check["name"]: check for check in report["checks"]}
    assert report["status"] == "blocked"
    assert checks["twenty"]["status"] == "blocked"
    assert "unreachable" in checks["twenty"]["message"]


def test_doctor_ok_for_twenty_probe_success(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    settings = Settings(
        crm_provider="twenty",
        twenty_api_key="test-key",
        obsidian_vault_path=tmp_path / "vault",
        transcripts_inbox_dir=tmp_path / "inbox",
        db_path=tmp_path / "ri.db",
    )

    def ok(self):
        return {"fields": []}

    monkeypatch.setattr(TwentyCRMAdapter, "_opportunity_metadata", ok)

    report = run_doctor(settings, repo_root=_repo_root(tmp_path))

    checks = {check["name"]: check for check in report["checks"]}
    assert checks["twenty"]["status"] == "ok"


def test_doctor_ok_for_codex_provider_when_cli_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/local/bin/codex")
    settings = Settings(
        llm_provider="codex",
        obsidian_vault_path=tmp_path / "vault",
        transcripts_inbox_dir=tmp_path / "inbox",
        db_path=tmp_path / "ri.db",
    )

    report = run_doctor(settings, repo_root=_repo_root(tmp_path))

    checks = {check["name"]: check for check in report["checks"]}
    assert checks["llm"]["status"] == "ok"
    assert "Codex CLI" in checks["llm"]["message"]
