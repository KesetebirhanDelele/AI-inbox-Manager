# Email Management Dashboard

Web dashboard for the InboxGenius email pipeline: what the pipeline sorted, interview
requests and student-notification drafts to approve, run history and reports.

**Production** runs on a single Hetzner server — https://2-29-47-89.nip.io. How it is
deployed, operated and debugged is in [`../../RUNBOOK.md`](../../RUNBOOK.md) §4c
(live infrastructure, commands, failure playbook) and
[`../../directives/hetzner-deployment.md`](../../directives/hetzner-deployment.md).
This README is only about the code in this folder. (The earlier Render/Vercel/Neon
deployment is a frozen fallback until it is retired; see RUNBOOK §1.)

## What's here

| Path | What |
|---|---|
| `api/` | FastAPI backend (`main.py`, `routers/`, `models.py`, `auth.py`). Routes live under `/api/...`; `/health` is unauthenticated. |
| `frontend/` | React 18 + TypeScript + Vite + Tailwind. Pages: Dashboard, Interviews, Interview Events report, Reports, Review (queue + notification drafts), Settings (read-only schedule + whitelist). |
| `tests/` | Backend tests (pytest). |
| `docker-compose.yml` | Local development stack (Postgres, API, Vite dev server, cron). |
| `docker-compose.viewer.yml` + `view-dashboard.sh/.ps1` | Just API + frontend, pointed at a remote database (ports 5174/8011). |
| `docker-compose.prod.yml` | The production stack (Postgres, API, Caddy-served frontend, cron). Server only. |

## Run it locally

```bash
cd services/dashboard
docker compose up -d          # API http://localhost:8010, frontend http://localhost:5173
```

The local compose file has a dev-only login (`admin` / `admin123`) — never reuse it
anywhere reachable from the internet. The pipeline itself is `execution/`
(see `../../directives/`); the dashboard only reads what it writes.

## Run the tests

```bash
pip install -r api/requirements.txt -r api/requirements-dev.txt
python -m pytest services/dashboard/tests        # from the repo root
```

Repo-wide: `python -m pytest` (18 tests in `tests/execution/test_log_interview.py`
fail on a known, unrelated import problem — see `../../progress.md`).

## Configuration (environment variables)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres URL (falls back to local SQLite for quick dev) |
| `SESSION_SECRET` | Required when `ENVIRONMENT=production` |
| `ADMIN_PASSWORD_HASH` | bcrypt hash of the admin password |
| `STAKEHOLDER_PASSWORD_HASH` | bcrypt hash for the "stakeholder" login. **The role is only a label today — no endpoint enforces view-only** (see `../../progress.md`). |
| `CORS_ORIGINS` | Comma-separated allowed origins (production is same-origin behind Caddy) |
| `DB_STORAGE_CAP_MB` | Cap for the dashboard's "Database Storage" card (default 512) |
| `MAX_EMAILS_PER_RUN` | Per-run email cap; shown read-only on the Settings page (default 100; production uses 150) |

Notes:
- The login cookie is `secure` + `SameSite=None`, so the API only works over HTTPS
  (or `localhost`).
- The processing schedule is **not** editable from the UI: it is the cron line in
  `execution/crontab.server`. "Run Now" is disabled in production by design.
- Never commit real credentials; secrets are generated on the server
  (`../../scripts/hetzner_init_secrets.sh`).
