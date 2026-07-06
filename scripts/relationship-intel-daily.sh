#!/usr/bin/env zsh
set -euo pipefail

REPO_DIR="/Users/mitchdornich/Documents/GitHub/SM-CRM-System"
cd "$REPO_DIR"

mkdir -p output/logs

set -a
source .env
set +a

source .venv/bin/activate

python -m relationship_intel.cli init --json
python -m relationship_intel.cli ingest --json

# Capture the pending-count so we can fire a macOS notification when new
# items are waiting for review. gh #17 — the operator should never have to
# type venv commands to know something needs attention.
REVIEW_JSON="$(python -m relationship_intel.cli review-queue --json)"
echo "$REVIEW_JSON"

PENDING=$(printf '%s' "$REVIEW_JSON" | python -c 'import json, sys; print(json.load(sys.stdin)["by_status"]["pending"])')

if [[ "$PENDING" -gt 0 ]]; then
  osascript -e "display notification \"$PENDING item(s) awaiting approval — open http://127.0.0.1:8765/\" with title \"SM-CRM: review queue\" sound name \"Ping\"" || true
fi

if [[ "$(date +%u)" == "1" ]]; then
  python -m relationship_intel.cli weekly-plan --json
  osascript -e "display notification \"Weekly plan for the current week has been generated — see relationship-intelligence/weekly-plans/\" with title \"SM-CRM: weekly plan ready\"" || true
fi
