#!/usr/bin/env zsh
# Persistent review UI server (gh #17 UX — no terminal needed).
# Invoked by scripts/review-gate.sh, which launchd keeps alive via
# com.stablemischief.smcrm-reviewgate.plist, so the operator can just open
# http://127.0.0.1:8765/ in a browser. Run it directly only on a host that
# already has the environment (it does no credential checking of its own).
set -euo pipefail

source "${0:A:h}/_repo-env.sh"

# "$@" is forwarded so `review-gate.sh --port 9000` actually changes the port;
# later argparse values win over the defaults above.
exec python -m relationship_intel.cli review-ui --host 127.0.0.1 --port 8765 "$@"
