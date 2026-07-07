#!/usr/bin/env sh
set -eu

DATA_DIR="${SMCRM_DATA_DIR:-/data/smcrm}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8765}"

mkdir -p \
  "$DATA_DIR/transcripts-inbox" \
  "$DATA_DIR/processed-transcripts" \
  "$DATA_DIR/failed-transcripts" \
  "$DATA_DIR/obsidian-vault" \
  "$DATA_DIR/mock_crm"

exec python -m relationship_intel.cli review-ui --host "$HOST" --port "$PORT"
