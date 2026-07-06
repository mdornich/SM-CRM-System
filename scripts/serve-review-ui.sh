#!/usr/bin/env zsh
# Persistent review UI server (gh #17 UX — no terminal needed).
# Loaded by launchd via com.stablemischief.smcrm-reviewui.plist and kept
# alive so the operator can just open http://127.0.0.1:8765/ in a browser.
set -euo pipefail

REPO_DIR="/Users/mitchdornich/GitHub/SM-CRM-System"
cd "$REPO_DIR"

mkdir -p output/logs

set -a
source .env
set +a

# Venv is installed OUTSIDE ~/Documents/ so macOS TCC / Full Disk Access
# never blocks the LaunchAgent context. Fallback to the repo-local dev
# venv when the ~/.venvs one is missing (useful for `./scripts/…` runs
# by a fresh clone before install).
VENV="$HOME/.venvs/sm-crm-system"
if [[ ! -d "$VENV" ]]; then
    VENV="$REPO_DIR/.venv"
fi
source "$VENV/bin/activate"

exec python -m relationship_intel.cli review-ui --host 127.0.0.1 --port 8765
