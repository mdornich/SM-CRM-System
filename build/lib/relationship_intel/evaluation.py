"""Extraction evaluation harness for redacted acceptance transcripts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from relationship_intel.config import Settings
from relationship_intel.extraction.extractor import Extractor
from relationship_intel.extraction.schemas import SuccessionLeadProfile
from relationship_intel.intake.local_folder import LocalFolderSource


@dataclass(frozen=True)
class Finding:
    field: str
    status: str
    message: str


def run_evaluation(settings: Settings, source: Path) -> dict[str, Any]:
    extractor = Extractor(settings)
    cases = _load_cases(source)
    case_results = []
    for case in cases:
        raw = case["raw"]
        eri = extractor.extract(raw)
        findings = _evaluate_profiles(eri.lead_profiles, case["expected_profiles"])
        passed = all(finding.status == "pass" for finding in findings)
        case_results.append(
            {
                "source_id": raw.source_id,
                "title": raw.title,
                "passed": passed,
                "findings": [finding.__dict__ for finding in findings],
            }
        )
    return {
        "source": str(source),
        "cases": len(case_results),
        "passed": sum(1 for case in case_results if case["passed"]),
        "failed": sum(1 for case in case_results if not case["passed"]),
        "results": case_results,
    }


def _load_cases(source: Path) -> list[dict[str, Any]]:
    source = Path(source)
    raw_by_path = {
        raw.source_path: raw
        for raw in LocalFolderSource(source, source_system="eval").iter_transcripts()
    }
    cases: list[dict[str, Any]] = []
    for path, raw in raw_by_path.items():
        if path is None:
            continue
        meta = _frontmatter(path)
        expected = meta.get("expected") if isinstance(meta, dict) else None
        if not isinstance(expected, dict):
            continue
        profiles = expected.get("profiles") or []
        if not isinstance(profiles, list):
            continue
        cases.append({"raw": raw, "expected_profiles": profiles})
    return cases


def _frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    parts = text.split("\n---", 2)
    if len(parts) < 2:
        return {}
    data = yaml.safe_load(parts[0].lstrip("-").lstrip("\n")) or {}
    return data if isinstance(data, dict) else {}


def _evaluate_profiles(
    profiles: list[SuccessionLeadProfile], expected_profiles: list[dict[str, Any]]
) -> list[Finding]:
    findings: list[Finding] = []
    by_name = {profile.person_name: profile for profile in profiles}
    for expected in expected_profiles:
        name = str(expected.get("person_name") or "")
        profile = by_name.get(name)
        if profile is None:
            findings.append(Finding(f"profile:{name}", "fail", "expected profile not found"))
            continue
        findings.extend(_evaluate_profile(profile, expected))
    return findings


def _evaluate_profile(profile: SuccessionLeadProfile, expected: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    name = profile.person_name
    if "lead_type" in expected:
        findings.append(
            _equals(
                f"{name}.lead_type",
                profile.lead_type.value,
                str(expected["lead_type"]),
            )
        )
    if "timing_window" in expected:
        findings.append(
            _equals(
                f"{name}.timing_window",
                profile.timing_window.value,
                str(expected["timing_window"]),
            )
        )
    if "min_score" in expected:
        minimum = int(expected["min_score"])
        status = "pass" if profile.succession_signal_score >= minimum else "fail"
        findings.append(
            Finding(
                f"{name}.succession_signal_score",
                status,
                f"expected >= {minimum}, got {profile.succession_signal_score}",
            )
        )
    for phrase in _as_list(expected.get("next_action_contains")):
        haystack = (profile.next_best_action or "").lower()
        status = "pass" if phrase.lower() in haystack else "fail"
        findings.append(
            Finding(
                f"{name}.next_best_action",
                status,
                f"expected action to contain {phrase!r}",
            )
        )
    for phrase in _as_list(expected.get("required_evidence")):
        status = (
            "pass"
            if any(phrase.lower() in snippet.lower() for snippet in profile.evidence_snippets)
            else "fail"
        )
        findings.append(
            Finding(
                f"{name}.evidence_snippets",
                status,
                f"expected evidence containing {phrase!r}",
            )
        )
    return findings


def _equals(field: str, actual: str, expected: str) -> Finding:
    status = "pass" if actual == expected else "fail"
    return Finding(field, status, f"expected {expected!r}, got {actual!r}")


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]
