#!/usr/bin/env zsh
# Shared environment bootstrap for SM-CRM shell entrypoints.
#
# Sourced (not executed) by scripts/*.sh. It does three things:
#
#   1. Resolves REPO_DIR from the sourced file's own location. It deliberately
#      does NOT honour a REPO_DIR from the environment: with-8d-env.sh exports
#      the whole Infisical file with `set -a`, so a generic name defined by some
#      other job's secret set could otherwise redirect this into the wrong
#      checkout. `${0:A:h:h}` already resolves correctly on both machines.
#   2. Merges .env at the LOWEST precedence, and only when the file exists.
#      A plain `set -a; source .env` would clobber the values with-8d-env.sh
#      just injected, silently reverting Infisical config to on-disk dev values
#      before Python ever runs. Anything already present in the environment
#      wins; .env fills gaps only. On the mini there is no .env at all — secrets
#      are rendered by the 980labsOS 8D Infisical Agent — and none may be
#      created there.
#   3. Activates the venv, preferring the TCC-safe ~/.venvs/sm-crm-system one
#      and falling back to the repo-local .venv.

REPO_DIR="${0:A:h:h}"
if [[ ! -d "$REPO_DIR/scripts" ]]; then
    print -u2 -- "sm-crm: resolved repo root '$REPO_DIR' has no scripts/ directory"
    return 1 2>/dev/null || exit 1
fi
cd "$REPO_DIR"

mkdir -p output/logs

# Lowest-precedence merge of the dev .env. Values already in the environment
# (i.e. injected by with-8d-env.sh) are never overwritten.
if [[ -f "$REPO_DIR/.env" ]]; then
    while IFS= read -r _line || [[ -n "$_line" ]]; do
        _line="${_line## }"
        [[ -z "$_line" || "$_line" == \#* ]] && continue
        _line="${_line#export }"
        _key="${_line%%=*}"
        [[ "$_key" == "$_line" ]] && continue
        [[ "$_key" =~ '^[A-Za-z_][A-Za-z0-9_]*$' ]] || continue
        [[ -n "${(P)_key-}" ]] && continue
        eval "export ${_line}"
    done < "$REPO_DIR/.env"
    unset _line _key
fi

VENV="$HOME/.venvs/sm-crm-system"
if [[ ! -d "$VENV" ]]; then
    VENV="$REPO_DIR/.venv"
fi
source "$VENV/bin/activate"
