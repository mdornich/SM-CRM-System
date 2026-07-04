"""Structural security tests (KTD-8a, build-prompt test 12): the codebase has no
outbound-send capability and the CRM interface has no destructive methods."""

from __future__ import annotations

import inspect
from pathlib import Path

from relationship_intel.crm.base import CRMAdapter

SRC = Path(__file__).parent.parent / "src" / "relationship_intel"

FORBIDDEN_TOKENS = (
    "smtplib",
    "sendmail",
    "imaplib",
    "poplib",
    "twilio",
    "slack_sdk",
    "sendgrid",
    "mailgun",
    "import requests",
    "from requests",
    # stdlib channels that could smuggle outbound traffic past the httpx allowlist
    "urllib",
    "http.client",
    "import socket",
    "ftplib",
    "subprocess",
    "os.system",
)

# The ONLY permitted network surfaces (spec §3.8: no sending code exists anywhere).
# Granola is read-only intake; Twenty is additive CRM sync; Anthropic is extraction.
HTTP_ALLOWED = {"crm/twenty_adapter.py", "extraction/llm_client.py", "intake/granola_api.py"}


def _sources() -> dict[str, str]:
    return {str(p.relative_to(SRC)): p.read_text(encoding="utf-8") for p in SRC.rglob("*.py")}


def test_no_outbound_send_modules_anywhere():
    for rel, text in _sources().items():
        for token in FORBIDDEN_TOKENS:
            assert token not in text, f"forbidden outbound token {token!r} in {rel}"


def test_httpx_confined_to_declared_network_surfaces():
    users = {rel for rel, text in _sources().items() if "httpx" in text}
    assert users <= HTTP_ALLOWED, f"unexpected network surface(s): {users - HTTP_ALLOWED}"


def test_crm_interface_has_no_destructive_methods():
    method_names = {name.lower() for name, _ in inspect.getmembers(CRMAdapter)}
    for verb in ("delete", "remove", "destroy", "archive", "purge"):
        assert not any(verb in name for name in method_names), (
            f"CRMAdapter exposes a destructive method containing {verb!r}"
        )
