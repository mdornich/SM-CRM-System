#!/usr/bin/env sh
set -eu

DATA_DIR="${SMCRM_DATA_DIR:-/data/smcrm}"
INBOX="${TRANSCRIPTS_INBOX_DIR:-$DATA_DIR/transcripts-inbox}"
PROCESSED="${SMCRM_PROCESSED_TRANSCRIPTS_DIR:-$DATA_DIR/processed-transcripts}"
ARCHIVE_PROCESSED="${SMCRM_ARCHIVE_PROCESSED_TRANSCRIPTS:-true}"

mkdir -p "$INBOX" "$PROCESSED" "$DATA_DIR/obsidian-vault" "$DATA_DIR/mock_crm"

python -m relationship_intel.cli init --json
python -m relationship_intel.cli ingest --json
python -m relationship_intel.cli review-queue --json

if [ "$(date +%u)" = "1" ]; then
  python -m relationship_intel.cli weekly-plan --json
  python -m relationship_intel.cli report --json
fi

if [ "$ARCHIVE_PROCESSED" = "true" ]; then
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  archive_dir="$PROCESSED/$stamp"
  mkdir -p "$archive_dir"
  found=false
  for file in "$INBOX"/*.md "$INBOX"/*.txt; do
    [ -e "$file" ] || continue
    found=true
    mv "$file" "$archive_dir/"
  done
  if [ "$found" = "false" ]; then
    rmdir "$archive_dir"
  fi
fi
