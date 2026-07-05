"""CodexExecClient tests use a fake runner; no real Codex call is made."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from relationship_intel.errors import NotConfiguredError
from relationship_intel.extraction.llm_client import CodexExecClient, make_client


def test_codex_client_invokes_codex_exec_with_schema(tmp_path, monkeypatch):
    codex_bin = tmp_path / "codex"
    codex_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    codex_bin.chmod(0o755)
    calls = []
    schemas = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        schema_path = Path(args[args.index("--output-schema") + 1])
        schemas.append(json.loads(schema_path.read_text(encoding="utf-8")))
        output_path = Path(args[args.index("-o") + 1])
        output_path.write_text('{"ok": true}', encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    client = CodexExecClient(codex_bin=str(codex_bin), runner=runner, cwd=tmp_path)

    result = client.complete("system prompt", '{"metadata": {}, "transcript": "hello"}', {})

    assert result == {"ok": True}
    args, kwargs = calls[0]
    assert args[:4] == [str(codex_bin), "exec", "--sandbox", "read-only"]
    assert "--output-schema" in args
    assert kwargs["input"].startswith("system prompt")
    assert '"transcript": "hello"' in kwargs["input"]
    assert schemas == [{}]


def test_codex_client_passes_model_when_configured(tmp_path):
    codex_bin = tmp_path / "codex"
    codex_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    codex_bin.chmod(0o755)
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        output_path = Path(args[args.index("-o") + 1])
        output_path.write_text('{"ok": true}', encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    client = CodexExecClient(codex_bin=str(codex_bin), model="gpt-5.4-mini", runner=runner)

    assert client.complete("system", "{}", {}) == {"ok": True}
    assert "--model" in calls[0]
    assert calls[0][calls[0].index("--model") + 1] == "gpt-5.4-mini"


def test_codex_client_strips_markdown_json_fence(tmp_path):
    codex_bin = tmp_path / "codex"
    codex_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    codex_bin.chmod(0o755)

    def runner(args, **kwargs):
        output_path = Path(args[args.index("-o") + 1])
        output_path.write_text('```json\n{"ok": true}\n```', encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    client = CodexExecClient(codex_bin=str(codex_bin), runner=runner, cwd=tmp_path)

    assert client.complete("system", "{}", {}) == {"ok": True}


def test_codex_client_missing_binary_is_not_configured():
    client = CodexExecClient(codex_bin="/definitely/missing/codex")

    with pytest.raises(NotConfiguredError):
        client.complete("system", "{}", {})


def test_codex_client_strict_schema_adds_required_additional_properties():
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "nested": {
                "type": "object",
                "default": {},
                "properties": {"ok": {"type": "boolean"}},
            },
        },
    }

    strict = CodexExecClient._strict_json_schema(schema)

    assert strict["additionalProperties"] is False
    assert strict["required"] == ["name", "nested"]
    assert "default" not in strict["properties"]["nested"]
    assert strict["properties"]["nested"]["additionalProperties"] is False
    assert strict["properties"]["nested"]["required"] == ["ok"]


def test_make_client_supports_codex_provider():
    assert isinstance(make_client("codex"), CodexExecClient)
