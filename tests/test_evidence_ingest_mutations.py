"""Re-run decision tests against isolated reverted source; never edit the checkout."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "old,new",
    [
        ('"high": 0.9', '"high": 0.8'),
        ('locator = "page"', 'locator = "whole-page"'),
    ],
    ids=["confidence", "locator"],
)
def test_reverted_decision_is_detected(tmp_path, old, new):
    root = Path(__file__).resolve().parents[1]
    source_root = tmp_path / "src"
    shutil.copytree(root / "src", source_root, ignore=shutil.ignore_patterns("__pycache__"))
    source = source_root / "relationship_intel/opportunity_engine/ingest.py"
    original = source.read_text()
    assert original.count(old) == 1
    env = dict(os.environ, PYTHONPATH=str(source_root), PYTHONDONTWRITEBYTECODE="1")
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "tests/test_evidence_ingest.py::test_pure_mapping_confidence_and_locator",
    ]
    control = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
    assert control.returncode == 0, control.stdout + control.stderr
    source.write_text(original.replace(old, new))
    reverted = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
    assert reverted.returncode == 1, reverted.stdout + reverted.stderr
    assert "AssertionError" in reverted.stdout
    assert "FAILED tests/test_evidence_ingest.py::test_pure_mapping" in reverted.stdout
