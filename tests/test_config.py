"""Settings/env parsing (plan U1 scenarios)."""

from __future__ import annotations

from pathlib import Path

from relationship_intel.config import Settings, _bool, load_settings


def test_defaults_resolve_without_env(monkeypatch, tmp_path):
    for var in (
        "LLM_PROVIDER",
        "CODEX_MODEL",
        "ANTHROPIC_MODEL",
        "CRM_PROVIDER",
        "OBSIDIAN_VAULT_PATH",
        "STORE_RAW_TRANSCRIPTS",
        "TWENTY_API_URL",
        "TRANSCRIPTS_INBOX_DIR",
        "DEFAULT_OWNER",
        "STALL_THRESHOLD_DAYS",
    ):
        monkeypatch.delenv(var, raising=False)
    # Point at an empty env file so the developer's real repo .env (which may
    # legitimately set CRM_PROVIDER=twenty etc.) cannot leak into this test.
    empty_env = tmp_path / "empty.env"
    empty_env.touch()
    settings = load_settings(env_file=empty_env)
    assert settings.llm_provider == "mock"
    assert settings.codex_model == ""
    assert settings.anthropic_model == "claude-sonnet-5"
    assert settings.crm_provider == "mock"
    assert settings.twenty_api_url == "http://localhost:3002"
    assert settings.transcripts_inbox_dir == Path("./examples/transcripts")
    assert settings.store_raw_transcripts is True
    assert settings.default_owner == "James"
    assert settings.stall_threshold_days == 21


def test_env_overrides_win(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("CODEX_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-test")
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/tmp/elsewhere")
    monkeypatch.setenv("TRANSCRIPTS_INBOX_DIR", "/tmp/inbox")
    monkeypatch.setenv("STALL_THRESHOLD_DAYS", "30")
    settings = load_settings()
    assert settings.llm_provider == "anthropic"
    assert settings.codex_model == "gpt-5.4-mini"
    assert settings.anthropic_model == "claude-sonnet-test"
    assert settings.obsidian_vault_path == Path("/tmp/elsewhere")
    assert settings.transcripts_inbox_dir == Path("/tmp/inbox")
    assert settings.stall_threshold_days == 30


def test_blank_anthropic_model_env_falls_back_to_default(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_MODEL", "   ")
    empty_env = tmp_path / "empty.env"
    empty_env.touch()

    settings = load_settings(env_file=empty_env)

    assert settings.anthropic_model == "claude-sonnet-5"


def test_store_raw_transcripts_boolean_forms(monkeypatch):
    for value, expected in (
        ("false", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("true", True),
        ("1", True),
        ("yes", True),
        ("", True),
    ):
        monkeypatch.setenv("STORE_RAW_TRANSCRIPTS", value)
        assert load_settings().store_raw_transcripts is expected, value


def test_invalid_stall_threshold_is_a_clear_config_error(monkeypatch):
    import pytest

    from relationship_intel.errors import NotConfiguredError

    monkeypatch.setenv("STALL_THRESHOLD_DAYS", "three weeks")
    with pytest.raises(NotConfiguredError, match="STALL_THRESHOLD_DAYS"):
        load_settings()


def test_bool_helper_default_only_on_missing_or_blank():
    assert _bool(None, True) is True
    assert _bool("  ", False) is False
    assert _bool("TRUE", False) is True
    assert _bool("nonsense", True) is False


def test_settings_frozen():
    settings = Settings()
    try:
        settings.llm_provider = "other"  # type: ignore[misc]
        raise AssertionError("Settings should be frozen")
    except AttributeError:
        pass
