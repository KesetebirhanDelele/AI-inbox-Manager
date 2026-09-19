#!/usr/bin/env bash
# Starts the dashboard against the cloud (Neon) database -- no local
# Postgres, no local cron. Requires NEON_DATABASE_URL set in the repo root .env.
#
# Usage: ./view-dashboard.sh
# Stop with Ctrl+C; nothing needs to keep running between visits.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
docker compose -f docker-compose.viewer.yml --env-file ../../.env up
