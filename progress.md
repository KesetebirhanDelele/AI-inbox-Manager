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

## 2026-09-29 (late night) — Addressing the "small gaps" (#6) + no more pushes to master

**Side effect avoided:** pushing `master` can trigger Vercel/Render rebuilds of the
old fallback stack, so per Kes **nothing is pushed to `master` until Render/
Vercel/Neon are retired** (open item 5). Work happens on `feat/hetzner-deployment`
(pushing a branch is fine); deploy with `scripts/deploy_hetzner.sh` from the
branch. `master` sits at `24443cf` (the one push that already happened).

**Runtime changes (deployed):**
- **Deploy guard:** new `scripts/deploy_hetzner.sh` — refuses to deploy during
  `:00–:11` of an even UTC hour or while `tmp/process.lock` is fresh (the cause of
  the 22:00 UTC incident); `--dry-run`, `--force`, `--build-web`; deploys tracked
  files only via `git archive`, restarts the API, health-checks, records
  `.deployed_commit` on the server. 23 tests in `tests/deploy/test_deploy_script.py`
  (window rule incl. octal-looking "08"/"09", `--help`, bad option, no secrets).
- **ProcessRun for runs that go wrong:** `process_inbox_auto.py` `finally` now
  writes a `failed` row for a crash at ANY point (e.g. Gmail auth failure before a
  single email was fetched — previously no trace on the dashboard) and a
  `partial_failure` row when the fetch left emails behind and nothing else
  happened. A clean empty run still writes nothing. 4 new tests in
  `test_fetch_alerting.py`.
- **`db_storage_days_remaining` removed** from the KPI API, its query and the
  frontend type (test asserts it's gone).
- **Wrong "Run Now" message fixed:** in production it returns `unavailable` by
  design (only the server cron runs the pipeline — prevents a second runner
  double-processing the mailbox), but the message claimed it runs on a laptop via
  Windows Task Scheduler. Now: "Manual runs are disabled in production. The
  pipeline runs automatically every 2 hours, on the hour (UTC)…" (API + dashboard
  toast; test added). The local Run Now path now reads `MAX_EMAILS_PER_RUN`
  instead of the never-written `email_batch_size` setting.
- **Correction to the stakeholder note below:** "Run Now" cannot be triggered from
  the production dashboard at all, so an un-enforced role can't start runs; it can
  still approve/reject notifications and edit the whitelist.
- Comments in `process_inbox_auto.py` no longer mention Windows Task Scheduler.
- Laptop check: the old Windows task `ColaberryEmailProcessing` does not exist on
  this machine, so nothing can double-process the mailbox from here.

---

## 2026-09-29 (night) — STATUS SNAPSHOT: Hetzner is live; decisions and open items

