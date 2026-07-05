"""Vault writer with managed-section idempotency (architecture.md KTD-7 mechanism).

Layout of every generated note:

    ---
    <generated frontmatter, incl. content_hash of the managed region>
    ---
    <manual text here survives re-runs>
    <!-- ri:begin main -->
    <AI-managed content>
    <!-- ri:end main -->
    <manual text here survives re-runs>

Rules enforced here:
- unchanged input -> byte-for-byte no-op
- out-of-marker manual edits preserved verbatim; a .bak lands in .ri-backups/ before
  any file containing manual edits is rewritten
- unbalanced/corrupted markers -> file treated as fully manual: skip rewrite, warn,
  still write the .bak (conservative fallback)
- backups capped at the 10 most recent per source file"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from relationship_intel.util.hashing import short_hash
from relationship_intel.util.markdown import frontmatter_block

logger = logging.getLogger(__name__)

BEGIN = "<!-- ri:begin main -->"
END = "<!-- ri:end main -->"
BACKUP_KEEP = 10

_FM_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def managed_hash(managed: str) -> str:
    return short_hash(managed)


class VaultWriter:
    """Write generated artifacts into either the POC or Cairns vault layout."""

    _PLAIN_FOLDERS = {
        "transcripts": "transcripts",
        "people": "people",
        "companies": "companies",
        "opportunities": "opportunities",
        "weekly-plans": "weekly-plans",
        "promotion-proposals": "promotion-proposals",
        "indexes": "indexes",
        "reports": "reports",
    }
    _CAIRNS_FOLDERS = {
        "transcripts": "raw/relationships/transcripts",
        "people": "card-catalog/L2/relationships/people",
        "companies": "card-catalog/L2/relationships/companies",
        "opportunities": "card-catalog/L2/relationships/opportunities",
        "weekly-plans": "card-catalog/L2/relationships/weekly-plans",
        "promotion-proposals": "manifests/relationship-intelligence/promotion-proposals",
        "indexes": "manifests/relationship-intelligence/indexes",
        "reports": "manifests/relationship-intelligence/reports",
    }

    def __init__(self, vault_root: str | Path, mode: str = "plain"):
        self.mode = mode.strip().lower()
        if self.mode not in ("plain", "cairns"):
            raise ValueError(f"Unsupported Obsidian mode: {mode!r}")
        vault_root = Path(vault_root)
        self.root = vault_root / "relationship-intelligence" if self.mode == "plain" else vault_root

    @property
    def folder_names(self) -> tuple[str, ...]:
        return tuple(self._folder_map)

    @property
    def _folder_map(self) -> dict[str, str]:
        return self._PLAIN_FOLDERS if self.mode == "plain" else self._CAIRNS_FOLDERS

    def dir_for(self, folder: str) -> Path:
        try:
            mapped = self._folder_map[folder]
        except KeyError as exc:
            raise ValueError(f"Unknown vault artifact folder: {folder!r}") from exc
        return self.root / mapped

    def path_for(self, folder: str, note_name: str) -> Path:
        return self.dir_for(folder) / f"{note_name}.md"

    def write_note(
        self,
        folder: str,
        note_name: str,
        frontmatter: list[tuple[str, object]],
        managed: str,
    ) -> Path:
        path = self.path_for(folder, note_name)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Defang any literal ri: markers arriving via content (e.g. a transcript
        # quoting them) — an embedded marker would corrupt marker counting and
        # permanently freeze the note. Deterministic, so re-runs stay byte-stable.
        managed = managed.replace("<!-- ri:begin", "<!-- ri(escaped):begin").replace(
            "<!-- ri:end", "<!-- ri(escaped):end"
        )

        frontmatter = frontmatter + [("content_hash", managed_hash(managed))]
        rendered_fm = frontmatter_block(frontmatter)

        if not path.exists():
            path.write_text(f"{rendered_fm}\n{BEGIN}\n{managed}\n{END}\n", encoding="utf-8")
            return path

        existing = path.read_text(encoding="utf-8")
        begin_count, end_count = existing.count(BEGIN), existing.count(END)
        if begin_count != 1 or end_count != 1 or existing.index(BEGIN) > existing.index(END):
            logger.warning(
                "Unbalanced ri: markers in %s — treating as fully manual, skipping rewrite",
                path,
            )
            self._backup(path, existing)
            return path

        pre_all, rest = existing.split(BEGIN, 1)
        old_managed, post = rest.split(END, 1)
        old_managed = old_managed.strip("\n")
        fm_match = _FM_RE.match(pre_all)
        pre = pre_all[fm_match.end() :] if fm_match else pre_all
        old_hash = _stored_hash(fm_match.group(0)) if fm_match else None

        candidate = f"{rendered_fm}\n{pre}{BEGIN}\n{managed}\n{END}{post}"
        if candidate == existing:
            return path

        manually_edited = (
            bool(pre.strip())
            or bool(post.strip())
            or (old_hash is not None and managed_hash(old_managed) != old_hash)
        )
        if manually_edited:
            self._backup(path, existing)
        path.write_text(candidate, encoding="utf-8")
        return path

    def _backup(self, path: Path, content: str) -> None:
        rel = path.relative_to(self.root)
        backup_dir = self.root / ".ri-backups" / rel.parent / rel.stem
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        (backup_dir / f"{stamp}.md").write_text(content, encoding="utf-8")
        backups = sorted(backup_dir.glob("*.md"))
        for old in backups[:-BACKUP_KEEP]:
            old.unlink()

    def write_jsonl_index(self, name: str, lines: list[str]) -> Path:
        path = self.dir_for("indexes") / f"{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(lines) + ("\n" if lines else "")
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
        return path

    def write_report(self, filename: str, content: str) -> Path:
        path = self.dir_for("reports") / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
        return path

    def write_json_artifact(self, folder: str, filename: str, content: str) -> Path:
        path = self.dir_for(folder) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
        return path

    def ensure_readme(self) -> None:
        path = (
            self.root / "README.md"
            if self.mode == "plain"
            else self.root / "card-catalog" / "L2" / "relationships" / "README.md"
        )
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# Relationship Intelligence Archive\n\n"
            "Generated by the SM-CRM-System pipeline (evidence layer — the CRM holds\n"
            "operational summaries only). AI-managed content lives between\n"
            "`<!-- ri:begin main -->` / `<!-- ri:end main -->` markers; anything you\n"
            "write outside the markers survives re-runs. Notes default to\n"
            "`review_status: unreviewed` until a human reviews them (ORD-0003).\n",
            encoding="utf-8",
        )


def _stored_hash(frontmatter_text: str) -> str | None:
    for line in frontmatter_text.splitlines():
        if line.startswith("content_hash:"):
            return line.split(":", 1)[1].strip()
    return None
