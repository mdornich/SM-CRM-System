"""Slug assignment. Base slugs are stable; collisions get a record-id suffix so
two same-named entities can never share a vault note path. The first (lowest-id)
record keeps the base slug, so existing notes stay put when a collision appears
later."""

from __future__ import annotations

import re


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "unnamed"


def assign_slugs(rows: list[tuple[int, str]]) -> dict[int, str]:
    """rows: (id, name) in id order -> {id: unique slug}."""
    first_owner: dict[str, int] = {}
    slugs: dict[int, str] = {}
    for record_id, name in rows:
        base = slugify(name)
        if base not in first_owner:
            first_owner[base] = record_id
            slugs[record_id] = base
        else:
            slugs[record_id] = f"{base}-{record_id}"
    return slugs
