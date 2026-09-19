# Starts the dashboard against the cloud (Neon) database -- no local
# Postgres, no local cron. Requires NEON_DATABASE_URL set in the repo root .env.
#
# Usage: .\view-dashboard.ps1
# Stop with Ctrl+C; nothing needs to keep running between visits.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
docker compose -f docker-compose.viewer.yml --env-file ../../.env up
