#!/usr/bin/env zsh
set -euo pipefail

REPO_DIR="/Users/mitchdornich/Documents/GitHub/SM-CRM-System"
cd "$REPO_DIR"

mkdir -p output/logs

# OBSIDIAN_VAULT_PATH and other SM-CRM secrets live in the same Infisical
# project (agent-native-os) that 980labsOS renders locally. Source its
# rendered env file directly rather than keeping a repo-local .env file.
# (with-8d-env.sh itself execs its command arg, so it can't be sourced —
# it's built to wrap one child process, not to export into this shell.)
AGENT_NATIVE_OS_ENV_FILE="${AGENT_NATIVE_OS_INFISICAL_ENV_FILE:-$HOME/.infisical/agent-native-os.env}"
if [[ ! -f "$AGENT_NATIVE_OS_ENV_FILE" ]]; then
  echo "credential_preflight_failed: missing env file: $AGENT_NATIVE_OS_ENV_FILE" >&2
  exit 10
fi
set -a
source "$AGENT_NATIVE_OS_ENV_FILE"
set +a

# Venv is installed OUTSIDE ~/Documents/ so macOS TCC / Full Disk Access
# never blocks the LaunchAgent context. Fallback to repo-local venv for
# fresh clones that haven't run the install yet.
VENV="$HOME/.venvs/sm-crm-system"
if [[ ! -d "$VENV" ]]; then
    VENV="$REPO_DIR/.venv"
fi
source "$VENV/bin/activate"

python -m relationship_intel.cli init --json
python -m relationship_intel.cli ingest --json

# Capture the pending-count so we can fire a macOS notification when new
# items are waiting for review. gh #17 — the operator should never have to
# type venv commands to know something needs attention.
REVIEW_JSON="$(python -m relationship_intel.cli review-queue --json)"
echo "$REVIEW_JSON"

PENDING=$(printf '%s' "$REVIEW_JSON" | python -c 'import json, sys; print(json.load(sys.stdin)["by_status"]["pending"])')

if [[ "$PENDING" -gt 0 ]]; then
  osascript -e "display notification \"$PENDING item(s) awaiting approval — open Twenty's Home dashboard (Pending review tab)\" with title \"SM-CRM: review queue\" sound name \"Ping\"" || true
fi

if [[ "$(date +%u)" == "1" ]]; then
  python -m relationship_intel.cli weekly-plan --json
  # Push the freshly-generated plan into Twenty's Home dashboard widget.
  # --refresh-plan is required — provision-twenty is a no-op without it,
  # so re-runs to reconfirm schema don't blow away manual edits (see the
  # provisioner's ensure_home_dashboard docstring). Failures here should
  # not break the daily pipeline; the plan is still readable in the vault.
  python -m relationship_intel.cli provision-twenty --refresh-plan --json || \
    echo "warn: provision-twenty --refresh-plan failed; plan is still in the vault"
  osascript -e "display notification \"Weekly plan for the current week has been generated — see the Home dashboard in Twenty (or relationship-intelligence/weekly-plans/)\" with title \"SM-CRM: weekly plan ready\"" || true
fi
