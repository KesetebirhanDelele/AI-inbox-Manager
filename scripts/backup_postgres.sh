#!/usr/bin/env bash
# Daily Postgres backup for the Hetzner stack. Run ON THE SERVER (host cron).
# Replaces .github/workflows/backup_neon_db.yml once Neon is retired.
#
#   BACKUP_DIR (default /opt/backups/inboxgenius)   KEEP_DAYS (default 30)
#
# Dumps are gzipped SQL, chmod 600. The script fails (non-zero exit) if the dump
# is empty, so a broken backup is never silently kept.
set -euo pipefail
umask 077

BACKUP_DIR="${BACKUP_DIR:-/opt/backups/inboxgenius}"
KEEP_DAYS="${KEEP_DAYS:-30}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$REPO_ROOT/services/dashboard/docker-compose.prod.yml" \
         --env-file "$REPO_ROOT/services/dashboard/.env.compose")

mkdir -p "$BACKUP_DIR"
OUT="$BACKUP_DIR/inboxgenius_$(date -u +%Y%m%dT%H%M%SZ).sql.gz"

"${COMPOSE[@]}" exec -T postgres pg_dump -U inboxgenius --no-owner --no-privileges inboxgenius \
  | gzip > "$OUT"

# gzip of empty input is ~20 bytes; a real dump is far larger.
if [ "$(stat -c %s "$OUT")" -lt 1000 ]; then
  echo "ERROR: backup $OUT is suspiciously small; removing" >&2
  rm -f "$OUT"
  exit 1
fi

find "$BACKUP_DIR" -name 'inboxgenius_*.sql.gz' -mtime +"$KEEP_DAYS" -delete
echo "Backup written: $OUT ($(du -h "$OUT" | cut -f1))"
