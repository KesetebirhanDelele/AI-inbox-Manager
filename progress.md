# Progress Log

Running log of code changes in this repo — every change, not just infra
(infra/architecture incidents also get an entry in [RUNBOOK.md §16](RUNBOOK.md),
which stays the source of truth for those; this file is the source of truth
for everything else, including cleanups and small fixes that RUNBOOK.md
doesn't cover).

**Read this before starting new work**, the same way `RUNBOOK.md` gets read
before diagnosing production issues. This file exists because it didn't
before — a duplicate `requirements.phase1.txt` missed the SQLAlchemy driver
fix, then nearly missed the openai/google-api-python-client cap too, because
nothing recorded that the first fix had ever happened or where it had been
applied. See [CLAUDE.md](CLAUDE.md) "Maintain `progress.md`".

Newest first.

---

## 2026-09-29 (evening) — Hetzner live: first scheduled run confirmed, SSH hardened, storage card

- **First scheduled run confirmed:** started 20:00:01 UTC (GitHub was 9–34 min
  late), `triggered_by=scheduled`, success, 54 processed / 38 moved, 0 errors,
  `ProcessRun` #134. Cutover complete; RUNBOOK §4c is now the authoritative
  production section (header, §0 table and §16 changelog updated too; §1–§3,
  §8, §10, §12 still describe the old setup — flagged in the header).
- **SSH hardening (verified with a fresh connection):**
  `/etc/ssh/sshd_config.d/01-hardening.conf` (PasswordAuthentication no,
  PermitRootLogin prohibit-password, MaxAuthTries 3, X11Forwarding no);
  `fail2ban` sshd jail (5 tries / 10 min → 1 h ban) banned an attacker within
  seconds; password login now returns `Permission denied (publickey)`.
- **"Neon Storage Left" card → "Database Storage Left"** (`DashboardPage.tsx`,
  `routers/stats.py`): the cap comes from env `DB_STORAGE_CAP_MB` (default 512,
  so Render/Neon behave as before; the Hetzner `.env` sets 40960); sizes ≥1 GB
  display in GB. 7 new unit tests in `services/dashboard/tests/test_stats.py`
  (pass). Note: `TestCategoryBreakdown::test_categories_with_data` fails on the
  committed baseline too (pre-existing, unrelated, not investigated). Verified
  live: the API returns a 40960 MB cap, and the served bundle has the new label
  and not the old one.
- **Countdown timer fixed:** the dashboard's "Next run in" showed the time to the
  next 10-minute boundary (e.g. `6:40` at 16:13 UTC) because
  `routers/schedule.py` defaulted `interval_minutes` to 10 when the `system_config`
  table has no row (it's empty here). Default is now 120, matching the real
  cron `0 */2 * * *` (test in `test_schedule.py` updated). `useCountdownTimer.ts`
  now formats ≥1 h as `h:mm:ss` (was `m:ss`, would read "90:28"), and the card
  caption says "runs every 2 hours". Verified live: API returns 120; at 20:30 UTC
  the countdown computes to 22:00 UTC (`1:29:26`). Known limit: the Settings
  page's interval/batch controls are still cosmetic (cron is a static file) and
  changing the interval there would desync the countdown again; the batch-size
  default (20) also doesn't match `MAX_EMAILS_PER_RUN` (100).
- **Days-to-full-storage removed** from the storage card (`DashboardPage.tsx`):
  the big "Nd" number is gone and the card is now "Database Storage" (size, %,
  usage bar). The API still returns `db_storage_days_remaining` (unused by the
  UI; left in place to avoid an API/type change).
- **Settings controls removed; schedule endpoint now read-only:**
  `routers/schedule.py` rewritten — GET reports interval 120 (= cron
  `0 */2 * * *`) and batch size from `MAX_EMAILS_PER_RUN`; the POST endpoint, the
  `system_config` writes and the Windows PowerShell `update_scheduled_task` call
  are gone (POST now 405). `SettingsPage.tsx`: sliders / Update button replaced
  by a read-only card; `client.ts`: `updateScheduleConfig` removed. Tests:
  `test_schedule.py` rewritten (env cap, bad-env fallbacks, POST 405, auth).
- **Per-run cap 100 → 150:** `MAX_EMAILS_PER_RUN=150` added to the server `.env`
  (100 was hit on 3 consecutive runs 09-29 14:32/16:35/18:37 UTC; 15 of the last
  30 days' runs were ≥90). Cost guardrail unaffected (150 × $0.015 = $2.25 < $5).
  Schedule stays every 2 hours.
- **Stale test fixed:** `test_categories_with_data` expected "Job Alert" in the
  category breakdown, but commit `23f0c0d` deliberately excludes "Job Alert" and
  "Application Notification" (job-board noise; they only sort mail into the
  "Job Alerts" folder and never notify students). Test now asserts they are
  hidden. Full dashboard suite: 175 pass; 3 `test_notifications.py` failures
  occur only in my dashboard-only scratch copy (`No module named 'execution'`),
  identical on HEAD, not a code regression.
- **Backups dropped (owner decision):** Kes will not enable Hetzner server backups
  and doesn't want the daily dump. Removed `/etc/cron.d/inboxgenius-backup` from
  the server (verified gone). `scripts/backup_postgres.sh` is kept as an optional
  manual tool (header + directive step 6 updated). Three dump files remain in
  `/opt/backups/inboxgenius/` (two `neon_premigration_*`, one test dump; they
  contain email data) — left in place, not deleted.
- **RUNBOOK cleanup:** §1, §4, §8, §10, §12 now carry "previous setup / fallback"
  banners pointing to §4c; added a Hetzner failure playbook (§4c) and Hetzner
  verify commands (§14); §4c backups row and "still deferred" list corrected;
  changelog notes the no-backup decision.
- **Deferred:** (backup item removed); stakeholder
  login hash; a real domain to replace nip.io; retire Render/Vercel/Neon and
  remove their RUNBOOK sections; the Settings page / `schedule.py` still has
  vestigial "Windows scheduled task" wording.

---

## 2026-09-29 — Hetzner deployment: repo files added (branch `feat/hetzner-deployment`, not yet deployed)

**Added the files needed to run the whole system on one Hetzner server** (CPX22,
`2.29.47.89`, hostname `2-29-47-89.nip.io`). Nothing existing was modified and
production (Render/Vercel/Neon/GitHub Actions) is untouched. Goal: fix the
GitHub Actions scheduler lateness (real cron on our own host), give the
dashboard a public HTTPS URL, and move storage into Postgres in Docker.

New files:
- `services/dashboard/docker-compose.prod.yml` — `postgres` (no published port),
  `api` (non-root), `web` (Caddy: static frontend + HTTPS + reverse proxy),
  `cron` (behind the opt-in `scheduler` profile so it can't double-process the
  mailbox while GitHub Actions is live).
- `services/dashboard/api/Dockerfile.server`, `execution/Dockerfile.cron.server`,
  `services/dashboard/frontend/Dockerfile.prod`, `frontend/Caddyfile`,
  `execution/crontab.server`, plus per-Dockerfile `.dockerignore` files that keep
  secrets out of the build context.
- `scripts/hetzner_init_secrets.sh` (generates secrets on the server, never
  prints them), `scripts/backup_postgres.sh` (daily dump, 30-day retention),
  `services/dashboard/compose.env.example`.
- `.gitattributes` — forces LF for shell scripts, crontabs, Dockerfiles, the
  Caddyfile and the prod compose file (this repo runs `core.autocrlf=true` on
  Windows; CRLF would break shebangs and `/etc/cron.d` files on Linux).
- `directives/hetzner-deployment.md` — the SOP.
- `tests/deploy/test_prod_compose.py` — 9 guardrail tests (Postgres unpublished,
  only `web` publishes ports, cron is opt-in, no hard-coded secrets, ...).

Verified locally: 9/9 new tests pass; `docker compose config` valid; Caddyfile
valid; all three images build; frontend build bakes the nip.io URL with zero
Render references; cron job runs as uid 1000; API image runs non-root.

**Follow-up same day:** Neon turned out to run Postgres **18.6**, so the prod compose
uses `postgres:18-alpine` (volume mounted at `/var/lib/postgresql`, the PG 18 image
layout) to allow a clean `pg_dump` → restore; a 16 container can't take an 18 dump.

**Cutover done 2026-09-29 (server side, no repo code change):** server prepped
(Docker 29, 2 GB swap), secrets generated on the server, Neon → Postgres 18
restored twice (final copy after disabling `process_inbox.yml` at ~18:40 UTC;
Kes then disabled the other three workflows too — keepalive, backup_neon_db,
deploy_backend — so all 4 are off;
all 12 tables' row counts identical: 4,318 emails, 132 runs), public HTTPS
verified (Let's Encrypt, login 5/5 checks), Hetzner `cron` started, manual run OK
(52 processed / 38 moved / ProcessRun #133), daily backup cron installed
(03:30 UTC, first dump 20 MB). Scripts made executable in git
(`git update-index --chmod=+x`) after a re-sync dropped the exec bit.
**Still to do:** confirm the first scheduled run (20:00 UTC), rewrite RUNBOOK
§0–§4/§8/§10/§12 as authoritative for Hetzner, relabel the "Neon Storage Left"
card, add SSH hardening + fail2ban, decide when to retire Render/Vercel/Neon,
and carry over the stakeholder login hash.

**Original deferred list (pre-cutover):** actual server deploy, Neon → Postgres data
migration, cutover (disable GitHub Actions cron), backup cron install, SSH
hardening, and the RUNBOOK.md rewrite (RUNBOOK §4c added as "in progress"; make
it authoritative only after cutover). Stakeholder login hash still lives only in
Render env vars — needs to be carried over or regenerated.

---

## 2026-09-29 — Cron offset fix + Ojobo1800 reference cleanup

**Fixed `process_inbox.yml`'s cron congestion.** Investigated why the 8pm EDT
(00:00 UTC) scheduled run appeared to not fire — it did fire, but 29-34 min
late, every day for 4 straight days, vs. 9-27 min for every other 2-hour
slot. Root cause: GitHub Actions' scheduler is most congested at the top of
the hour, worst at 00:00 UTC (a globally common cron pick). Changed the cron
from `0 */2 * * *` to `20 */2 * * *` in `.github/workflows/process_inbox.yml`
to dodge that window. `RUNBOOK.md` §16 and "Last verified" updated in the
same change.

**Removed all references to the original upstream repo
(`Ojobo1800/AI-inbox-Manager`) from this repo.** Deleted the `upstream` git
remote and rewrote 5 spots in `RUNBOOK.md` that named it. Two of those spots
(the Scheduler/CI + Git repo URLs in §1, and the secrets header in §8) were
actually pointing at the wrong repo — stale from before the 2026-09-18
migration to this fork's own independent GitHub Actions/Neon setup, not just
confusing. Rewritten to describe this fork as self-contained.

---

## 2026-09-28 — Repo maintenance session

**Removed 17 dead files (PR #2, merged to fork `master`).**
Audited every `.py`/`.txt` script in the repo against CI workflows,
`render.yaml`, code imports, docs, and directives. Files with zero references
anywhere were deleted; files referenced only in docs/directives were left
alone pending human confirmation.

Removed:
- `requirements.phase1.txt` (root duplicate — the real one is
  `client_inbox_foundation_phase1/requirements.phase1.txt`)
- `execution/process_inbox_smart.py`, `process_and_organize.py`,
  `explore_email_folders.py`, `fetch_sample_interviews.py`,
  `setup_sharepoint.py`, `log_to_sharepoint.py`
- `services/dashboard/check_db.py`, `import_interviews.py`,
  `import_interviews_from_summary.py`, `backfill_runs.py`,
  `extract_interview_details.py`, `fetch_real_email_content.py`
- `services/dashboard/api/check_db.py`, `check_auth.py`,
  `requirements.py313.txt`, `requirements.py313.fixed.txt` (abandoned Python
  3.13 experiment; `render.yaml` builds from `requirements.txt` only)

Verified via `pytest --co -q` (345 tests collected, no import errors from any
deletion) and full run (327 passed, 18 pre-existing failures in
`test_log_interview.py` — unrelated `ModuleNotFoundError: No module named
'models'`, confirmed identical on `master` before this change via
`git stash` comparison).

**Deferred, not done:** `RUNBOOK.md` §14 already flags a separate batch of
Railway-era stale files (`services/dashboard/api/railway.json`,
`services/dashboard/README.md`, `QUICKSTART.md`, `FULLSTACK_QUICKSTART.md`,
stale comments in `database.py`) as known-stale but out of scope for this
session.

**`CLAUDE.md` updated** to require a `progress.md` entry with every code
change going forward (this file, created this session).

---

## 2026-09-28 — Dependency version caps (in progress, not yet merged)

Branch `chore/cap-major-version-pins`, pushed to fork, reviewed and approved
by Ali via email. **PR not yet opened** — pending explicit go-ahead.

Scope: cap `openai` at `>=1.0.0,<2.0.0` and `google-api-python-client` at
`>=2.100.0,<3.0.0` (or `>=2.161.0,<3.0.0` for the phase1 variant) across 5
files: `requirements.txt`, `execution/requirements.txt`, `pyproject.toml`,
`requirements.phase1.txt` (root — since removed, see above),
`client_inbox_foundation_phase1/requirements.phase1.txt`. The `openai` cap
was verified against actual usage — `execution/classify_email.py` targets the
1.x client API (`openai.OpenAI(...)`, `RateLimitError`, `APIStatusError`).
Left untouched per Ali's scope call: pytest, black, flake8, mypy, fastapi,
twilio, httpx, tenacity.

Note: this branch was cut before the `chore/remove-dead-scripts` cleanup, so
it still contains the now-deleted root `requirements.phase1.txt` — will need
a rebase or conflict resolution against current `master` before merge.

---

## Earlier history (inferred from `RUNBOOK.md` §16 and git log — predates this file)

- **2026-09-25** — Dashboard silently stopped recording emails while GH
  Actions stayed green. Root cause: unpinned `sqlalchemy>=2.0.0` picked up
  2.1.0's driver default change (psycopg v3, not installed) →
  `execution/db_url.py` added to pin `postgresql+psycopg2://`; DB write
  failures now alert. Backfill via `execution/backfill_missed_runs.py`
  recovered 262 of ~327 missed emails. PR #1
  (`fix/sqlalchemy-21-psycopg-driver`).
- **2026-09-18** — Local Docker cron container's `tail -f` PID1 problem fixed
  (`exec cron -f` instead); dashboard "Next run in" countdown desync fixed.
- **2026-09-08** — Move/delete pipeline switched from IMAP sequence numbers
  to UIDs + Gmail label ops; fixed a 300+ email backlog bug.
- **2026-08-31** — `emails.message_id` UNIQUE constraint added for dedup;
  `keepalive.yml` added; `DATABASE_URL` secret corrected Railway → Neon.
- **2026-06-27** — Two-pass Spam Review system added.
- **2026-06-03** — Backend + DB migrated Railway → Render + Neon.
- **pre-2026-06** — Railway backend + Windows Task Scheduler era. Deprecated.

For full detail on any of the above, see `RUNBOOK.md` §16 and `git log`.
