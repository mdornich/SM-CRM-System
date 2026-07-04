"""Content hashing. The transcript hash is the identity key for intake dedupe,
so normalization must be stable across newline style and trailing whitespace."""

from __future__ import annotations

import hashlib


def normalize_text(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()
