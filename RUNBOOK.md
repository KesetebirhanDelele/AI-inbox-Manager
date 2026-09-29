# InboxGenius — Operations Runbook & Current Architecture

> **This is the single source of truth for how the system is deployed and runs today.**
> If you are an AI agent (or a new engineer) debugging a production issue, **read this
> file first**, then run the checks in [§14 "Verify this doc is still current"](#14-verify-this-doc-is-still-current)
> before trusting any older notes, chat history, or memory.
>
> **Last verified: 2026-09-29** — cron offset changed to dodge GitHub's
> top-of-hour scheduling congestion (§16).

---

## 0. TL;DR — what changed from older docs

Earlier versions of this runbook (and stale chat sessions) describe infrastructure
that **is no longer in use**. Current reality:

| Thing | ❌ OLD (ignore) | ✅ CURRENT |
|---|---|---|
| Scheduler | Windows Task Scheduler on a laptop | **GitHub Actions cron**, cloud, laptop-independent |
| Backend host | Railway | **Render** (Docker web service) |
| Database | Railway PostgreSQL | **Neon PostgreSQL** (free tier, never expires) |
| Backend URL | `inboxgenius-api-production.up.railway.app` | `https://ai-inbox-manager-5l6p.onrender.com` |
| "Laptop must be on" | true | **false** — everything runs in the cloud |
| Student notifications | auto-emailed by the cron | **draft → human approval** in the dashboard |
| Classifier model | (unclear) | `gpt-4o-mini` (see [§11](#11-cost)) |

The frontend URL (`https://ai-inbox-manager-vert.vercel.app`) and the Gmail
account (`c_interviews@colaberry.com`) are unchanged.

**Fork note:** this repo (`KesetebirhanDelele/AI-inbox-Manager`) runs its own
independent pipeline — its own GitHub Actions cron, its own secrets, and its
own dedicated Neon Postgres project (`inboxgenius-fork`). It also has a
**separate local Docker environment** against the same Gmail mailbox — see
[§4b](#4b-this-forks-local-docker-environment). This fork does not read from,
write to, or depend on any other GitHub repo, Render service, or database.
**Push policy:** all commits, branches, and PRs for this project stay within
this repo (permanent rule).

---

## 1. Live URLs & accounts

| Component | URL / location |
|---|---|
| **Dashboard (frontend)** | https://ai-inbox-manager-vert.vercel.app — Vercel, auto-deploys from `master` |
| **Backend API** | https://ai-inbox-manager-5l6p.onrender.com — Render Docker web service `inboxgenius-api` |
| **API health** | https://ai-inbox-manager-5l6p.onrender.com/health → `{"status":"healthy","database":"connected"}` |
| **API docs (OpenAPI)** | https://ai-inbox-manager-5l6p.onrender.com/docs |
| **Database** | Neon PostgreSQL — host `ep-super-shadow-aqsoxad0.c-8.us-east-1.aws.neon.tech`, db `neondb` |
| **Scheduler / CI** | https://github.com/KesetebirhanDelele/AI-inbox-Manager/actions |
| **Git repo** | https://github.com/KesetebirhanDelele/AI-inbox-Manager (branch: `master`) |
| **Monitored mailbox** | `c_interviews@colaberry.com` (Gmail, IMAP + SMTP) |
| **Google Sheet audit log** | id in `GOOGLE_SHEET_ID` secret |

**Dashboard logins:** `admin` / `admin123` (full), stakeholder account view-only.
Passwords are bcrypt hashes in Render env vars `ADMIN_PASSWORD_HASH` /
`STAKEHOLDER_PASSWORD_HASH`.

---

## 2. Architecture (Agent-First, Deterministic-Execution — see `CLAUDE.md`)

```
Layer 1  /directives          Human-readable SOPs. Claude reads before acting.
Layer 2  Claude / engineer    Plans & edits. Never runs business logic itself.
Layer 3  /execution           Deterministic Python scripts — the actual work.
         .github/workflows     "The worker": GH Actions runs Layer 3 on a schedule.
Dashboard services/dashboard   React (Vercel) + FastAPI (Render) + Neon, read-mostly view.
```

The **cron running `execution/process_inbox_auto.py` every 2 h is the production
system.** The dashboard only *reads* what that script writes (plus a human
approval queue for student notifications).

---

## 3. The processing pipeline — what one run does

Entry point: `python execution/process_inbox_auto.py`
(function `process_unread_emails()` in that file).

1. **Acquire run-lock** (`execution/run_lock.py`, lock at `tmp/process.lock`) — no
   overlapping runs.
2. **Spam-review 2nd pass** (`_run_spam_review_pass`): fetch everything in the
   `Spam Review` Gmail folder (≤50), re-classify each:
   - still `Other` / confidence < 0.70 / flagged spam → **permanently deleted**
     (`delete_emails`, UID-scoped `UID EXPUNGE`)
   - turns out legit → **rescued** to its real category folder
3. **Fetch INBOX**: `UNSEEN` only, **newest-first**, capped at
   `MAX_EMAILS_PER_RUN` (default **100**). Handles are **IMAP UIDs**.
4. **Pre-run budget check**: abort before any API call if
   `len(emails) × ~$0.015 > MAX_COST_PER_RUN_USD` (default `5.0`).
   ⚠️ that per-email estimate uses gpt-4o pricing but the model is gpt-4o-mini —
   it over-estimates ~17× (see [§15](#15-known-issues--deferred-work)).
5. **Classify** (16 parallel workers):
   - `pre_classify_by_sender()` — deterministic sender-domain rules, **no AI call**
     for obvious senders (LinkedIn, Indeed, etc.)
   - else `classify_email()` → OpenAI **`gpt-4o-mini`** → category + confidence +
     extracted fields + edge-case flags
6. **Post-classification cost check**: if actual token cost > limit, DB writes
   still happen but **all Gmail moves/deletes are skipped** this run.
7. **Apply actions** (sequential) per email:
   - **Genuine interview request** OR **sender/company in `KNOWN_INTERVIEW_COMPANIES`**
     → **kept in INBOX, untouched**. Imported to DB; `process_interview_email()`
     runs: sub-classify → create `InterviewEvent` → resolve student from
     `config/students.py` → create a **`NotificationDraft`** (NOT auto-sent).
   - **`Other`** → quarantine: apply label `Spam Review`, remove from inbox,
     import to DB.
   - **Everything else** → organize: `CATEGORY_TO_FOLDER` map; if confidence <
     `ROUTING_CONFIDENCE_THRESHOLD` (0.70) or category unmapped → `Needs Review`;
     else the mapped folder.
8. **Move** (`fetch_emails.move_emails`): for each message, `STORE +X-GM-LABELS
   "<folder>"` then `STORE -X-GM-LABELS \Inbox`, addressed by **UID**, with
   **Message-ID re-resolution** if a UID has shifted. No COPY / `\Deleted` /
   `expunge()` in this path — it cannot delete mail.
9. **Google Sheets** audit log (filtered subset of categories).
10. **SharePoint** audit log (if configured; usually a no-op).
11. **`ProcessRun`** row written to Neon; `summary.json` saved under
    `tmp/auto_process_<ts>/`; logs uploaded as a GH Actions artifact
    (`inbox-logs-<run#>`, 7-day retention).
12. On fatal error: `send_failure_alert()` emails `ALERT_EMAIL_TO`. Script always
    `sys.exit(0)` so the scheduler reports success.
13. **DB writes are best-effort** — a DB failure never blocks Gmail processing.
    But if *any* DB write failed (engine init or `ProcessRun`), the first error
    is put in `stats["db_error"]` and `main()` logs `DASHBOARD DB WRITES FAILED`,
    emits a GitHub Actions `::error::` annotation (visible on the run page; the
    job itself stays green) and sends a `send_failure_alert()` email.
    `DATABASE_URL` is passed through `execution/db_url.normalize_db_url()`, which
    pins `postgresql://` → `postgresql+psycopg2://` (see §16 2026-09-25).

**Categories → Gmail folders/labels:** see `CATEGORY_TO_FOLDER` in
`execution/process_inbox_auto.py` (~line 584). All flat label names.
**Confidence threshold:** `ROUTING_CONFIDENCE_THRESHOLD = 0.70`.

---

## 4. Scheduling & GitHub Actions workflows

| Workflow | Trigger | What it does |
|---|---|---|
| `.github/workflows/process_inbox.yml` | cron `0 */2 * * *` (every 2 h UTC) + manual `workflow_dispatch` | Installs deps, writes `.env` + `config/*.json` from secrets, runs `process_inbox_auto.py`, refreshes the `GMAIL_TOKEN_JSON` secret with the rotated token, uploads logs. `timeout-minutes: 30`. |
| `.github/workflows/keepalive.yml` | cron `17 6 * * 1` (Mon 06:17 UTC) + manual | Pushes one empty `chore: keepalive [skip ci]` commit/week so GitHub never auto-disables the cron (it did on ~2026-08-25 after 60 days idle). |
| `.github/workflows/deploy_backend.yml` | push to `master` touching `services/dashboard/api/**`, `execution/**`, or `config/**` + manual | `curl`s the Render deploy hook (`RENDER_DEPLOY_HOOK_URL` secret). |

**Frontend deploy:** Vercel watches `master` and rebuilds
`services/dashboard/frontend/` automatically. Prod API URL is baked in via
`services/dashboard/frontend/.env.production`
(`VITE_API_BASE_URL=https://ai-inbox-manager-5l6p.onrender.com`).

**Local Windows Task Scheduler** job `ColaberryEmailProcessing` — **DISABLED on
purpose.** Re-enable only if the cloud cron dies. `InboxAI_StartAPI_OnLogon`
(starts a local API on logon) is harmless and still active.

---

## 4b. This fork's local Docker environment

`KesetebirhanDelele/AI-inbox-Manager` (this fork) also runs a **fully local,
self-contained** Docker Compose stack — `services/dashboard/docker-compose.yml`
— as an independent alternative to §1–§4's cloud production system, against the
same Gmail mailbox. It does **not** touch Render, Vercel, Neon, or GitHub
Actions; everything lives in four containers:

| Container | Role |
|---|---|
| `email_dashboard_db` | Postgres 16, local-only data (own DB, not Neon) |
| `email_dashboard_api` | FastAPI dashboard backend, `services/dashboard/api/Dockerfile.dev`, host port 8010 |
| `email_dashboard_frontend` | Vite dev server, host port 5173 |
| `email_dashboard_cron` | Local replacement for `.github/workflows/process_inbox.yml`'s cron trigger |

**Scheduler:** `execution/Dockerfile.cron` + `execution/crontab`, same cadence
as production — `0 */2 * * *` (every 2 h UTC). The container's PID 1 is
`cron -f` (foreground) directly; the crontab job runs
`process_inbox_auto.py`, redirecting its own output to `/repo/logs/cron.log`
via the crontab line's `>>` redirect.

⚠️ **2026-09-18 incident + fix:** the CMD used to be
`cron && tail -f /repo/logs/cron.log` — plain `cron` daemonizes and detaches,
so the shell's `&&` chain handed PID 1 to `tail -f` watching the bind-mounted
log file. That `tail -f` hit `No data available` (a WSL2/Docker Desktop
filesystem-bridge hiccup on the Windows-host bind mount) and exited, which
killed PID 1 and the whole container — including whatever pipeline run was
mid-flight — restart policy silently relaunched it, but the run itself was
lost uncleanly. Fixed by making `cron -f` PID 1 directly (`exec cron -f`, no
`tail -f`), since it never touches the bind-mounted log itself. Verified: a
full 2 h cycle completed unattended afterward with zero container restarts.

**Countdown timer caveat:** the dashboard's "Next run in" countdown
(`services/dashboard/frontend/src/hooks/useCountdownTimer.ts`) computes the
next fire time from a **fixed UTC clock boundary**
(`Math.ceil(now / intervalMs) * intervalMs`), matching the crontab's
`0 */2 * * *` schedule — it does **not** anchor off the last `ProcessRun`
timestamp. An earlier version anchored off `last_run_timestamp`, which meant
every manual "Run Now" click (which also writes a `ProcessRun` row) silently
dragged the countdown away from the real fixed schedule.

**Known disconnect:** the dashboard Settings page lets you change
`interval_minutes` / `batch_size` (`SystemConfig` table, `api/routers/schedule.py`),
but for this fork those values are cosmetic only — `execution/crontab` is a
static file baked into the `email_dashboard_cron` image at build time and does
**not** read `SystemConfig`. Changing Settings today does not reschedule
anything. (That control's "update the Windows scheduled task" code path is
also vestigial — this fork uses the Docker cron container, not Task
Scheduler.) Not fixed as of this writing; see [§15](#15-known-issues--deferred-work).

**Update — 2026-09-18/19, migration completed:** the "in-progress" framing
above is now done. This fork's actual production scheduler is **this fork's
own GitHub Actions** (`.github/workflows/process_inbox.yml`, re-enabled with
its own secrets, fully self-contained),
writing to a dedicated **Neon Postgres project** (`inboxgenius-fork`, free
tier, 0.5 GB cap). Verified: multiple full unattended scheduled runs
completed cleanly with `ProcessRun` rows landing in Neon and zero manual
intervention. The local Docker `cron` container is **stopped** (not
removed — `docker start email_dashboard_cron` brings it back) to avoid
double-processing against GitHub Actions on the same `0 */2 * * *` schedule.
Rollback point if this ever needs reverting: git tag
`pre-cloud-migration-2026-09-18`.

**Neon storage countdown:** the local dashboard (`view-dashboard.sh`) shows
a "Neon Storage Left" card (Engineering KPIs row) — days-remaining estimate
computed from actual DB growth rate (`GET /api/stats/engineering-kpis`,
`db_storage_*` fields), so the 0.5 GB free-tier cap doesn't run out silently.
Hitting the cap blocks new writes but does **not** interrupt email
processing itself (all DB writes in `process_inbox_auto.py` are
best-effort/non-fatal) — only dashboard visibility would go stale.

**Backup:** Neon's free tier only gives a 6-hour point-in-time-recovery
window and one manual snapshot (no scheduled ones) — thin for an unattended
system nobody's watching in real time. `.github/workflows/backup_neon_db.yml`
runs a daily `pg_dump` (06:00 UTC) and keeps 30 days of gzipped dumps as
workflow artifacts, independent of Neon's own retention.

**Health checks (local only):**
```bash
# Is the cron daemon PID 1 (no tail -f in the mix)?
docker exec email_dashboard_cron sh -c "cat /proc/1/cmdline | tr '\0' ' '"

# Container restart count (0 = healthy since last rebuild)
docker inspect email_dashboard_cron --format 'RestartCount={{.RestartCount}}'

# Tail the actual pipeline log
docker exec email_dashboard_cron tail -n 60 /repo/logs/cron.log

# Manual run (bypasses the 2h wait)
docker exec -w /repo email_dashboard_cron python execution/process_inbox_auto.py --triggered-by manual
```

**In-progress migration (2026-09-18):** moving the scheduler off this laptop
entirely to GitHub Actions on this fork + a dedicated Neon Postgres (see
[§16 changelog](#16-changelog-infra--architecture-only) once that lands),
because this local Docker setup turned out to have a second, worse reliability
problem beyond the `tail -f` bug: Docker Desktop's **Resource Saver**
auto-pauses the whole container VM after just 30s of Docker-API inactivity
(`autoPauseTimeoutSeconds` in Docker Desktop's `settings.json`), silently
freezing `cron`'s clock through any scheduled fire that happens while nobody's
run a `docker` command recently. Neither more container fixes nor Windows
Task Scheduler solve this class of problem — both still depend on this
laptop/Docker Desktop being awake, which a 2-hour unattended schedule can't
assume. GitHub Actions runners are cloud-side and immune to both this and
laptop sleep.

Once that migration is live, the four-container stack above (`postgres` +
`cron` especially) is only needed for **local pipeline development** (testing
a code change before pushing) — not for production scheduling. A separate,
lightweight `docker-compose.viewer.yml` (plus `view-dashboard.ps1` /
`view-dashboard.sh` wrappers) starts just `api` + `frontend` against the
shared Neon database, so you can look at the dashboard without running
Postgres or cron locally at all:
```bash
# services/dashboard/ -- requires NEON_DATABASE_URL set in the repo root .env
# (kept separate from the local DATABASE_URL key, which local manual/cron
# runs still use against local Postgres)
./view-dashboard.sh          # or view-dashboard.ps1 on Windows
```
Runs on **5174/8011** (not 5173/8010, the main stack's ports) so both stacks
can run side by side without a port collision. Open http://localhost:5174.

---

## 4c. Hetzner deployment — CUT OVER 2026-09-29 (pending first scheduled-run check)

> **Status (2026-09-29 18:46 UTC): the Hetzner server is now the live scheduler
> and database.** All four GitHub workflows (`process_inbox`, `keepalive`, `backup_neon_db`,
> `deploy_backend`) are **disabled** (re-enable with `gh workflow enable <name>`). A manual run on the server succeeded (52 emails, 38
> moved, `ProcessRun` #133 written). **Not yet confirmed:** the first
> *scheduled* run at the top of an even UTC hour, and this runbook's §0–§4, §8, §10
> and §12 still describe the old GitHub/Render/Neon setup — they will be
> rewritten once a scheduled run is confirmed. Render, Vercel and Neon are still
> up, unchanged, as a fallback (Neon is frozen at 2026-09-29 18:44 UTC).

Target: one Hetzner Cloud server (CPX22, Helsinki, `2.29.47.89`, public hostname
`2-29-47-89.nip.io`, cloud firewall = inbound 22/80/443 only) running
`services/dashboard/docker-compose.prod.yml`: Postgres 18 (internal only), the
FastAPI API, a Caddy-served frontend with automatic HTTPS, and the 2-hourly
pipeline cron (`execution/crontab.server`, behind the `scheduler` compose
profile). It replaces Render + Vercel + Neon + the GitHub Actions cron, mainly to
fix GitHub's scheduler lateness (§16, 2026-09-29) and to give the dashboard a
public URL. Step-by-step SOP and safety constraints:
[`directives/hetzner-deployment.md`](directives/hetzner-deployment.md).

**Never run the GitHub Actions cron and the Hetzner `cron` service at the same
time** — both process the same mailbox.

---

## 5. Data stores

| Store | Holds | Notes |
|---|---|---|
| **Gmail labels/folders** | the actual sorted result the assistant sees | source of truth for "where is this email" |
| **Neon PostgreSQL** (`neondb`) | `emails`, `classifications`, `process_runs`, `interview_events`, `notification_drafts`, `students`, approvals, checklist… | powers the dashboard. Dedup key = RFC 5322 `Message-ID` (`emails.message_id` UNIQUE). `_ensure_schema()` in `process_inbox_auto.py` auto-migrates on run. |
| **Google Sheet** | flat human-readable audit log | filtered; failures are non-blocking |
| **GH Actions artifacts** | per-run `logs/` | 7-day retention |
| `tmp/auto_process_<ts>/summary.json` | per-run stats | local/CI only, disposable |

**Connection string** lives in the `DATABASE_URL` GitHub secret (processing) and
the `DATABASE_URL` Render env var (API). Both point at the same Neon external URL
(`...neon.tech/neondb?sslmode=require`).

---

## 6. Frontend UI

`services/dashboard/frontend/` — **React 18 + TypeScript + Vite 5**, routing via
`react-router-dom` 6, charts via `recharts`, HTTP via `axios`
(`src/api/client.ts`, base URL from `VITE_API_BASE_URL`). Cookie-session auth
(`/api/auth/login` sets a cookie; there is no bearer token).

| Route | Page component | Purpose |
|---|---|---|
| `/login` | `LoginPage.tsx` | admin / stakeholder login |
| `/` | `DashboardPage.tsx` | stats, category chart, volume trends, countdown to next interview |
| `/interviews` | `InterviewsPage.tsx` | interview requests & events |
| `/interview-events` | `InterviewEventsReportPage.tsx` | interview-events report |
| `/reports` | `ReportsPage.tsx` | analytics tabs (accuracy, categories, hourly volume, company tracker, engineering KPIs) |
| `/review` | `ReviewPage.tsx` | `Needs Review` queue + pending **notification drafts** to approve/edit/reject |
| `/settings` | `SettingsPage.tsx` | schedule config, thresholds |

Shared shell: `components/Layout.tsx`. Other components: `ApprovalsContent`,
`InboxContent`, `InterviewChecklist`, `CountdownTimer`, `ErrorBoundary`.

---

## 7. Backend API

`services/dashboard/api/` — **FastAPI**, `uvicorn main:app`, Python 3.11,
SQLAlchemy 2 + `psycopg2` → Neon. Deployed as a Render Docker web service
(`Dockerfile.prod`, non-root, healthcheck on `/health`, port 8000 → Render `$PORT`).
`render.yaml` documents the service; env vars with `sync: false` are set by hand
in the Render dashboard.

Routers (all under `/api`, see `main.py`): `auth`, `approvals`, `inbox`, `stats`,
`whitelist`, `emails`, `interviews`, `notifications`, `checklist`, `schedule`.
CORS `allow_origins` = `CORS_ORIGINS` env var (must exactly match the Vercel URL,
no trailing slash).

> **Manual move/delete from the dashboard is disabled in the cloud** —
> `services/dashboard/api/integration/email_actions.py` catches the missing IMAP
> libs and raises "IMAP actions not available in cloud deployment". All Gmail
> mutation happens in the cron.

---

## 8. Secrets & credentials

**Nothing secret is committed.** `.gitignore` covers `.env`, `config/gmail_token.json`,
`config/gmail_credentials.json`, `config/service-account-key.json`, `*.db`, `logs/`.

### GitHub repo secrets (this repo → Settings → Secrets → Actions)
`DATABASE_URL`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `EMAIL_SERVER`, `EMAIL_PORT`,
`OPENAI_API_KEY`, `SMTP_APP_PASSWORD`, `ALERT_EMAIL_TO`, `GOOGLE_SHEET_ID`,
`GMAIL_TOKEN_JSON` (base64, auto-refreshed each run), `GMAIL_CREDENTIALS_JSON`
(base64), `SERVICE_ACCOUNT_KEY_JSON` (base64), `RENDER_DEPLOY_HOOK_URL`,
`PAT_FOR_SECRETS` (PAT used to write `GMAIL_TOKEN_JSON` back).
`gh secret list` to enumerate.

### Render env vars (`inboxgenius-api` → Environment)
`DATABASE_URL`, `ENVIRONMENT=production`, `SESSION_SECRET`, `ADMIN_PASSWORD_HASH`,
`STAKEHOLDER_PASSWORD_HASH`, `CORS_ORIGINS`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD`,
`OPENAI_API_KEY`.

### Rotation

- **OpenAI key** — new key at platform.openai.com → update `OPENAI_API_KEY` in
  **both** the GitHub secret and the Render env var. (Charges bill to whichever
  OpenAI account owns the key — not necessarily the GitHub owner.)
- **Gmail OAuth** (`config/gmail_token.json`) — auto-refreshes via the stored
  refresh token; the cron writes the refreshed token back to `GMAIL_TOKEN_JSON`.
  Full re-auth only if Google revokes: `python scripts/authorize_gmail.py`, sign
  in as `c_interviews@colaberry.com`, then base64 the new
  `config/gmail_token.json` into the `GMAIL_TOKEN_JSON` secret.
- **DB** — rotate in Neon console, update `DATABASE_URL` in the GitHub secret and
  the Render env var.
- **Dashboard password** — `python -c "from services.dashboard.api.auth import
  hash_password; print(hash_password('newpw'))"` → paste hash into the Render env
  var → Render redeploys.

---

## 9. Safety mechanisms

- **Run-lock** — `tmp/process.lock`, no concurrent runs.
- **Known-interview-company protection** — `KNOWN_INTERVIEW_COMPANIES` set; a
  match on company / sender / subject forces "keep in INBOX" even if the AI
  misclassifies.
- **Confidence gate** — < 0.70 routes to `Needs Review`, never the target folder.
- **Two-pass spam** — `Other` is quarantined in `Spam Review`, only deleted after
  a second AI confirmation on the next run.
- **Cost guardrails** — pre-run estimate abort + post-run actual-cost skip of
  Gmail mutations. Env: `MAX_COST_PER_RUN_USD` (default 5.0).
- **Batch ceiling** — `MAX_EMAILS_PER_RUN` (default 100).
- **Label-only organize path** — cannot permanently delete mail; the only hard
  delete is the confirmed-spam purge, and it is UID-scoped (`UID EXPUNGE`), never
  a blind `expunge()`.
- **UID + Message-ID addressing** — moves/deletes can't hit the wrong message
  when sequence numbers shift (see changelog 2026-09-08).
- **Failure alerts** — `send_failure_alert()` → `ALERT_EMAIL_TO` on fatal errors
  / cost aborts / dashboard DB write failures.

---

## 10. Common operations

```bash
# --- Trigger a processing run now (instead of waiting for the 2h cron) ---
gh workflow run process_inbox.yml --ref master
gh run watch $(gh run list --workflow=process_inbox.yml -L1 --json databaseId -q '.[0].databaseId')

# --- Inspect the last runs / a run's log ---
gh run list --workflow=process_inbox.yml -L 10
gh run view <run-id> --log | grep -E "PROCESSING SUMMARY|Total Processed|Organized|Quarantined|Spam Review pass|Successfully moved|ERROR"

# --- Backend health ---
curl -s https://ai-inbox-manager-5l6p.onrender.com/health

# --- Deploy backend manually ---
gh workflow run deploy_backend.yml --ref master     # or: curl -X POST "$RENDER_DEPLOY_HOOK_URL"

# --- Run the test suite (315 tests) ---
python -m pytest -q                                 # or: scripts/test.sh  /  scripts\test.bat

# --- Local dev ---
#   backend:  cd services/dashboard/api && uvicorn main:app --port 8000
#   frontend: cd services/dashboard/frontend && npm run dev   (http://localhost:5173)
#   one processing run locally (needs root .env): python execution/process_inbox_auto.py --limit 10

# --- Lock recovery (only relevant for local runs) ---
cat tmp/process.lock            # PID + timestamp
rm tmp/process.lock             # if the PID is dead / lock > 3h old
```

---

## 11. Cost

- Model: **`gpt-4o-mini`** (`execution/classify_email.py`, `call_claude_api`
  default; `classify_email()` does not override it).
- Deterministic `pre_classify_by_sender()` skips the API entirely for many
  emails.
- Real spend ≈ **$0.10–0.15 per run** (~800k input + ~15k output tokens at
  gpt-4o-mini rates) → **~$1.50–2.00/day** across 12 runs.
- The **`estimated cost: $X` line in the logs over-states this ~17×** because
  `_compute_cost()` in `process_inbox_auto.py` hard-codes gpt-4o pricing
  ($2.50 / $10 per M) instead of gpt-4o-mini ($0.15 / $0.60 per M). Safe (fails
  toward aborting), but misleading — see [§15](#15-known-issues--deferred-work).
- Charges bill to the OpenAI account that owns the key in the `OPENAI_API_KEY`
  secret. Verify the account at platform.openai.com → Billing/Usage.

---

## 12. Failure playbook

| Symptom | First checks |
|---|---|
| **Dashboard shows 0 emails today but runs are green** | Run log: `grep -E "Could not initialize database|DB import skipped|DASHBOARD DB WRITES FAILED|ProcessRun record created"`. `No module named 'psycopg'` = SQLAlchemy driver mismatch (§16 2026-09-25) — check `pip` installed `sqlalchemy` version in the run log and that `normalize_db_url()` is still applied. Emails moved out of INBOX during the outage are **not** backfilled automatically; interview emails (kept UNSEEN in INBOX) self-heal on the next good run. |
| **Dashboard shows no / stale data** | `curl .../health` → is `database` `connected`? Is Render awake (cold start ≈ 20 s)? `gh run list` — are cron runs green? Check a run log for `Dashboard ProcessRun record created`. |
| **Emails not being sorted** | `gh run view <id> --log` → look for `Successfully moved N of N`, `Move: … skipping`, `BAD Could not parse command`. Check `Total Processed` vs inbox size. Confirm `EMAIL_PASSWORD` / Gmail OAuth still valid (`AUTHENTICATE failed` / `invalid_grant`). |
| **Cron not running at all** | GH Actions → is "Process Inbox" **disabled**? (re-enable; keepalive should prevent this). Check `keepalive` ran in the last week. |
| **Cost guardrail aborting** | Log shows `COST GUARDRAIL`. Real cost is ~17× lower than the estimate — usually safe to raise `MAX_COST_PER_RUN_USD` (GitHub secret / `.env`) or reduce inbox backlog. Fixing [§15](#15-known-issues--deferred-work) removes the false alarm. |
| **OpenAI errors** | status.openai.com for outage. `401` → rotate key ([§8](#8-secrets--credentials)). `429` → lower `MAX_EMAILS_PER_RUN`. Affected emails stay UNSEEN for next run. |
| **Gmail OAuth expired** | `python scripts/authorize_gmail.py` → re-base64 into `GMAIL_TOKEN_JSON`. SMTP alerts also fail during this window. |
| **Backend deploy failed** | GH Actions `Deploy Backend to Render` log; Render dashboard → `inboxgenius-api` → Events / Logs. |
| **Run crashed, lock stuck (local only)** | `rm tmp/process.lock` if PID dead or > 3 h old. |
| **`Spam Review` / `Needs Review` errors** | folder names must be quoted in IMAP — `_quote_folder()` in `fetch_emails.py` handles this; if it regresses you'll see `BAD Could not parse command`. |

---

## 13. Directives (Layer 1 SOPs)

`directives/email-integration.md` — IMAP fetch/move/delete rules (UID handling,
label ops, folder quoting — **step 7 is the authority on the move pipeline**).
`directives/email-classification.md` — categories & classification rules.
`directives/interview-processing.md` — interview sub-classification & notifications.

---

## 14. Verify this doc is still current

Run these; if any disagree with the above, **the doc is stale — update it**:

```bash
# Backend host & DB (expect onrender.com + "database":"connected")
curl -s https://ai-inbox-manager-5l6p.onrender.com/health

# Scheduler is the GH Actions cron, running & green
gh run list --workflow=process_inbox.yml -L 3

# Production entrypoint is still process_inbox_auto.py
grep -n "process_inbox_auto.py" .github/workflows/process_inbox.yml

# Classifier model
grep -n 'model: str = ' execution/classify_email.py

# DB target (expect a neon.tech URL in the secret; can't print value, but:)
gh secret list | grep DATABASE_URL

# Frontend prod API URL
cat services/dashboard/frontend/.env.production
```

**Known stale files still in the repo (do not treat as current):**
`services/dashboard/api/railway.json`, `services/dashboard/README.md`,
`services/dashboard/QUICKSTART.md`, `services/dashboard/FULLSTACK_QUICKSTART.md`,
and the `# Railway…` comments in `services/dashboard/api/database.py` (the
`postgres://` → `postgresql://` normalization there is still valid). Deployment
config that *is* live: `render.yaml` + `services/dashboard/api/Dockerfile.prod`.

---

## 15. Known issues & deferred work

- **Cost estimate is ~17× too high.** `_compute_cost()` /
  `_EST_COST_PER_EMAIL_USD` in `process_inbox_auto.py` use gpt-4o pricing while
  the model is gpt-4o-mini. Fix: use gpt-4o-mini rates ($0.15 / $0.60 per M) or
  read the model from one constant. Low risk, avoids false cost-guardrail aborts.
- **Interview / known-company emails are re-classified every run.** They're kept
  UNSEEN in INBOX on purpose, so each 2 h run re-fetches and re-classifies them.
  Deferred fix: stamp a durable `InboxGenius-Processed` Gmail label and exclude
  it from the fetch search (`fetch_emails.search_emails` already accepts
  `exclude_gm_labels`, just not wired to the caller).
- **`email_actions.delete_email()` defaults `folder="INBOX"`** — a dashboard
  delete of a non-inbox email now safely no-ops with a warning (previously could
  hit the wrong message). Pass the real folder if this path is ever re-enabled.
- **The mislabelled backlog from the Sept 2026 incident** keeps its junk labels
  in Gmail; the fix stopped new damage but didn't retro-clean. A one-off
  label-stripping script can be written if needed.
- **(This fork's local Docker env only)** Dashboard Settings' `interval_minutes`
  / `batch_size` controls don't actually reschedule the local cron container —
  `execution/crontab` is a static file, not read from `SystemConfig`. See
  [§4b](#4b-this-forks-local-docker-environment).

---

## 16. Changelog (infra / architecture only)

- **2026-09-29 (this fork)** — `process_inbox.yml`'s cron changed from
  `0 */2 * * *` to `20 */2 * * *`. Cause: the 00:00 UTC slot (8pm EDT) was
  consistently the latest-firing run of the day, 29-34 min after trigger for
  4 straight days, vs. 9-27 min for every other slot — GitHub Actions'
  scheduler is most congested at the top of the hour, worst at 00:00 UTC
  specifically (a globally common "midnight" cron pick across all of GitHub).
  The pipeline itself was never broken — every delayed run still completed
  successfully in under 2 minutes once dispatched. Offsetting 20 min off the
  hour avoids that congestion window; still every-2-hours cadence.

- **2026-09-25 (this fork)** — Dashboard showed 0 emails from 2026-09-24
  22:10 UTC while every GH Actions run was green. Cause: `execution/requirements.txt`
  had unpinned `sqlalchemy>=2.0.0`; SQLAlchemy **2.1.0** was released between
  runs and changed the default driver for bare `postgresql://` URLs to psycopg
  v3 (not installed) → every DB write failed with `No module named 'psycopg'`,
  logged only as a WARNING. Same commit, same secret — only the pip resolution
  changed. Fix: new `execution/db_url.py` pins `postgresql+psycopg2://` for all
  pipeline engines; `sqlalchemy>=2.0.0,<2.1`; DB write failures now alert
  (email + `::error::` annotation, §3 step 13). Tests: `tests/execution/test_db_url.py`.
  The dashboard API (`services/dashboard/api/requirements.txt`) pins
  `sqlalchemy==2.0.36` and was unaffected.
  **Backfill:** `execution/backfill_missed_runs.py` rebuilt the 10 missing
  `ProcessRun` rows from the GH Actions job logs and re-imported 262 moved
  emails from Gmail (read-only `EXAMINE`, matched by subject + arrival window,
  deduped on Message-ID). 65 could not be matched (~60 Spam Review mail already
  purged). Reusable for any future "runs green, DB writes failed" gap — save
  each run's `gh run view <id> --log` into a dir, dry-run, then `--apply`.

- **2026-09-18 (this fork's local Docker env only, not production)** — Cron
  container's `CMD` changed from `cron && tail -f cron.log` to `exec cron -f`
  (foreground `cron` as PID 1 directly). The old form let a bind-mounted-log
  `tail -f` become the container's PID 1; a WSL2/Docker Desktop filesystem
  hiccup killed that `tail -f`, taking the whole container (and any mid-flight
  run) down with it. Also fixed the dashboard's "Next run in" countdown to
  anchor on fixed UTC clock boundaries instead of `last_run_timestamp`, which
  manual "Run Now" runs had been silently desyncing. See [§4b](#4b-this-forks-local-docker-environment).
- **2026-09-08** — Move/delete pipeline switched from IMAP sequence numbers to
  **UIDs + Gmail label ops** (`+X-GM-LABELS` / `-X-GM-LABELS \Inbox`), with
  Message-ID re-resolution and UID-scoped spam expunge. Folder names quoted in
  `SELECT` (revived the long-dead spam-review 2nd pass). Newest-first INBOX
  fetch. Root cause: stale sequence numbers across two connections →
  wrong labels, mail stuck in Inbox, 300+ backlog. Commit on `master`; tests in
  `tests/execution/test_fetch_emails.py`. Full rewrite of this runbook.
- **2026-08-31** — `emails.message_id` UNIQUE column; DB dedup keyed on
  `Message-ID` not sequence number (fixed the 2026-06-29 → 08-31 dashboard
  freeze). `keepalive.yml` added. Cron re-enabled after 60-day auto-disable.
  `DATABASE_URL` GitHub secret corrected from Railway → Neon.
- **2026-06-03** — Migrated backend Render + DB **Railway → Neon**
  (Render's free PostgreSQL expired). Backend moved to Render Docker.
- **2026-06-27** — Two-pass Spam Review system added.
- (pre-2026-06) — Railway backend + Windows Task Scheduler era. **Deprecated.**

---

*Maintained by: Colaberry InboxGenius team. When you change hosting, the
pipeline, secrets, or the frontend stack, update this file in the same commit
(`CLAUDE.md` requires it).*
