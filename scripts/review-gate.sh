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
# wrapper. There is no .env on the mini and none should ever be created there —
# scripts/_repo-env.sh merges .env only at the lowest precedence, so injected
# values always win where a dev machine does have one.
#
# Two things here are deliberately hard failures rather than fallthroughs. A
# human-approval gate that comes up green while pointed at a mock CRM is worse
# than one that refuses to start: the operator approves records believing they
# are gating writes to Twenty, and nothing tells them otherwise.
set -euo pipefail

REPO_DIR="${0:A:h:h}"

# launchd creates the log FILE but not intermediate directories, and StandardOut
# /StandardErrorPath both live under here. Without this, a failing start on a
# fresh host respawns every ThrottleInterval with both streams going nowhere —
# exactly when the log is needed.
LOG_DIR="${SM_CRM_LOG_DIR:-$HOME/.980labsOS/smcrm}"
mkdir -p "$LOG_DIR"

WRAPPER="${SM_CRM_ENV_WRAPPER:-$HOME/Documents/GitHub/980labsOS-deploy/scripts/with-8d-env.sh}"

if [[ -z "${SM_CRM_ENV_WRAPPED:-}" ]]; then
    if [[ ! -x "$WRAPPER" ]]; then
        print -u2 -- "review-gate: refusing to start — the 8D env wrapper is not executable at:"
        print -u2 -- "  $WRAPPER"
        print -u2 -- "Without it no Twenty credentials are injected and the gate would come up"
        print -u2 -- "backed by the mock CRM, so approvals would gate nothing. Fix the path (or set"
        print -u2 -- "SM_CRM_ENV_WRAPPER), or set SM_CRM_ENV_WRAPPED=1 to supply the environment"
        print -u2 -- "yourself on a dev machine."
        exit 78
    fi
    export SM_CRM_ENV_WRAPPED=1
    exec "$WRAPPER" -- "${0:A}" "$@"
fi

source "${0:A:h}/_repo-env.sh"

if [[ -z "${TWENTY_API_KEY:-}" ]]; then
    print -u2 -- "review-gate: refusing to start — TWENTY_API_KEY is empty."
    print -u2 -- "load_settings() would fall back to the mock CRM and the gate would look healthy"
    print -u2 -- "on 127.0.0.1:8765 while approving nothing into Twenty."
    exit 78
fi

exec "${0:A:h}/serve-review-ui.sh" "$@"
