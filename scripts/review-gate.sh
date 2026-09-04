#!/usr/bin/env zsh
# Phase 13A S1 §5.2 — the SM-CRM review gate, running on the Mac mini.
#
# CRM_REVIEW_REQUIRED=true means nothing reaches Twenty without a human
# approving it first, and the approval surface is the review UI. That surface is
# host-coupled and always-on, so launchd is its scheduler of record
# (980labsOS docs/standards/recurring-job-routing.md). Loaded by
# scripts/launchd/com.stablemischief.smcrm-reviewgate.plist.
#
# Secrets: rendered by the 980labsOS 8D Infisical Agent and injected for exactly
# one child process by with-8d-env.sh. This script re-execs itself through that
# wrapper when it can find it. There is no .env on the mini and none should ever
# be created there — python-dotenv's load_dotenv() does not override values that
# are already in the environment, so the wrapper path is the supported one.
set -euo pipefail

WRAPPER="${SM_CRM_ENV_WRAPPER:-$HOME/Documents/GitHub/980labsOS-deploy/scripts/with-8d-env.sh}"

if [[ -z "${SM_CRM_ENV_WRAPPED:-}" && -x "$WRAPPER" ]]; then
    export SM_CRM_ENV_WRAPPED=1
    exec "$WRAPPER" -- "${0:A}" "$@"
fi

exec "${0:A:h}/serve-review-ui.sh" "$@"
