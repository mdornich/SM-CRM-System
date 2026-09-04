#!/usr/bin/env zsh
# Persistent review UI server (gh #17 UX — no terminal needed).
# Loaded by launchd via com.stablemischief.smcrm-reviewui.plist and kept
# alive so the operator can just open http://127.0.0.1:8765/ in a browser.
set -euo pipefail

source "${0:A:h}/_repo-env.sh"

exec python -m relationship_intel.cli review-ui --host 127.0.0.1 --port 8765
