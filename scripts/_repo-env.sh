#!/usr/bin/env zsh
# Shared environment bootstrap for SM-CRM shell entrypoints.
#
# Sourced (not executed) by scripts/*.sh. It does three things:
#
#   1. Resolves REPO_DIR from the script's own location instead of a hardcoded
#      absolute path, so the same script works on the MacBook Pro checkout and
#      on the Mac mini checkout (/Users/980macmini/Documents/GitHub/...).
#   2. Sources .env ONLY when the file exists. On the mini there is no .env:
#      secrets are rendered by the 980labsOS 8D Infisical Agent and injected by
#      scripts/with-8d-env.sh. relationship_intel.config.load_settings() calls
#      python-dotenv's load_dotenv(), which does not override values already
#      present in the process environment, so the wrapper path works with no
#      dotfile on disk. Never write real secrets into a repo .env.
#   3. Activates the venv, preferring the TCC-safe ~/.venvs/sm-crm-system one
#      and falling back to the repo-local .venv.

REPO_DIR="${REPO_DIR:-${0:A:h:h}}"
cd "$REPO_DIR"

mkdir -p output/logs

if [[ -f "$REPO_DIR/.env" ]]; then
    set -a
    source "$REPO_DIR/.env"
    set +a
fi

VENV="${SM_CRM_VENV:-$HOME/.venvs/sm-crm-system}"
if [[ ! -d "$VENV" ]]; then
    VENV="$REPO_DIR/.venv"
fi
source "$VENV/bin/activate"
