"""CLI integration: run-demo end-to-end via subprocess (the R1 exit criterion),
init idempotency, and argparse guardrails."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent


def _run(args: list[str], tmp_path: Path) -> subprocess.CompletedProcess:
    env = dict(
        os.environ,
        OBSIDIAN_VAULT_PATH=str(tmp_path / "vault"),
        TRANSCRIPTS_INBOX_DIR=str(tmp_path / "inbox"),
        RI_DB_PATH=str(tmp_path / "ri.db"),
        RI_MOCK_CRM_PATH=str(tmp_path / "mock_crm"),
        LLM_PROVIDER="mock",
        CRM_PROVIDER="mock",
        TWENTY_API_KEY="",
    )
    return subprocess.run(
        [sys.executable, "-m", "relationship_intel.cli", *args],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
    )


def test_run_demo_exits_zero_and_produces_all_artifacts(tmp_path):
    result = _run(["run-demo"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert "run-demo complete" in result.stdout
    root = tmp_path / "vault" / "relationship-intelligence"
    assert list((root / "weekly-plans").glob("*.md"))
    assert list((root / "weekly-plans").glob("*.json"))
    assert list((root / "reports").glob("CRM-*.json"))
    assert (tmp_path / "ri.db").exists()
    assert (tmp_path / "mock_crm" / "opportunities.json").exists()


def test_init_is_idempotent(tmp_path):
    assert _run(["init"], tmp_path).returncode == 0
    assert _run(["init"], tmp_path).returncode == 0


def test_init_json_outputs_machine_readable_paths(tmp_path):
    result = _run(["init", "--json"], tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["db_path"] == str(tmp_path / "ri.db")
    assert payload["vault_path"].endswith("relationship-intelligence")


def test_ingest_defaults_to_transcripts_inbox_dir(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "2026-07-01-bob-smith.md").write_text(
        "Bob Smith owns Smith HVAC and asked about succession planning.",
        encoding="utf-8",
    )

    result = _run(["ingest", "--json"], tmp_path)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ingested"] == 1


def test_unknown_crm_choice_is_an_argparse_error(tmp_path):
    result = _run(["sync-crm", "--crm", "salesforce"], tmp_path)
    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_malformed_week_start_is_a_clean_error(tmp_path):
    result = _run(["weekly-plan", "--week-start", "not-a-date"], tmp_path)
    assert result.returncode == 2
    assert "Invalid --week-start" in result.stderr
    assert "Traceback" not in result.stderr


def test_sync_twenty_without_key_fails_cleanly(tmp_path):
    result = _run(["sync-crm", "--crm", "twenty"], tmp_path)
    assert result.returncode == 2
    assert "Not configured" in result.stderr
    assert "TWENTY_API_KEY" in result.stderr


def test_sync_twenty_without_key_can_emit_json_error(tmp_path):
    result = _run(["sync-crm", "--crm", "twenty", "--json"], tmp_path)
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["error"] == "not_configured"
    assert "TWENTY_API_KEY" in payload["message"]


def test_query_pipeline_json_reads_sqlite_without_llm(tmp_path):
    assert _run(["run-demo"], tmp_path).returncode == 0

    result = _run(["query", "pipeline", "--json"], tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["query"] == "pipeline"
    assert payload["count"] == 1
    assert payload["results"][0]["lead_type"] == "warm"
    assert payload["results"][0]["succession_signal_score"] >= 50


def test_report_command_emits_contract_json(tmp_path):
    assert _run(["run-demo"], tmp_path).returncode == 0

    result = _run(["report", "--week-start", "2026-07-06"], tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["agent"] == "crm-source"
    assert payload["department"] == "CRM"
    assert isinstance(payload["headline"], str) and payload["headline"]


def test_query_last_touch_and_who_to_call_prose(tmp_path):
    assert _run(["run-demo"], tmp_path).returncode == 0

    last_touch = _run(["query", "last-touch"], tmp_path)
    who = _run(["query", "who-to-call", "--as-of", "2026-07-04"], tmp_path)

    assert last_touch.returncode == 0, last_touch.stderr
    assert "Bob Smith" in last_touch.stdout
    assert "last touch" in last_touch.stdout
    assert who.returncode == 0, who.stderr
    assert "Bob Smith" in who.stdout
    assert "score" in who.stdout


def test_doctor_json_outputs_readiness_checks(tmp_path):
    result = _run(["doctor", "--json"], tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] in {"ok", "warn", "blocked"}
    names = {check["name"] for check in payload["checks"]}
    assert {"obsidian", "db", "granola", "twenty", "launchd_files"} <= names
