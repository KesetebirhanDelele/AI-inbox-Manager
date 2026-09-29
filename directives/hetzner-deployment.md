# Directive: Hetzner Deployment

## Goal
Run the whole InboxGenius system (Postgres, dashboard API, dashboard frontend, and
the 2-hourly inbox pipeline) on one Hetzner Cloud server with Docker Compose,
replacing Render + Vercel + Neon + the GitHub Actions cron. The current cloud
system (RUNBOOK.md §1–§4) **stays live until the Hetzner system is verified**.

## Inputs
- Server: Hetzner Cloud `CPX22` (2 vCPU / 4 GB / 80 GB), Ubuntu, Helsinki. IPv4 `2.29.47.89`.
- Public hostname: `2-29-47-89.nip.io` (free wildcard DNS → the IP). A real domain
  can replace it later by changing `SITE_HOST` and rebuilding the `web` image.
- Cloud firewall: inbound TCP 22, 80, 443 only; outbound unrestricted.
- SSH: key `~/.ssh/hetzner_ai_inbox` (no passphrase), `root@2.29.47.89`.
- A copy of the local root `.env` (pipeline secrets) and `config/gmail_*.json`.

## Files (all in this repo)
| File | Role |
|---|---|
| `services/dashboard/docker-compose.prod.yml` | the stack: `postgres`, `api`, `web`, `cron` |
| `services/dashboard/api/Dockerfile.server` | API image (deps only; code bind-mounted at `/repo`) |
| `services/dashboard/frontend/Dockerfile.prod` + `Caddyfile` | frontend build + Caddy (HTTPS, reverse proxy) |
| `execution/Dockerfile.cron.server` + `crontab.server` | scheduler image, `0 */2 * * *` UTC |
| `scripts/hetzner_init_secrets.sh` | one-time secret generation (never prints values) |
| `scripts/backup_postgres.sh` | optional manual Postgres dump (not scheduled — see step 6) |
| `services/dashboard/compose.env.example` | template for the gitignored `.env.compose` |

## Steps
1. **Server prep** — install Docker + Compose plugin, add swap, clone the repo to
   `/opt/ai-inbox-manager`, `chown` `logs/ tmp/ config/` to uid 1000.
2. **Secrets** — `scp` the local `.env` to the server as `incoming.env`, then run
   `scripts/hetzner_init_secrets.sh incoming.env 2-29-47-89.nip.io`. Copy
   `config/gmail_token.json` and `gmail_credentials.json` into `config/`
   (create `config/service-account-key.json` containing `{}` if unused, matching
   the workflow). `HETZNER_API_KEY` and `NEON_DATABASE_URL` are never copied into `.env`.
3. **Data** — `pg_dump` Neon → restore into the container with
   `--no-owner --no-privileges`; compare per-table row counts.
4. **Start (no scheduler)** — `docker compose -f docker-compose.prod.yml --env-file .env.compose up -d --build`.
   Verify `https://2-29-47-89.nip.io/health` and log in.
5. **Cutover** — disable `process_inbox.yml` and `keepalive.yml` in GitHub,
   then `docker compose ... --profile scheduler up -d cron`. Manually trigger one
   run and confirm a `ProcessRun` row appears.
6. **Backups** — none scheduled (owner decision 2026-09-29: no Hetzner server
   backups; emails stay in Gmail and the DB is dashboard history). A daily-dump
   cron was installed and then removed the same evening. To take a dump on
   demand run `scripts/backup_postgres.sh`; to schedule it, add
   `30 3 * * * root /opt/ai-inbox-manager/scripts/backup_postgres.sh` to
   `/etc/cron.d/inboxgenius-backup`. Note dumps contain email data and sit on
   the same server as the database.
7. **Harden** — done 2026-09-29: `/etc/ssh/sshd_config.d/01-hardening.conf`
   (key-only, MaxAuthTries 3, no X11), `fail2ban` sshd jail; unattended-upgrades
   was already active. Verify with a *fresh* SSH connection and a refused
   password attempt (see the `vps-hardening` skill).

## Optional settings
- `DB_STORAGE_CAP_MB` (root `.env`): cap for the dashboard's storage card.
  Default 512 (Neon free tier); the Hetzner server uses 40960.
- `MAX_EMAILS_PER_RUN` (root `.env`): emails fetched per pipeline run. Default
  100; the Hetzner server uses 150. Shown read-only on the dashboard Settings
  page. The run interval is the cron line in `execution/crontab.server`
  (change it there and rebuild the `cron` image); it is not editable in the UI.

## Safety constraints
- **Never** run the GitHub Actions cron and the Hetzner `cron` service at the same
  time — both process the same mailbox. The `cron` service is behind the
  `scheduler` compose profile so a plain `up` cannot start it.
- Postgres has **no published port**; only the `web` service publishes 80/443.
  (Docker bypasses host `ufw`; the Hetzner cloud firewall is the outer control.)
- **Never print secrets.** No `cat .env`, `printenv`, `docker compose config`
  (expands variables) or `docker inspect` env output on the server. Check presence
  only (`wc -c`, `grep -c`).
- Change the default `admin` / `admin123` login before exposing anything —
  `hetzner_init_secrets.sh` generates a new admin password.
- Roll back by re-enabling the GitHub workflow and stopping the Hetzner `cron`
  service; Neon is untouched until the old system is deliberately retired.

## Edge cases / learnings
- The login cookie is `secure=True, samesite=none`, so HTTPS is mandatory; the
  frontend and API share one origin (Caddy), and `CORS_ORIGINS` is set to it.
- nip.io is a shared domain, so Let's Encrypt rate limits can refuse a cert;
  Caddy automatically falls back to ZeroSSL. If both fail, use a real domain.
- `docker compose` reads `.env.compose` only for `POSTGRES_PASSWORD` / `SITE_HOST`;
  everything else is read by python-dotenv from the repo-root `.env`. The bcrypt
  admin hash contains `$`, so it is single-quoted in `.env`.
- Files written by the cron job (`logs/`, `tmp/`, `config/gmail_token.json`) must
  be owned by uid 1000, the same user as the API container, or the run lock and
  token refresh break.