**Where things stand.** Production runs on the Hetzner server
(`2.29.47.89`, https://2-29-47-89.nip.io) — see RUNBOOK §4c. Scheduled runs fire
on the hour (first confirmed 20:00:01 UTC). All four GitHub workflows are
disabled; Render/Vercel/Neon are untouched fallbacks (Neon frozen at
2026-09-29 18:44 UTC). Per-run cap is 150 (`MAX_EMAILS_PER_RUN`), schedule every
2 h. Latest code is deployed from git (commit `4008510` + the docs commit that
lands this entry).

**Decisions made by Kes (2026-09-29):**
- **No PR needed** — solo project. PR #3 was opened, then dropped: the branch is
  landed directly on `master` with a fast-forward push (GitHub marks PR #3
  merged automatically). Work now goes straight to `master`; deploy with
  `git archive master | ssh …` (RUNBOOK §4c). The `feat/hetzner-deployment`
  branch is left in place, no longer needed.
- **No backups:** no Hetzner server backups and no scheduled DB dump (emails
  stay in Gmail; the DB is dashboard history). Optional manual script kept.
- **Redundant dumps deleted after 1 week:** one-shot cron
  `/etc/cron.d/inboxgenius-cleanup-dumps` removes two dumps on 2026-10-06 12:00
  UTC; the final cutover dump (`neon_premigration_…184445Z`) stays until Neon is
  retired.
- Domain stays `2-29-47-89.nip.io` for now.

**Open items (nothing below is blocking production):**
1. **Stakeholder role is not enforced** — the API never checks `role`, so a
   "stakeholder" login can do everything an admin can (Run Now, approve/reject
   student notifications, edit whitelist). No stakeholder login exists on Hetzner
   (`STAKEHOLDER_PASSWORD_HASH` only in Render, unverified). Fix = admin-only on
   all POST/PUT/DELETE endpoints + UI, with tests; then create a stakeholder
   password on the server. **Do not hand out a stakeholder login before that.**
2. **Verify the new fetch code live** — the 00:00 UTC run (2026-09-30) is the first
   with the reconnect/`partial_failure` code and the 150 cap; check
   `grep -c "fetch_emails - ERROR" logs/cron.log`, run status, and that no
   "Email fetch incomplete" alert fired. The reconnect path has only been tested
   with fakes, not against real Gmail.
3. **Real domain** to replace nip.io (Let's Encrypt rate limits on the shared
   domain could refuse renewal ~2026-12-28).
4. **Tell the team the new URL** — the old Vercel dashboard is stale and won't update.
5. **Retire Render, Vercel, Neon** after ~a week of stable Hetzner runs: take a
   final Neon dump first, rotate the OpenAI key + Gmail app password (old copies
   exist on Render/GitHub), delete `render.yaml` and the Render/Neon workflows,
   remove the old RUNBOOK sections (§1–§4, §8, §10, §12, §14 are banner-marked as
   previous setup until then), delete the final dump.
6. **Known small gaps:** deploys must avoid the `:00`–`:10` window of even UTC
   hours (RUNBOOK §4c); a run that fails *entirely* before any email is fetched
   writes no `ProcessRun` row (the alert email covers it); `db_storage_days_remaining`
   is still returned by the API though the UI no longer shows it; stale
   "Windows scheduled task" wording may remain elsewhere; the Railway-era stale
   files listed in RUNBOOK §14 are still in the repo.

**Test status:** repo suite 365 pass / 18 fail — all 18 pre-existing in
`tests/execution/test_log_interview.py` (`No module named 'models'`). Dashboard
suite passes in the API image (3 `test_notifications.py` tests only fail in a
dashboard-only scratch copy for lack of the `execution` package).

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
- **Incident (22:00 UTC scheduled run, run #135):** a deploy (`git archive` sync +
  Docker image rebuilds) overlapped the run. All 176 IMAP fetches failed at once
  with `socket error: EOF`, so only 2 emails were processed — yet the run was
  recorded as `success` and no alert fired. No mail lost (skipped emails stay
  unread). Recovered with a manual run on the idle server (#136: 91 processed,
  74 moved, 0 errors, 345 s). Cause is most likely CPU/network starvation from
  the build (all earlier runs, including three at the 100 cap, had 0 fetch
  errors) — inferred, not proven. **Lessons:** deploy between `:10` and `:55`
  past an even UTC hour (RUNBOOK §4c). **Follow-ups (both now done — see the
  next bullet):** (a) reconnect/retry the IMAP fetch when
  the connection drops instead of failing every remaining UID, (b) send a
  failure alert (`send_failure_alert`) and/or mark the run `partial` when fetch
  errors occur, so a "green" run with 176 errors isn't silent. Note the manual
  run (91 emails) did not reach the 150 cap, so the cap itself is not yet
  stress-tested.
- **Dump cleanup scheduled (owner request: "delete after 1 week"):** one-shot
  `/etc/cron.d/inboxgenius-cleanup-dumps` on the server removes
  `neon_premigration_…160602Z` and `inboxgenius_…185028Z` on 2026-10-06 12:00 UTC,
  then deletes itself. `neon_premigration_…184445Z` (final cutover copy) is
  deliberately kept until Neon is retired. (PR #3 was opened, then dropped in
  favour of landing directly on `master` — see the status snapshot above.)
- **IMAP fetch resilience + alerting (fix for the incident above):**
  `execution/fetch_emails.py` — new `EmailConnectionLost` (socket/SSL/timeout/EOF/
  `IMAP4.abort` during a FETCH) and `FetchedEmails` (list subclass with `skipped`,
  `abandoned`, `reconnects`); `fetch_emails()` now reconnects (backoff 2/5/10 s,
  max 3), re-selects the folder and retries the same UID, and abandons the rest
  only if that fails. `execution/process_inbox_auto.py` — records fetch stats
  (before the empty-inbox return, so a total fetch failure is no longer reported
  as "No unread emails"), sets ProcessRun status `partial_failure` (the model's
  documented value) via `_run_status()`, and `main()` sends a "Email fetch
  incomplete" alert when a UID was abandoned or ≥5 emails failed
  (`_FETCH_ERROR_ALERT_THRESHOLD`); a recovered reconnect or 1–4 bad emails only
  log. Tests: 29 new (`test_fetch_resilience.py`, `test_fetch_alerting.py`); full
  suite 365 pass / 18 fail, the 18 all pre-existing in `test_log_interview.py`.
  Directive `email-integration.md` v1.2 + RUNBOOK §4c playbook row added.
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
