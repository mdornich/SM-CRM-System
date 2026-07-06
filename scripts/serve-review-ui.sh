#!/usr/bin/env zsh
# Persistent review UI server (gh #17 UX — no terminal needed).
# Loaded by launchd via com.stablemischief.smcrm-reviewui.plist and kept
# alive so the operator can just open http://127.0.0.1:8765/ in a browser.
set -euo pipefail

REPO_DIR="/Users/mitchdornich/Documents/GitHub/SM-CRM-System"
cd "$REPO_DIR"

mkdir -p output/logs

set -a
source .env
set +a

source .venv/bin/activate

exec python -m relationship_intel.cli review-ui --host 127.0.0.1 --port 8765
