#!/usr/bin/env bash
# Deploy a COMMITTED git ref to the Hetzner server. Run from your own machine.
#
#   scripts/deploy_hetzner.sh [--ref REF] [--build-web] [--force] [--dry-run]
#
#   --ref REF      git ref to deploy (default: the current branch)
#   --build-web    also rebuild the frontend image (needed only when files under
#                  services/dashboard/frontend/ changed; it is CPU-heavy)
#   --force        deploy even inside the danger window / while a run is active
#   --dry-run      run the safety checks and show what would happen; change nothing
#
# Why this exists: on 2026-09-29 a deploy overlapped the 22:00 UTC scheduled run.
# The Docker rebuild starved the 2-vCPU server, Gmail dropped the IMAP connection
# and the run processed 2 emails instead of ~50 (RUNBOOK.md §4c, progress.md). So
# this script REFUSES to deploy while a run is likely executing:
#   * the scheduler fires at even UTC hours (00:00, 02:00, ...) and a run takes up
#     to ~6 minutes, so :00-:11 of an even hour is treated as unsafe, and
#   * a fresh tmp/process.lock on the server means a run is active right now.
#
# Only tracked files are copied (git archive), so .env, .env.compose and
# config/gmail_*.json on the server are never touched. No secrets pass through
# this script. Override the target with HETZNER_HOST / HETZNER_KEY / HETZNER_SITE.
set -euo pipefail

HOST="${HETZNER_HOST:-root@2.29.47.89}"
KEY="${HETZNER_KEY:-$HOME/.ssh/hetzner_ai_inbox}"
SITE="${HETZNER_SITE:-https://2-29-47-89.nip.io}"
REMOTE_DIR="/opt/ai-inbox-manager"

# Minutes past an even UTC hour during which a scheduled run may still be executing.
UNSAFE_MINUTES=12

# Pure function (unit tested): succeeds (exit 0) when a scheduled run is likely
# executing at the given UTC hour and minute, i.e. deploying now is unsafe.
deploy_window_unsafe() {
  local hour=$((10#$1)) minute=$((10#$2))   # 10# so "08"/"09" aren't parsed as octal
  (( hour % 2 == 0 && minute < UNSAFE_MINUTES ))
}

usage() {
  sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

main() {
  local ref="" build_web=0 force=0 dry_run=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --ref)        ref="${2:?--ref needs a value}"; shift 2 ;;
      --build-web)  build_web=1; shift ;;
      --force)      force=1; shift ;;
      --dry-run)    dry_run=1; shift ;;
      -h|--help)    usage; return 0 ;;
      *)            echo "Unknown option: $1" >&2; usage >&2; return 2 ;;
    esac
  done

  [[ -n "$ref" ]] || ref="$(git rev-parse --abbrev-ref HEAD)"
  git rev-parse --verify --quiet "$ref^{commit}" >/dev/null \
    || { echo "ERROR: '$ref' is not a valid git ref" >&2; return 2; }
  local sha; sha="$(git rev-parse --short "$ref")"

  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "WARNING: you have uncommitted changes — only committed files in '$ref' are deployed."
  fi

  local ssh_cmd=(ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=15 "$HOST")

  # ── safety checks (read-only) ─────────────────────────────────────────────
  local now hour minute lock_active
  now="$("${ssh_cmd[@]}" 'date -u +"%H %M"')"
  read -r hour minute <<<"$now"
  lock_active="$("${ssh_cmd[@]}" "find $REMOTE_DIR/tmp/process.lock -mmin -30 2>/dev/null | wc -l" | tr -d ' ')"

  echo "Server time: ${hour}:${minute} UTC | run lock active: $([[ "$lock_active" -gt 0 ]] && echo yes || echo no)"
  echo "Deploying: $ref ($sha) -> $HOST:$REMOTE_DIR$([[ $build_web -eq 1 ]] && echo ' (+ rebuild web)')"

  local unsafe=""
  if deploy_window_unsafe "$hour" "$minute"; then
    unsafe="a scheduled run may be executing (even UTC hour, minute < $UNSAFE_MINUTES)"
  elif [[ "$lock_active" -gt 0 ]]; then
    unsafe="a pipeline run is active right now (tmp/process.lock is fresh)"
  fi
  if [[ -n "$unsafe" ]]; then
    if [[ $force -eq 1 ]]; then
      echo "WARNING: $unsafe — continuing because of --force."
    else
      echo "REFUSING to deploy: $unsafe." >&2
      echo "Wait a few minutes and retry (safe: :12-:59 of any hour, or any time in an odd hour)." >&2
      return 3
    fi
  fi

  if [[ $dry_run -eq 1 ]]; then
    echo "Dry run: checks passed, nothing deployed."
    return 0
  fi

  # ── deploy ────────────────────────────────────────────────────────────────
  git archive --format=tar "$ref" | "${ssh_cmd[@]}" "tar -x -C $REMOTE_DIR"

  "${ssh_cmd[@]}" bash -s -- "$REMOTE_DIR" "$build_web" "$sha" <<'REMOTE'
set -euo pipefail
dir="$1"; build_web="$2"; sha="$3"
cd "$dir"
chown -R 1000:1000 logs tmp config
chmod +x scripts/*.sh
echo "$sha $(date -u +%FT%TZ)" > .deployed_commit
cd services/dashboard
dc=(docker compose -f docker-compose.prod.yml --env-file .env.compose --profile scheduler)
if [[ "$build_web" == "1" ]]; then
  "${dc[@]}" up -d --build web 2>&1 | grep -E "Built|Recreated|Error|error TS" | sort -u || true
fi
"${dc[@]}" restart api >/dev/null 2>&1   # API code is bind-mounted; the cron picks up new code on its next run
status=starting
for _ in $(seq 1 20); do
  status="$(docker inspect -f '{{.State.Health.Status}}' inboxgenius-api-1)"
  [[ "$status" == "healthy" ]] && break
  sleep 3
done
echo "api health: $status"
"${dc[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
REMOTE

  echo "--- verifying $SITE"
  curl -fsS -m 20 "$SITE/health" && echo
  echo "Deployed $ref ($sha)."
}

# Run main only when executed, not when sourced (the unit tests source this file).
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
