"""Local transcript folder intake — the contractual fallback source, forever.
Reads .md/.txt, parses optional YAML frontmatter, falls back to the
YYYY-MM-DD-source-title.md filename convention. Dedupe happens at the gate
via transcript_hash (logging references the hash only, never transcript text)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Protocol

import yaml

from relationship_intel.util.dates import parse_iso_date
from relationship_intel.util.hashing import content_hash

logger = logging.getLogger(__name__)

_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)$")


@dataclass
class RawTranscript:
    source_system: str
    source_id: str
    title: str
    raw_text: str
    transcript_hash: str
    meeting_date: date | None = None
    owner: str | None = None
    attendees: list[str] = field(default_factory=list)
    source_path: Path | None = None


class TranscriptSource(Protocol):
    def iter_transcripts(self) -> list[RawTranscript]: ...


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n---", 2)
    if len(parts) < 2:
        return {}, text
    try:
        meta = yaml.safe_load(parts[0].lstrip("-").lstrip("\n")) or {}
        if not isinstance(meta, dict):
            return {}, text
    except yaml.YAMLError:
        logger.warning("Malformed frontmatter; falling back to filename metadata")
        return {}, text
    body = parts[1]
    if len(parts) == 3:
        body = parts[1] + "\n---" + parts[2]
    # parts[1] begins right after the closing delimiter line's leading newline
    body = body.split("\n", 1)[1] if body.startswith("-") else body
    return meta, body.lstrip("\n")


def _parse_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return parse_iso_date(value.strip())
        except ValueError:
            return None
    return None


class LocalFolderSource:
    def __init__(self, folder: str | Path, source_system: str = "local"):
        self.folder = Path(folder)
        self.source_system = source_system

    def iter_transcripts(self) -> list[RawTranscript]:
        transcripts: list[RawTranscript] = []
        for path in sorted(self.folder.glob("*")):
            if path.suffix.lower() not in (".md", ".txt") or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            meta, body = _split_frontmatter(text)

            meeting_date = _parse_date(meta.get("date"))
            title = str(meta["title"]) if meta.get("title") else None
            if title is None or meeting_date is None:
                m = _FILENAME_RE.match(path.stem)
                if m:
                    meeting_date = meeting_date or _parse_date(m.group(1))
                    title = title or m.group(2).replace("-", " ").strip()
            title = title or path.stem

            attendees = meta.get("attendees") or []
            if isinstance(attendees, str):
                attendees = [a.strip() for a in attendees.split(",") if a.strip()]

            t = RawTranscript(
                source_system=str(meta.get("source_system") or self.source_system),
                source_id=str(meta.get("source_id") or path.name),
                title=title,
                raw_text=body,
                transcript_hash=content_hash(body),
                meeting_date=meeting_date,
                owner=str(meta["owner"]) if meta.get("owner") else None,
                attendees=[str(a) for a in attendees],
                source_path=path,
            )
            logger.info("Loaded transcript %s (hash=%s)", path.name, t.transcript_hash[:12])
            transcripts.append(t)
        return transcripts
