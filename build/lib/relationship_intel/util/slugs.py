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
    """rows: (id, name) in id order -> {id: unique slug}.

    Suffixed slugs are registered as taken too, so an id-suffix can never
    collide with a natural base slug (e.g. a person literally named "Jane
    Doe 5"). Processing in id order keeps earlier assignments stable when
    colliders appear later."""
    taken: set[str] = set()
    slugs: dict[int, str] = {}
    for record_id, name in rows:
        candidate = slugify(name)
        if candidate in taken:
            candidate = f"{candidate}-{record_id}"
        while candidate in taken:
            candidate = f"{candidate}-{record_id}"
        taken.add(candidate)
        slugs[record_id] = candidate
    return slugs
