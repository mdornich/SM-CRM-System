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
python -m relationship_intel.cli review-queue --json

if [[ "$(date +%u)" == "1" ]]; then
  python -m relationship_intel.cli weekly-plan --json
fi
