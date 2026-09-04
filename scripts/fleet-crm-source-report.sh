#!/usr/bin/env zsh
set -euo pipefail

source "${0:A:h}/_repo-env.sh"
python -m relationship_intel.cli report
