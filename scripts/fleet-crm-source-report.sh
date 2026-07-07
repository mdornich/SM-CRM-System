#!/usr/bin/env zsh
set -euo pipefail

REPO_DIR="/Users/mitchdornich/Documents/GitHub/SM-CRM-System"
cd "$REPO_DIR"

set -a
source .env
set +a

source .venv/bin/activate
python -m relationship_intel.cli report
