"""Wikilink + note-name helpers. Slugs are computed centrally (util/slugs +
Repository) so collisions are handled in one place; transcript note names carry
a content-hash suffix so recurring meeting titles can never overwrite each other."""

from __future__ import annotations

from relationship_intel.util.slugs import slugify

__all__ = ["slugify", "transcript_note_name", "wikilink"]


def wikilink(target: str, label: str | None = None) -> str:
    return f"[[{target}|{label}]]" if label else f"[[{target}]]"


def transcript_note_name(meeting_date: str | None, title: str, transcript_hash: str) -> str:
    prefix = f"{meeting_date}-" if meeting_date else ""
    return f"{prefix}{slugify(title)}-{transcript_hash[:8]}"
