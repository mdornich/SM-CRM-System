"""Slug + wikilink helpers. Slugs are stable (derived from names only) so links
stay valid across re-runs."""

from __future__ import annotations

import re


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "unnamed"


def wikilink(target: str, label: str | None = None) -> str:
    return f"[[{target}|{label}]]" if label else f"[[{target}]]"


def transcript_note_name(meeting_date: str | None, title: str) -> str:
    prefix = f"{meeting_date}-" if meeting_date else ""
    return f"{prefix}{slugify(title)}"
