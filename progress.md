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

## 2026-10-01 — Interview sub-classifier wired in; spam pass quarantines instead of deleting

**Status: deployed to production and merged to `master` (deployed commit == `master` HEAD).**
The detail below is in the order the work happened; this block is the summary.

### 2026-10-02 (night): prompt fix, call rules, own opt-out record, channel test tool, test plan
- **Prompt** (`docs/voice-agent-outbound-interview-prompt.md`): the first test call showed the agent skipped "Am I speaking with ...?"
  because the agent's own Welcome Message setting is spoken before the prompt. Added checklist step 1a (set the welcome message to the
  identity question), made step 1 wait for the answer instead of greeting again, and made the agent go straight to the details after a
  yes (no "would you like to hear the details?"). GHL also adds its own opt-out sentence to the opening; kept.
- **Call reading by rule** (`ghl_conversations.call_outcome`, `call_turns`, `VoiceCall.outcome`; wired in `escalation_engine.poll_replies`):
  a plain yes to the confirmation question = acknowledged (explicit, even in shadow mode); "don't call me again" = STOP. "yes but I can't"
  and a yes before the details are NOT confirmations. Before this a call "yes" would only have been read by the AI in shadow mode.
- **App-side opt-out memory**: new table `notification_opt_outs` (model, alembic 005, `init_db` import), written by
  `escalation_engine.record_opt_out` on a STOP text/call/email, checked by `notify_channels.opted_out_in_app` before every GHL send.
  New table only (create_all cannot add columns); `create_all` makes it on the next API start.
- **Test tool** (`execution/ghl_test_call.py`): now `--channel call|sms|email`, writes only that channel's field(s) on one exact-match
  contact after the DND check, `--readback` shows each call's `app reads it as` line plus the last 24 h of messages.
- **Test plan**: `docs/test-plan-student-notifications.md` (stages 0-7 with expected results and a go-live gate).
- Tests: 724 root + 191 dashboard passed. Still OFF: no GHL credentials on the server, escalation disabled, nothing sent to students.
- Also: removed stray `samp.txt` (accidentally committed with the test script).
- Deferred: text/email test writes, voicemail/wrong-person/STOP calls (Kes tests step by step per the plan); GHL `do not call` tag action;
  server shadow rehearsal; 5-minute cron; Rob/Ali items.

- Kes set the agent's Welcome Message (Outbound tab, "AI speaks first", 117/190 chars) to the identity question; prompt doc now names the exact setting. Next: re-test call (stage 1.1 of the test plan).

- **PENDING (Ali):** the inbound AI Receptionist in GHL does NOT yet have the INTERVIEW CALLBACKS section (doc section 4). Waiting for Ali to say who
  gets interview callbacks and within what time (question 4 in the draft email). Kes asked to be REMINDED after Ali responds: then update the
  receptionist prompt with the named owner/time and run test 1.9 of `docs/test-plan-student-notifications.md`.

- Opening shortened (Kes found the GHL default disclosure + our greeting off-putting): Outbound AI Disclosure set to Custom ("Hi <first>, this is Colaberry's AI assistant calling about your interview. You can say 'stop calling' at any time."), Welcome Message reduced to "Am I speaking with <first>?"; prompt step 1 and checklist 1a/1b updated. Needs Ali's OK on the disclosure wording; re-test stage 1.1.

### 2026-10-02 (end of day): where we stand, and what we are waiting for

**WAITING ON ALI** (draft reply sent to Kes's Gmail drafts on the thread "AI-Inbox-Manager is now deployed and live on Hetzner"; Kes sends it):
1. Consent: have students agreed to automated calls and texts? (GHL does not check.)
2. Pilot size: first live run with 3 students Rob approves by hand, then everyone?
3. Who may undo a STOP (recommended: Ali or Rob, on the student's written request).
4. Who takes interview callbacks, and within what time. **Blocks the INTERVIEW CALLBACKS section of the inbound AI Receptionist (not yet added). Remind Kes when Ali answers.**
5. Alerts: tell Rob when a draft is waiting; tell Ali if a draft sits unapproved past about 2 hours (neither built).
Also to confirm with Ali: the wording of the custom AI disclosure on the outbound agent. Deliberately NOT asked now: Cora's real SMS usage, the GitHub destination.

**Voice agent, as of tonight:** one live test call proved the field value reaches the agent, the facts are spoken correctly, the reference is not read, "yes" is captured. The opening was rebuilt (custom AI disclosure + one-line welcome message) and saved in GHL; **the greeting re-test call is due tomorrow between 8 AM and 8 PM Kes's time** (calls after 8 PM are not allowed; it was ~11 PM Eastern when Kes saved).

**Next, in order (all on Kes's own contact, per `docs/test-plan-student-notifications.md`):** greeting re-test (1.1) -> wrong person (1.4) -> voicemail (1.5) -> STOP (1.6) -> text test (2.x) -> email test (3.x) -> GHL `do not call` tag action -> server shadow rehearsal (5.x) -> small live pilot (6.x) only after Ali's answers.

**Use cases page** updated and republished (artifact version 4, same link; tracked copy `docs/use-cases.html`): UC16 now Partial with live-call evidence, new stories 14.8, 14.9, 15.8, 16.8, 16.9, 17.5-17.7, summary now 7 working / 5 partial / 5 built-off.

### 2026-10-03: email-first GHL contact lookup, and Rob told when a student cannot be reached
- **Why (Kes):** the interview notice identifies a student by email, so email should be the normal way to find the GHL contact; phone was
  only my build assumption (exact-phone match was my safe default). Live check (read-only, counts only, 2026-10-03): 7 students in the
  table, only 2 with a phone, 4 with a personal email, 3 with neither; GHL found by PHONE for the 2 that have one, but searching by our
  stored personal email found NO contact for any of the 4 emails: for both phone-matched students GHL holds a DIFFERENT gmail address than
  ours, and for one of them the GHL contact's first name differs from the student's. So the data in the two systems disagrees and must be
  cleaned; email-first today would reach nobody, which is exactly why Rob must be told.
- **Built:** `find_ghl_contact()` (personal email, assigned Gmail, then phone; identifiers must agree; phone-only match needs the same first
  name), `UNREACHABLE:` attempt details, `RobAlerts.cannot_reach` (once per sequence; immediately when nothing is on file),
  `start_sequence` keeps call/text attempts for any student that can be found by email, new tests (740 root pass, 191 dashboard).
- **Open:** reconcile student emails/phones between our table and GHL (Rob/Kes); student matching of interview events (3 of 5 no student);
  time zone should come from the GHL contact's phone when ours is missing.

### 2026-10-03: "Interview Requests" page was empty (35 in the count card, none in the list)
- **Cause:** the page calls `/api/interviews` (no trailing slash); the route was `/`, so FastAPI answered 307 with `Location: http://...` (the https scheme
  is lost behind Caddy) and the browser dropped it, leaving an empty list. Unit tests passed because they all used the slash. Proven with `curl -I`.
- **Fix:** route registered for both `""` and `"/"` (`routers/interviews.py`), the client now calls `/api/interviews/`, new test
  `test_the_list_answers_without_a_trailing_slash_and_never_redirects`. Empty "Upcoming" text now explains why it is empty.
- **Backfill checked, nothing to backfill:** all 40 events have NO interview date/time in the extraction (0 of 40 ever had one; 4 have a format), because they
  are recruiter "interview request" emails with no scheduled date. The Events Report "-" and the empty Upcoming section are correct, not bugs.
  32 of 40 events have no student (the open matching issue); 8 drafts exist (all status `draft`).
- **Where Rob approves:** Review > Inbox tab (draft subject/body, "Approve & Send", "Edit"/"Save & Send"). The Approvals tab is the separate low-confidence
  classification review. Note: until escalation is enabled, "Approve & Send" sends ONE real email to the student.

### 2026-10-03: Rob's approval screen ("Review > Student notifications") and the email authenticity check
- **Why (Kes):** Rob could not see the draft, the student's contact details or any Approve button where he was looking (the old panel only existed for
  emails with a matched student), and nothing told him whether an "interview" email was a real invitation or a job-board mailer (4 of the 8 drafts were
  from Job-Assist-Now). Rob must be able to judge that before approving.
- **Built:** `execution/email_authenticity.py` (deterministic, advisory: looks_genuine / needs_check / likely_job_board, with readable reasons for and
  against: click-tracking links, job-board phrases, generic mailbox on a jobs domain, reference codes vs a named sender at the company's own domain,
  a concrete date/time, a meeting link), `GET /api/notifications/review-queue` (one item per interview event: student + phone/email, interview
  facts, source email excerpt, the check, draft, preview of the call/text/email, blockers and warnings, what Approve will do, follow-up status),
  and the frontend `NotificationQueue` as the FIRST tab of Review ("Student notifications"; old Approvals tab renamed "Classification review").
  Approve needs a second confirmation that states exactly what will happen; Reject asks for a reason. Events with no student are listed as
  "Student not identified" with Approve disabled, so nothing hides. Advisory only: a job-board warning never blocks Rob.
- **Limits:** the check reads only the stored first 500 characters of each email (the note says so); previews of the text/call are shown but those
  channels are still off, and until escalation is enabled Approve sends ONE real email. Edit is still on the Inbox tab. Tests: 746 root, 199 dashboard.
- **Not done:** widen the body-name finder for "Name, ..." openings (it missed "Sehrish, you asked to be considered"), assign-a-student action for unmatched
  events, dashboard tile clean-up (analysis given to Kes, awaiting his choice), checklist wording ("via personal email").

### 2026-10-03 (later): dashboard decision, and the frontend deploy lesson
- **Kes's call on the dashboard tiles:** keep Upcoming Interviews This Week, Offers Received, This Week, Avg Duration, Failure Rate, AI Cost, Database Storage and
  Emails Processed Today. Only change made: the "Students Not Yet Notified" table is replaced by one banner, "Student notifications: needs your
  decision (N ready, M need fixing)", linking to Review > Student notifications. "Recent Interview Requests" left untouched (not discussed).
- **LESSON (cost Kes a wasted check):** `scripts/deploy_hetzner.sh` rebuilds the web image ONLY with `--build-web`. A frontend change deployed without it
  updates the API but the browser keeps the old screens. Any change under `services/dashboard/frontend/` must be deployed with `--build-web`
  (outside the :00-:11 window of even UTC hours), then check the bundle on the server. Added to RUNBOOK.

### 2026-10-03 (evening): Events Report merged into Interviews; Upcoming and Offers fixes
- **Merged (Kes: "one of them"):** the Interviews page is now event-based (one row per interview event, from `/api/interviews/events`, which now also returns
  `draft_id`, email `subject`/`from_address`/`received_date` and `confidence`). Columns: student (+ email), type, company, position, interview date ("Not scheduled
  yet" when none), received, notification (Notified / Needs your decision + a "Decide" link to Review / Student not identified / No draft). Tabs: All / Needs your
  decision / Notified / Not notified yet, with counts; search and type filter; the process checklist still opens per row. The Events Report page is deleted;
  `/interview-events` redirects to `/interviews`; its nav item is gone; the Dashboard link now points to Interviews.
- **Upcoming interviews:** on both the Dashboard and Interviews, always shown, a real 7-day window ("N more later" counts the rest), and an empty message that says why.
- **Offers tile:** relabelled "Offers Today"; today and this-month are now compared in Central time (the UTC date slice was a day off in the evening). Only ONE Offer email
  exists in production (2026-09-29), so 0 today and 0/10 this month are correct.
- **Found, not fixed:** 20 emails in interview categories (Phone Screen 7, Interview Cancelled 6, Confirmation 3, Schedule 3, Instant Interview 1) have NO interview
  event, so they cannot reach Interviews, Upcoming or notifications. Needs a dry-run backfill that re-reads the mailbox (not started; ask Kes first).
- Deployed WITH `--build-web`. Tests: 746 root, 201 dashboard.

### 2026-10-03 (night): full UI audit in a real browser (local Docker + Playwright), outdated features fixed
- **How:** ran the dashboard locally (docker compose: postgres, api, frontend), seeded synthetic data, drove every page with Playwright (real Chrome), read the screenshots,
  and ran an end-to-end flow (approve one notification, reject one, open the checklist). No console errors or failed requests on any page. Scripts live in the session scratchpad only.
- **Found and fixed:**
  | Problem | Fix |
  |---|---|
  | Process checklist said "Notify the student via personal email" (all 7 types), had no step for judging the email or confirming the student, and 5 interview types (schedule, confirmed, assessment, final round, other) had NO checklist (404 text under the row) | New three-step checklist for every type (Check the email / Notify the student (call, text and email) / Make sure the student knows); unknown types get a generic one; "Approve the notification" ticks itself on approval (`approve_step_key`); old keys had 1 uncompleted tick in production so nothing is lost |
  | Inbox list and email bodies showed raw HTML/CSS ("<!DOCTYPE html>... @import url(...)") because the HTML-to-text step only removed tags; this also starved the authenticity check | `execution/text_cleaning.py` (drops head/style/script/comments, keeps line breaks, decodes entities); used at ingestion (`fetch_emails.extract_email_body`) AND on read in the API (old rows are rebuilt from `full_body`) |
  | Authenticity check said "Looks like a real interview" for resume-marketing mail (two WEAK signals added up) | "looks_genuine" now needs a strong signal (a date/time, a meeting link or a named sender); weak phrases removed |
  | Approve & Reject existed in two places (Inbox panel and the new queue); Inbox "Save & Send" could send around the queue's checks | Inbox panel is read-only for decisions (link to Review > Student notifications) and keeps "Edit draft" (save only); the queue is the only place to approve/reject |
  | API let a draft be approved with no student or no contact details | server-side guard returns 400 with the reason |
  | Reports > "Missed Interviews" duplicated the approval queue | tab removed |
  | Dashboard "emails waiting for approval" banner opened the wrong tab | now opens Review > Classification review (`?tab=approvals`) |
  | Interview types shown as raw "other"/"confirmed"; Interviews list sorted by created time | shared labels (`constants/interviewTypes.ts`); newest received first |
- **Found, NOT fixed (needs Kes or a decision):** (1) 20 interview-category emails have no event (Phone Screen, Cancelled, Confirmation, Schedule, Instant Interview); (2) some emails store the
  sender as "Unknown"; (3) "Run Now" / "Run Email Processing" run the whole pipeline inside the API container and share the lock with the cron container only through the mounted repo:
  configuration checked, NOT exercised on production; (4) the Dashboard "Recent Interview Requests" panel overlaps the Interviews page; (5) the old local development database holds fake
  students ("Ok", "Pandey") from an earlier name-matching bug, production shows 5 of 7 students with single-word names (to be reviewed with Rob).
- Tests: 752 root, 205 dashboard. Deployed WITH `--build-web`.

### 2026-10-03 (late): missing interview events, redundant screens removed, email body on Interviews
- **Root cause of the 20 emails with no event:** `process_inbox_auto` created an InterviewEvent only in the "keep in inbox" branch (category Interview Request or a known company).
  Phone Screen / Cancelled / Confirmation / Schedule / Assessment emails went down the "organize" branch, which filed them in a folder and never created an event, so they never reached
  Interviews, Upcoming or notifications. **Fixed in the pipeline** (organize branch now calls `process_interview_email` for new interview-related mail; "Instant Interview" maps to an
  interview request) and **backfilled** with `execution/backfill_interview_events.py` (dry-run default, `--apply`, reuses the real pipeline step, drafts only, never sends).
- **Removed as redundant (Kes: "remove any redundant tile or tab"):** Dashboard "In Inbox" tile (it counted emails whose stored folder is INBOX, and its sync icon re-read Gmail;
  duplicated the Inbox tab), the Dashboard "Interviews" quick-link banner (nav has it), the Dashboard "Recent Interview Requests" panel (overlapped Interviews), and Review > Inbox
  (decisions live in Student notifications; its Edit draft moved into the queue card, which saves without sending). Kept: every tile Kes named, and the Reports tabs.
- **Interviews page:** an expanded row now shows the email body (cleaned) above the checklist; the sender "Unknown" reads "an unknown sender".
- Tests: 755 root, 205 dashboard.

### 2026-10-03 (late, 2): backfill applied in production; "Run Now" made to work in production
- **Backfill applied** (production, `backfill_interview_events.py --apply`): 31 old interview-category emails were candidates; 16 events created, 6 skipped (application notices
  the primary classifier mislabelled as "Interview Cancelled", e.g. "Thank you for applying" / "Application update": a CLASSIFIER precision problem to fix separately),
  9 skipped as older repeats of the same message (Eliassen "Application Next Steps" x11). Production now has 57 events, 9 drafts (all `draft`, nothing sent), 9 events with a
  student: **student matching is now the bottleneck** (most emails name a person the roster does not know).
- **Run Now**: verified by calling the same function the button calls inside the production API container: it returned "Manual runs are disabled in production" (by design of an earlier
  developer: the run would compete with the scheduler). Now: the button writes `tmp/run_now.request`; host cron `/etc/cron.d/inboxgenius-runnow` (every minute, file-tested) runs
  `execution/run_now_watcher.py` in the cron container, which starts the SAME `process_inbox_auto.py` run under the same run lock. Dashboard shows "Run requested..." or "a run is
  already active". The duplicate "Manual Processing" card on Settings was removed. See RUNBOOK 16.
- **"In Inbox" meaning (removed tile):** the number of emails whose stored folder is INBOX (interview mail the pipeline keeps there, known-company mail, and mail not yet processed);
  the sync icon re-read Gmail. Not actionable, and Review > Inbox showed the same list, so both were removed.

### 2026-10-03 (late, 3): emails with no body / sender "Unknown": root cause found and repaired
- **Symptom (Kes):** expanding an interview on Interviews showed "No email body available" (and "from Unknown"). Production: 239 of 6,435 emails had no stored body, 163 of them sender
  "Unknown", including 17 of 33 Interview Requests.
- **Root cause:** the dashboard's IMAP "sync" (`integration/email_fetcher.fetch_and_store_emails`, behind the In Inbox sync icon and `?refresh=true` on /api/inbox/*) read the WRONG field
  names (`from`, `body`, `date` instead of `sender_email`, `body_content`, `email_date`), matched rows by the unstable IMAP sequence number, and wrote sender "Unknown", an empty body and
  today's date over stored emails. The pipeline's re-import path also never refilled a body for an existing row.
- **Fixed:** the sync is deleted (`refresh` is now ignored on all three endpoints; test proves stored emails are untouched); `import_email_to_db` fills a missing body and never overwrites a
  real subject/sender with a placeholder; the email panel is collapsible (Hide/Show) and says plainly when the text was not stored.
- **Repair:** `execution/backfill_email_bodies.py` looks each damaged email up in Gmail "All Mail" by Message-ID (read-only) and fills only the damaged fields; `--verify N` samples healthy
  rows against Gmail to see whether the sync also overwrote real emails with the wrong message. Results are recorded below once run.
- **Repair results (production, 2026-10-03 22:2x UTC):** verify sample of 60 healthy rows vs Gmail: 54 found, 0 with a different subject (the sync did NOT overwrite real emails with the wrong message;
  6 not found in All Mail). `--apply`: 81 damaged rows had a Message-ID; 31 repaired (body/sender filled), 12 not found in Gmail, the rest had nothing to fill. Including the email Kes opened (id 6238).
  **Still damaged: 208 rows, none with an interview event**: 158 stubs created by the old sync (no Message-ID, sender Unknown, empty body, all in INBOX, 50 with a classification) that cannot be
  matched by Message-ID, and 50 older rows (36 Job Alerts, 13 Spam Review, 1 Job Invite) no longer in Gmail All Mail. They inflate some counts slightly; deleting them was NOT done (destructive;
  decide with Rob/Ali).
- Tests: 766 root, 206 dashboard.

### 2026-10-03 (late, 4): "Student not identified" although the email names the student's Gmail
- **Kes' case:** a Synchrony email whose To header is the student's own Gmail was "Student not identified". Cause: (1) only forwarding headers (Delivered-To, X-Forwarded-To...) counted as an identity;
  a Gmail in the To/CC field was deliberately ignored; (2) the roster (`config/students.py`, 24 people) did not contain this student, so the name lookup (body greeting "Hi,") found nothing;
  (3) the pipeline then gave up even though the email was addressed to a real mailbox.
- **Fix** (`process_inbox_auto._identify_student`): a Gmail in To/CC now identifies the recipient; the roster is searched by that email; and when nobody knows the student, the recipient Gmail
  itself identifies them (`recipient_only_student`: username = Gmail local part, name guessed from it, e.g. "Priyan", notification goes to that Gmail; Rob sees the missing phone as a warning and
  can correct the name). The old test that asserted "To-field is ignored" encoded that earlier decision and was replaced.
- **Repair for existing events:** `execution/backfill_event_students.py` re-reads each student-less event's original email from Gmail (read-only, by Message-ID), applies the same identification,
  attaches the student and creates the DRAFT (nothing is sent). Results below once run.
- **Later the same night (precedence fix):** a first dry run showed a body name that does not fit the delivery Gmail ("Lead Business", a job title that the roster auto-add had turned into a
  student) winning over the Gmail. New order when a delivery Gmail exists: its assigned-Gmail owner, a student whose personal email it is, roster by email, the body name ONLY if it appears in the
  Gmail, the one known student whose name appears in the Gmail, else the Gmail itself (greeting name used when it fits, e.g. "Kenya" in kenyasbogans@). `add_new_student` now refuses job-title
  words. The first dry run had also appended students to `config/students.py` on the server (the pipeline's name lookup auto-adds by REWRITING that file); the backfill now disables that step.
  NOTE: every deploy overwrites the server's `config/students.py` with the repo copy (auto-added roster entries vanish at each deploy and come back at the next pipeline run): the roster should
  live in the database; not changed here.
- **Backfill applied (production):** 43 student-less events were identified (30 by an existing student, 11 by the delivery Gmail alone, 2 by the roster), 5 emails are no longer in Gmail; 43 drafts
  created, none sent. Students: 7 -> 19 (named from the Gmail or greeting, no phone for most; Rob corrects names/phones). Production now has 52 of 57 events with a student.

### 2026-10-03 (late, 5): guessed students must be verified by Rob; greeting name is the display name
- **Kes' rule:** a Gmail is just a username the person chose, and a candidate may have changed their email, so names the pipeline guesses must be flagged for verification (Rob traces the
  original in the roster sheet/Drive), and a greeting like "Hi OMOLOLA" should surface as the candidate's name. **Precedence now:** the delivery Gmail is the identity KEY (the mailbox the email reached,
  the student's username); the greeting/classifier name is the DISPLAY name when plausible (`plausible_person_name`: no job-title/greeting words; ALL-CAPS "OMOLOLA" becomes "Omolola"); otherwise a guess from
  the Gmail. Roster / existing-student matches are trusted.
- **Verification:** new table `student_verifications` (create_all, migration 006): a pipeline-created student gets an `unverified` row (basis `greeting_name` | `gmail_guess`, the guessed name and
  the evidence "delivered to ...; greeting names ..."). The approval screen shows an orange "Verify who this student is" box (name, phone, personal email, "Confirm this student"); Approve is hidden/blocked
  until confirmed, and the API refuses to approve an unverified student. Confirming also repoints the student's waiting drafts to the corrected personal email. Interviews shows "Verify the student first".
  Students with no verification record (roster, earlier students) count as verified. Verified in a real browser against local Docker (form -> confirm -> Approve appears).
- Production: `backfill_event_students.py --refresh-names` flags the 12 students the backfill created and improves their names from each one's latest email greeting (results below).

### 2026-10-04: Ali's answers -> roles instead of people, stale-draft alert, pilot gate, Shemika removed
- **Ali (2026-10-03):** pilot = 3 notices the approver approves by hand, then everyone; callbacks: Rob for now, answered within one business hour in working hours; DO NOT write her name into the system:
  approver, callback owner and escalation target are ROLES that get assigned (the work will move to recruiters, with Rob or Jackie as the approval step until trusted); stale drafts go to Jackie as the
  ESCALATION role (not to the approver, who is the one who has not acted); test phone/email = Kes's own. **Kes:** Jackie's address, 2 business hours is enough, escalation role = only Jackie, remove Shemika's
  email everywhere, call test Monday 2026-10-05 09:00 EDT with his phone, students have consented.
- **Built:** `execution/roles.py` + tables `role_assignments`, `alert_log` (migration 007); `RobAlerts` -> `RoleAlerts(db)` (each alert resolves its role's address at send time; nobody assigned = logged, never lost);
  every person's name removed from code, comments and tests (a test now fails if a person is named in execution/, the API or config/students.py); the hardcoded CC list (Shemika + Jackie) is gone: copies go
  to the escalation role; `execution/business_hours.py` (Mon-Fri 09-17 America/Chicago by default, an ASSUMPTION Kes/Ali should confirm); `execution/stale_draft_alerts.py` + host cron `execution/crontab.stale`
  (every 15 min; once per draft; silent baseline on first run); Settings page "Roles and alerts" card (3 roles + pilot limit); pilot gate on approve (limit 3 while escalation is enabled).
- Renamed `rob_no_response*` identifiers; the DB columns `rob_day1_alert_at` / `rob_ended_alert_at` keep their names (create_all cannot rename columns).
- Production assignment of the escalation role (Jackie) is DATA set after deploy, not code. Approver and callback owner are unassigned until Kes enters them (alerts are logged until then).
- **Test calendar (GHL: ONE call per number per day):** Mon 5 Oct 09:00 EDT greeting + confirmation; text and email tests the same day; wrong person, voicemail and STOP on three separate days (or a second number).

### 2026-10-04 (2): callback flow built; roles assigned
- Roles in production (settings data): escalation = jackie@colaberry.com; approver AND callback owner = robelyn@colaberry.com (Kes). Business hours confirmed Mon-Fri 9-17 Central. A callback not made
  within one business hour alerts the escalation role (Kes confirmed). Kes: callback is made by a person (no AI call back); the callback owner is emailed and the interview shows it under review.
- **Built:** `GhlClient.voice_ai_agent_calls`, `execution/callbacks.py`, table `callback_requests` (migration 008), API `/api/callbacks` (+ `/{id}/done`), the review-queue's `callbacks`, a "Callbacks waiting"
  section and a red banner on the student's cards in the approval screen, "Callback needed" on Interviews, a dashboard banner count, host cron `execution/crontab.callbacks`, `add_business_minutes`.
- **Found in GHL (read-only):** the inbound AI Receptionist agent is `6a97318a65c4b663f8b154a1` (153 calls, actions CALL_TRANSFER and KNOWLEDGE_BASE, extractedData keys name/email/address/otherDetails);
  the outbound agent is `6ac01cf1c3f750053ed53d60`. None of the 153 receptionist calls mentioned an interview, so detection is UNPROVEN until Kes makes a test callback.
- Kes' GHL action ("Update contact field" on the receptionist): the call's date/time is NOT something the agent can extract (the caller never says it); the call log already has it. See the guidance given to Kes.

### RESUME HERE (state at the end of the 2026-10-02 session; read this first after a compact)

**One-line state:** the student-notification escalation (call + text + email, follow-ups until acknowledged) is BUILT, TESTED
and DEPLOYED but SWITCHED OFF. `master` == `origin/master` == server (`.deployed_commit`). No GHL credentials are on the server.
Nothing can reach a student.

**Where everything lives**
| What | Where |
|---|---|
| Design, decisions, schedule, settings, checklist | `directives/student-notification-escalation.md` (read first) |
| GHL facts: verified / unverified / what the kit lacks | `docs/ghl-conversations-and-calls.md`; local skills `.claude/skills/ghl-integration` and `ghl-conversations-calls` (`.claude/` is git-ignored) |
| Voice agent prompt + GHL setup checklist | `docs/voice-agent-outbound-interview-prompt.md` |
| Use cases and user stories (17 UCs) | `docs/use-cases.html`; published artifact https://claude.ai/artifact/FRzyZVP1uBnsvMPEViEZiw (private) |
| Code | `execution/escalation_schedule.py`, `escalation_engine.py`, `notify_channels.py`, `ghl_client.py`, `ghl_conversations.py`, `reply_analysis.py`, `notification_tick.py`, `area_code_timezones.py`; API routes in `services/dashboard/api/routers/notifications.py`; tables `notification_sequences`, `notification_attempts`, `reply_analyses`, `notification_inbound` |
| Daily health check | `execution/health_check.py` (host cron `/etc/cron.d/inboxgenius-health`, 07:30 UTC; Monday all-clear email) |

**Decisions (who decided)**
- Ali: all three channels (email, text, voice call); student must acknowledge; keep after them until they do; Rob approves the first send;
  confirm with Rob what he does today BEFORE switching on; share the Cora number budget; delete the 20 non-interview rows (done);
  quiet hours 9 PM-8 AM in the STUDENT'S time zone for calls and texts (area-code fallback, Central last); email any time;
  day 1 as designed, then one call+text+email per day for up to 3 more days; telling Rob does not stop the sequence;
  AI reading of replies in SHADOW mode for 2 weeks (to 2026-10-16) before it may stop anything.
- Kes: `master` is the single source of truth (work on a short-lived branch, verify, merge, deploy from master); the voice agent is
  GHL Voice AI; the trigger fields are `interview_notification` (call), `Support Issue Ticket #2` + `Message:` (email),
  `Support issue Ticket #4` (text); a changed value re-triggers a workflow, an identical one does not; use the `.env` key;
  adhere to GHL's rules; the Cora repo is READ-ONLY reference (never edit it).
- Claude (Kes accepted): calls end at 8 PM (GHL's own window) and there is no 2nd call on day 1 (GHL allows one call per number
  per day, 14 in 14 days); each attempt's value is unique; own SMS budget 150 of the shared 999 (`NOTIFY_SMS_DAILY_SEGMENT_CAP`);
  exact-phone contact match; a connected call with no readable student words never stops a sequence.

**Verified live (read-only, 2026-10-02):** the four trigger fields exist (large text); the Voice AI call-log scope works with `GHL_API_KEY`
(152 live logs); `GHL_CONVERSATIONS_API_KEY` works; contact phone is E.164; exact-phone lookup works; our `human:` parser kept the
agent's words out. **Test call DONE 2026-10-02 (`execution/ghl_test_call.py --email ... --send`, Kes's own contact): the value reached the
agent, correct facts spoken, reference not read, "yes" captured as a `human:` line, call log readable (agent id, duration, transcript).**
Not yet seen: voicemail, wrong person, STOP request; agent greeted "Hi Kes" (own greeting setting) instead of verifying the name.

**Open / next (in order)**
1. DONE 2026-10-02 (see above). Next: test voicemail / wrong person / STOP once; then tag action for STOP. Original step: check the call log
   (agent said the right facts; did not read "Reference"; a "yes" shows as a `human:` line). This also answers how the field value
   reaches the agent (UNVERIFIED: merge syntax `{{contact.interview_notification}}` in the Voice AI prompt).
2. Create the new outbound Voice AI agent from the prompt doc; confirm the existing number is an eligible From number; set
   `GHL_VOICE_AGENT_ID`; add an action so a STOP request tags the contact `do not call`.
3. Kes confirms with Rob what Rob does today; get `ROB_ALERT_EMAIL`; confirm students opted in to texts/calls; Cora's real usage.
4. Shadow rehearsal on the server (`NOTIFY_CHANNEL_*=ghl`, `GHL_WRITE_MODE=shadow`), read the `[GHL shadow]` log lines, then a human
   approves the three `GHL_WRITE_*` switches and `NOTIFY_ESCALATION_ENABLED`; install the 5-minute host cron for `notification_tick.py`.
5. Not built yet: alert Rob when a draft is waiting (Claude's idea, Ali has not agreed); alert Ali when a draft sits unapproved.

**How to work here (hard-won)**
- Tests: `python -m pytest tests -q --no-cov` (root, ~701) and `python -m pytest services/dashboard/tests -q --no-cov` (~191, needs `bcrypt`).
- Deploy: branch from master -> tests -> merge fast-forward -> `git push origin master` -> delete branch -> `scripts/deploy_hetzner.sh`
  (it refuses 00-11 minutes past an even UTC hour). Then the sync check in CLAUDE.md (tree clean, master == origin, deployed == master).
- Shell quoting: long heredocs with quotes in the Bash tool break. Write files with the Write tool, or write a patch script to the
  scratchpad and run it. Never print secrets (CLAUDE.md); check `.env` values with `grep -c "^KEY=.\+"`.
- A health-check run EMAILS Kes unless `ALERT_EMAIL_TO=` is blanked (`docker exec -e ALERT_EMAIL_TO= ...`).

### 2026-10-02 update

- **Deleted the 20 non-interview events** (Job Invite 12, Job Alert 6, Application Notification 1,
  Other 1) and their 3 notification drafts from production, as Ali and Kes approved. One guarded
  transaction that rolls back unless it removes exactly 20 events and 3 drafts; checklist rows: none.
  The emails and their classifications are untouched. Backup of the 20 rows (company, role, sender
  domain, subject, category; no bodies): `tmp/non_interview_events_export_2026-10-02.csv` (git-ignored).
- **New live proof from overnight runs (#165–#170, all success):** 5 new interview events, all labelled by
  the sub-classifier (0 fallback), including the **first live Phone Screen** (event 54). The "no event for
  a Job Invite" gate fired live. The review queue is at 15 pending (7 + 8). One student now has an
  assigned Gmail (header read worked and the name matched). 3 of the 5 events had a student; the Phone
  Screen was one of the 2 without, so it got no draft (so sub-type drafts are still unproven live).
  The daily health check ran at 07:30 UTC: HEALTHY.
- **Student notification design approved** by Ali (2026-10-02) with one change: day 1 as designed, then
  one call + text + email daily for up to 3 more days until acknowledged; telling Rob does not end the
  sequence. Quiet hours 9 PM–8 AM in the student's own time zone (area-code fallback, Central last),
  calls and texts only. Kes approved the schema change and chose: daily follow-up at 9 AM student-local;
  "3 days" = days 2–4; held attempts released at 8 AM with a 3-hour same-channel minimum gap.
  Spec: `directives/student-notification-escalation.md`. **Not built**: Ali requires Kes to confirm
  with Rob first, plus Twilio details, Cora's usage and student opt-in (checklist in the directive).

- **Student notification escalation built (Kes: "build it for now"), deployed OFF.** New:
  `execution/escalation_schedule.py`, `escalation_engine.py`, `notify_channels.py`, `reply_analysis.py`,
  `notification_tick.py`, `area_code_timezones.py` (414 US/Canada area codes, generated once from the
  `phonenumbers` library, so no new runtime dependency); models + migration `003` (3 NEW tables only,
  because prod's `create_all` cannot add columns to existing tables); `routers/notifications.py` (Approve
  starts it when `NOTIFY_ESCALATION_ENABLED`; public email "I got this" link; Rob's status/close; secret-
  protected `/inbound/reply`); health check now also flags failed attempts. 103 new tests (root suite 574,
  dashboard API suite 191 incl. 12 new).
  **Safety:** off unless `NOTIFY_ESCALATION_ENABLED`; every channel defaults to `dry_run` (recorded as
  `dry_run`, never `sent`); the AI reply reader runs in shadow mode until 2026-10-16 and can only stop a
  sequence when also set to live. Nothing can reach a student yet.
  **Researched how GHL/Cora delivers each channel** (cora-recap-engine code, not the GHL dashboard): email =
  GHL fields Ticket #2 + Message → "AI Agent - Send Email"; SMS = Ticket #4 → "AI Agent - Send SMS"; **phone
  call = no ticket field at all, a Synthflow "Make Call" webhook** (details and four risks in the directive:
  Cora's SMS ledger does not count our texts; do not reuse Cora's Synthflow agent or its voicemail engine
  would start chasing students as leads; Synthflow agents do not read keypad presses; writing Ticket #4
  bypasses Cora's safeguards). GHL and Synthflow adapters are NOT built; selecting them fails loudly.
  Nothing was enabled or sent. Still gated on: Kes confirming with Rob, Rob's address, Twilio/GHL/Synthflow
  access, Cora's usage, student opt-in.

- **GHL channels built (Kes: "build it", voice field is `interview_notification`).** New
  `execution/ghl_client.py` and the `ghl` channel in `notify_channels.py`, following
  `.claude/skills/ghl-integration/KIT.md`: email = Ticket #2 (subject) + `Message:` (body); SMS = Ticket #4;
  call = `interview_notification`. Shadow by default (live needs `GHL_WRITE_MODE=live` AND
  `GHL_WRITE_SHADOW_LOG_ONLY=false` AND `GHL_WRITE_NOTIFY_FIELDS=true`), writes by field UUID, retries incl.
  GHL's disguised 401 timeout, rate limiter, Do-Not-Disturb + opt-out-tag check before every send, a student with
  no GHL contact FAILS visibly (health check) instead of skipping, every value unique per attempt (GHL fires on a
  field CHANGE), text gate (no links, 3+ words, curly quotes normalised, segment cap) and our own daily SMS
  budget (default 150 of the shared 999, counted from our real sends since midnight Pacific; deferred texts move
  to 08:05 PT next day). Engine now handles `deferred` and `skipped` results. 52 new tests (root 627, dashboard
  191). Corrected the API settings note: API and tick both read `/repo/.env`. `.env.example` updated.
  **Not verified (written in the directive, must be answered in GHL before live):** what the voice workflow does
  with the field value, that a changed value always re-triggers, how call results come back, Call DND/hours,
  forwarding of student SMS replies to our webhook, and that each student exists as a GHL contact.
  Still deployed OFF; no credentials on the server, nothing can be sent.

- **Kes answered the five GHL questions; built the reading side.** (1) The call value now carries the interview
  facts (type, company, position, date, time, format, contact, interviewers) for the voice agent. (2) A changed
  value re-triggers the workflow, so every attempt's value differs (step tag + Ref). (3)(4) Replies and calls are
  READ from the candidate's GHL Conversations with the second token: new `execution/ghl_conversations.py`, client
  methods `conversations_for_contact` / `conversation_messages` / `message_transcription`,
  `escalation_engine.poll_replies()` (run by `notification_tick.py`), new table `notification_inbound` (one row per
  GHL message id, so each is handled once; migration 004). Echoes of our own emails are filtered; calls that did not
  connect are recorded, not read; a missing transcript is retried for 15 minutes. **Only the student's side of a call
  transcript is ever analysed, and only once `GHL_CALL_STUDENT_MEDIA_CHANNEL` is set**; until then a finished call
  only alerts Rob. (5) Students exist in GHL; contact lookup now needs an EXACT phone match (a near match could have
  sent one student's details to another; two exact matches are refused). Found and fixed a design bug on the way: one
  student with two open notices would have recorded the same reply twice and crashed the poll, so open sequences are
  now grouped by GHL contact. 50 more tests (root 677, dashboard 191). Still OFF, no credentials on the server.

- **Read the Cora repo (read-only; nothing there changed) for the open GHL questions and acted on it.**
  Findings: call status/duration live at `meta.call` (connected = completed + minimum length); GHL native
  transcripts are OFF on this account and the Whisper fallback has no speaker labels, so a student-only transcript is
  not available today; outbound Synthflow calls are not TYPE_CALL messages in GHL; contact phone is E.164 and the
  contact search is free-text; `startAfterDate` is a cursor and `lastMessageType` hides calls behind notes.
  Changes here: `ghl_conversations.normalize` reads `meta.call` and adds `duration`; `is_connected_call` is a positive
  test (default 10 s, `NOTIFY_CALL_MIN_SECONDS`); a connected call with no transcript now ALERTS Rob instead of being
  recorded silently. 13 more tests (root 690). New tracked reference `docs/ghl-conversations-and-calls.md` (verified,
  unverified, and what the base kit lacks) and a local skill `.claude/skills/ghl-conversations-calls/` (`.claude/` is
  git-ignored in this repo, hence the tracked doc).

- **Kes: the voice agent is GHL Voice AI (screenshot of its logs); "use the key in .env, adhere to GHL rules, I added
  voice-ai-dashboard.readonly, test it".** Read GHL's docs and TESTED READ-ONLY against the live account (no field was
  written, no call placed; no secret printed): the four trigger fields exist and are large-text; the call-log scope works
  (152 live logs); conversations token works, contacts token refused there; contact `phone` is E.164; exact-phone lookup
  returns the right contact. **GHL rules applied:** calls only 8 AM-8 PM in the contact's zone (our call quiet hours are now
  8 PM-8 AM; texts stay 9 PM-8 AM) and ONE call per number per day (the +2h call on day 1 is dropped, plan is now 15
  attempts: 4 calls over 4 days, well under 14 in 14 days); GHL checks neither consent nor DND, so ours stay. **Call reading
  rebuilt on Voice AI call logs** (`GhlClient.voice_ai_call_logs`, `ghl_conversations.human_words/reached_a_person/
  fetch_new_calls`): only `human:` lines reach the AI, a call counts only if long enough (default 10 s) and the student
  spoke; `GHL_VOICE_AGENT_ID` limits it to the outbound agent. Removed the Conversations-transcript call code and
  `GHL_CALL_STUDENT_MEDIA_CHANNEL`. Verified our parser on real transcripts (no agent sentence leaks into the student's
  words). API tests now freeze the clock (they would have flipped after 8 PM Central). Tests: 701 root, 191 dashboard.
  Still OFF; no credentials on the server; NOT done: writing `interview_notification` (needs a test contact) and how the
  value reaches the agent's prompt.

- **Outbound voice agent prompt written** (Kes supplied the AI Receptionist prompt to adapt): `docs/voice-agent-outbound-interview-prompt.md`.
  Same section style and rules (provided information only, no assumptions, no verbatim repeats, "a team member will reach out"),
  new goal (verify the person, tell them the interview details, get a "yes"), plus VOICEMAIL (no interview details left),
  STOP REQUEST, wrong-person handling, and an INTERVIEW CALLBACKS section for the inbound receptionist. The app's
  `interview_notification` value is now FACTS ONLY (`Attempt: ...; Candidate first name; Interview details; Reference`); the
  instructions moved into the prompt so the two never contradict. Not yet configured in GHL. Use cases and user stories page
  rewritten to 17 use cases (new: UC12-UC17 for the notification feature): `docs/use-cases.html` + the published artifact.

### End-of-day summary (2026-10-01)

| Item | Result | Evidence |
|---|---|---|
| Sub-classifier called in the live path | Fixed, proven once on live mail | run #156: `Re: JD` → Interview Request 0.9; backfill re-checked all 27 existing events (all really first-round) |
| "Other" no longer permanently deleted | Fixed, proven | runs #156–#158: `quarantined=`, 0 "permanently deleted" lines |
| Approvals queue (< 0.70) | Fixed, proven | run #158 queued 7 rows (approvals 0 → 7) |
| Header-based student matching | Cause fixed (headers never captured), **not yet proven** | 0 students with an assigned Gmail; no interview mail arrived after the fix |
| Student identity rule, event gate (no events for Job Invite/Alert) | Built, **tests only** | no interview events were created in runs #157–#158 |
| Drafts follow the real sub-type | Built, **tests only** | needs a non-"Interview Request" email |
| Notification send path | **Proven in production**: test email to Kes's own address delivered | BCC and the dashboard Approve button were *not* exercised (BCC turned off for the test) |
| Daily health check | Deployed; first scheduled run 07:30 UTC 2026-10-02; Monday all-clear starts 2026-10-05 | `/etc/cron.d/inboxgenius-health` |

**Facts established along the way (not obvious from the code):**
- `origin` (`KesetebirhanDelele/AI-inbox-Manager`) is a **standalone private repo, not a GitHub
  fork** (`fork: false`, created 2026-09-17), seeded with the previous developer's history
  (76 commits by `Ojobo1800`, 39 by Kes). It is not linked to Ali's org repos
  (`Colaberry_InboxGenius`). Ali's "push what you deployed" request: his exact words did not
  name a repo; Kes believes he meant Kes's own GitHub account (which he monitors), hence the
  `master`-is-deployed workflow below. Still unconfirmed with Ali.
- Drafts live **only in the dashboard** (`notification_drafts`); nothing creates a Gmail draft.
  Dashboard Approve sends by SMTP via `send_notification.send_email`. Whether Rob uses
  Approve, or sends from his own Gmail/WhatsApp, is an open question to Ali.
- `process_runs.spam_deleted` counts mail *moved to Spam Review*, not deleted; dashboard
  labels now read "Quarantined" (column name unchanged, renaming needs a migration).
- The model returns confidence 0.0 for ordinary junk "Other" (740 of 810 live rows), so
  "Other" at exactly 0.0 is excluded from the approvals queue.
- The 7 rows run #158 queued were all noise at 0.65 (4 bare LinkedIn job links forwarded by
  students, 3 identical Skool reminders) → sender rules added (see "Queue noise" below). Those
  7 rows are still pending for Rob to clear; they were not touched.
- Use-case / user-story review page published as a private Claude artifact
  (https://claude.ai/artifact/FRzyZVP1uBnsvMPEViEZiw), 11 use cases with per-story status.
- Reply to Ali was drafted by Claude and sent by Kes himself.

**Open items (all waiting on a decision, none blocking):**
1. Ali: does Rob send via the dashboard Approve button, or from Gmail/WhatsApp? (If Gmail:
   build "save draft into the interview inbox's Gmail Drafts folder".)
2. Ali: which repo should the code live in for review (Kes's account vs Colaberry org)?
3. Kes/Ali: delete the 20 old non-interview rows from `interview_events`? (Not deleted.)
4. Rob to clear or reject the 7 pending approvals; one real Approve click is still untested.
5. Quarantine has no clean-up schedule and no "how often was Other wrong" measure yet.
6. Header names were never verified against real forwarded mail (the probe was blocked).


**Why:** Ali's review. Production DB (checked 2026-10-01, read-only) showed 50
interview events: 30 `interview_request`, 20 `other`, zero phone/client/technical/
cancelled/rescheduled/job-machine; `approvals` table empty; 5/5 students with no
`assigned_gmail`, 44/50 events with no student; every draft used
`interview_request_first`. Cause: `subclassify_interview` had no caller in the live
path (only the unused orchestrator `process_interviews.py` imports it), and
`parse_email_message` never captured headers, so `resolve_student` had nothing to
read. Separately, the spam second pass `UID EXPUNGE`d "Other" mail (≈45–105
deleted/day in the cron log).

**Changes:**
- `execution/process_inbox_auto.py`: new `_build_sub_classification` calls
  `subclassify_interview` for interview-related categories (fallback to the old
  category mapping on any failure; result tagged `sub_type_source` in
  `raw_extraction`). New `_resolve_assigned_gmail` stores the header-derived
  assigned Gmail on the student. `_run_spam_review_pass` now moves confirmed
  "Other" to a new `Quarantine` label (never deletes); a failed re-classification
  leaves the mail in `Spam Review`.
- `execution/fetch_emails.py`: `parse_email_message` now returns `headers`
  (recipient-related headers only, all values) and `to_addresses`.
- `execution/resolve_student.py`: also reads `X-Forwarded-For`, `X-Gm-Original-To`.
- `execution/notify_student.py`: `_build_classification_for_draft` takes the
  sub-classification so the template follows the real sub-type.
- `tests/execution/test_subclassify_and_quarantine.py`: 19 new tests.
- `RUNBOOK.md` §3, §9: corrected (it claimed a sub-classify step that never ran).

**Findings, not changed:**
- The dashboard counter `process_runs.spam_deleted` counts mail *moved to Spam
  Review*, not deleted; it overstates deletions and is now just a quarantine count.
- 134 "Other" rows at confidence 0.0: the model itself returns 0.0 for Other
  (`requires_manual_review` true in 740/810 live rows), so confidence is not a
  usable signal for Other. 21 are migration backfill rows.
- 20 events are non-interviews (Job Invite 13, Job Alert 5, ...) created via the
  known-company safety path; "Interview Confirmation" and "Offer" are not in
  `INTERVIEW_RELATED_CATEGORIES`, so they use the category fallback.
- Real forwarded-header names were NOT verified against live mail (probe denied);
  confirm `assigned_gmail` fills in after the first deployed runs.
- 18 tests in `test_log_interview.py` fail on a clean tree too
  (`No module named 'models'`) — pre-existing, unrelated.

**Follow-up, same day (deployed 13:50 UTC, run #156 verified):** sub-classifier
called (`Re: JD` → Interview Request 0.9), header resolution worked, spam pass
quarantined 4 and deleted 0. One open question: that email's header Gmail
(`sehrishkhan…`) was written onto the student the body-name lookup picked
("Alisha") — the two signals disagree; drafts are human-reviewed, nothing is
auto-sent, but decide which signal wins.

**Added after deploy:**
- Approvals queue: `needs_human_review` / `_queue_for_review` in
  `process_inbox_auto.py` write one pending `Approval` row per email when
  confidence < 0.70, except "Other" at exactly 0.0 (the model's normal answer for
  junk; including it would queue ~800/week). 8 more tests.
- `execution/backfill_sub_types.py` (+ tests): re-labels existing interview events
  with the real sub-classifier. Dry-run by default; old value kept in
  `raw_extraction.previous_sub_type`.

**Queue noise + health heartbeat, same day:** run #158 proved the review queue on real mail
(7 queued) but all 7 were noise at a flat 0.65: 4 bare LinkedIn job links forwarded by
students and 3 identical Skool "1 event happening tomorrow" reminders. Added two
deterministic sender rules in `pre_classify_by_sender` (skool.com → Other; subject that is
just a `linkedin.com/jobs/` URL → Job Alert) so they never reach the model or the queue.
The queue threshold is unchanged (0.70; "Other" at exactly 0.0 still excluded). The health
check now also emails an "all clear" every Monday: a healthy run is silent, so without it a
dead check looks the same as a healthy one. 10 more tests (499 pass).

**Branch cleanup + dependency caps, same day:** `feat/hetzner-deployment` and
`chore/cap-major-version-pins` were archived as annotated tags (`archive/*`) and deleted
locally and on `origin`; `master` is the only branch. The dependency-cap commit (5a75651)
was re-applied to `master` through the new workflow (branch → tests → merge). Two changes
from the original commit: `requirements.phase1.txt` stays deleted (removed earlier as a
duplicate), and the **openai cap was corrected from `<2.0.0` to `<4.0.0`** because the cron
container actually runs openai 3.21.0 (google-api-python-client 2.200.0 is fine under
`<3.0.0`); `<2.0.0` would have silently downgraded production at the next image rebuild.
RUNBOOK §4c now has the explicit revised git workflow and §16 a changelog entry.

**Workflow change, same day (Kes):** `master` is now the single source of truth: work on a
short-lived branch, verify, merge into `master`, push `master`, delete the branch, deploy
from `master`. Reason: Ali reviews Kes's GitHub account. `CLAUDE.md` rule rewritten (it
previously said `feat/hetzner-deployment` was the working line); `RUNBOOK.md` §4c updated
(the "never push to `master`" rule is lifted; checked that all four workflows are disabled,
so the only side effect is Vercel rebuilding the frozen fallback frontend). `master` was
brought up to date by fast-forward from `feat/hetzner-deployment`.

**Process rule, same day:** added "Keep git, the repo and the server identical" to
`CLAUDE.md` at Kes's request (sole developer): no new branches without asking, any
stray branch is merged/pushed/deleted locally and on `origin` in the same session, and
every code task ends by confirming clean tree, local == origin, and
`.deployed_commit` == `HEAD`. Applied immediately: the throwaway branch
`fix/subclassify-quarantine` (created without asking; 0 unique commits) was deleted
locally and on the fork.

**Fourth change, same day (health check):** new `execution/health_check.py` (+ 15
tests, `directives/pipeline-health-check.md`, `execution/crontab.health`). Daily,
read-only; emails only when an invariant breaks (see the directive). Installed on the
server as a host cron file, so no image rebuild. Full suite: 489 passed, 0 failed (the
18 earlier `test_log_interview.py` failures were an import-path problem that goes away
when the new test files put the dashboard `models` module on the path first; still
order-dependent when that file runs alone).

**Third change, same day (student identity, event noise, counter label):**
- **Identity rule (headers win, conflicts flagged):** new `_identify_student`. A
  header Gmail already recorded as a student's assigned Gmail picks that student
  even if the body names someone else. Otherwise the name lookup is used and the
  header Gmail is saved only if the student's name appears in it and it does not
  overwrite a different Gmail; a mismatch is logged ("Student identity
  unconfirmed") and nothing is saved. Production data fix: the Gmail wrongly saved
  on the "Alisha" record by the first deploy was cleared.
- **Event noise:** `creates_interview_event` — a Job Invite/Job Alert/Application
  Notification from a known interview company is still kept in the inbox but no
  longer creates an `InterviewEvent`. Existing noise rows (20) were NOT deleted.
  "Offer" no longer creates an event either.
- **Counter label:** `process_runs.spam_deleted` actually counts mail moved to
  Spam Review. The column keeps its name (renaming needs a migration); dashboard
  labels now say "Quarantined".
- 17 more tests (43 in `test_subclassify_and_quarantine.py`).

**Deferred:** the 20 existing noise events (decide: delete or keep); pushing to the
Colaberry GitHub org (needs Kes/Ali decision on the destination repo); Gmail drafts
for Rob (waiting on Ali's answer on how Rob notifies students).

---

## 2026-09-29 (late night) — Addressing the "small gaps" (#6) + no more pushes to master

> **Superseded 2026-10-01:** `master` is now the working line and what is deployed (see the
> 2026-10-01 entry and RUNBOOK §4c). Checked first: all four GitHub workflows are disabled,
> so a push cannot start processing; the only side effect is Vercel rebuilding the frozen
> fallback frontend.

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
  `.deployed_commit` on the server, and **removes files that were deleted in git
  since the last deploy** (tar only adds/overwrites, so deleted files would linger
  and could mask a broken import; a strict `is_safe_relpath` guard protects
  `.env`, `.env.compose`, `config/gmail_*`, `logs/`, `tmp/`). 42 tests in
  `tests/deploy/test_deploy_script.py` (window rule incl. octal-looking "08"/"09",
  path guard, `--help`, bad option, no secrets).
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
- Laptop check: the old Windows tasks `ColaberryEmailProcessing` and
  `InboxAI_StartAPI_OnLogon` do not exist on this machine, so nothing can
  double-process the mailbox from here.

**Stale-file / wording cleanup (docs + deletions, no runtime effect):**
- **Deleted** (verified zero references from code, workflows or other docs; all
  recoverable from git history): `scripts/update_schedule.ps1` (only the removed
  Settings save path called it), `scripts/setup_hourly_task.bat` + `.ps1`
  (would recreate a second, laptop-based scheduler → double-processing risk),
  `services/dashboard/api/railway.json`, `services/dashboard/QUICKSTART.md`,
  `services/dashboard/FULLSTACK_QUICKSTART.md` (Railway-era).
- **Rewritten:** `services/dashboard/README.md` (327 stale lines → a short,
  accurate README; states that the stakeholder role isn't enforced).
- **Reworded:** Railway comments in `api/database.py` (behaviour unchanged),
  the deprecated-infra sentence in `CLAUDE.md`, RUNBOOK §4 (laptop task history)
  and §14 (stale-file list → what was removed, what stays until Render is
  retired), RUNBOOK §4c deploy procedure (now the deploy script; no master pushes).
- **Bannered as obsolete** (kept for history): `docs/AUTOMATED_EMAIL_PROCESSING.md`,
  and a production note in `docs/email-integration-setup.md` (Option 2, Windows).
- **Deliberately kept until Render is retired:** `render.yaml`,
  `api/Procfile`, `api/runtime.txt`, `api/Dockerfile.prod`,
  `.github/workflows/deploy_backend.yml`.

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
- **No PR needed** — solo project. PR #3 was opened, then dropped: the branch was
  fast-forwarded into `master` once (`24443cf`; GitHub marked PR #3 merged
  automatically). **Superseded later the same night:** to avoid triggering
  Vercel/Render rebuilds of the fallback stack, nothing more is pushed to `master`
  until the old stack is retired — work continues on `feat/hetzner-deployment`
  and is deployed with `scripts/deploy_hetzner.sh` (RUNBOOK §4c).
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
2. **Verify the new fetch code live** — ✅ *normal path verified 2026-09-30:* run
   #137 started 00:00:02 UTC (on time), 39 emails / 23 moved / 130 s, `success`,
   0 fetch errors, 0 reconnects, 0 alerts, no other errors — the first run on the
   deployed `5b400e1` code with the 150 cap. ⚠️ The **reconnect path itself has
   still not been exercised against real Gmail** (it only triggers if Gmail drops
   the connection); it is covered by fake-based tests. Original note: the 00:00
   UTC run (2026-09-30) is the first
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
6. ~~Known small gaps~~ — **addressed 2026-09-29 (late night, see the section
   above):** deploy-window rule is now enforced by `scripts/deploy_hetzner.sh`;
   crashed/partial runs now write a `ProcessRun`; `db_storage_days_remaining`
   removed; stale Windows/Railway wording fixed, Railway-era files deleted, dashboard
   README rewritten. Leftovers tied to item 5 (delete with Render): `render.yaml`,
   `Procfile`, `runtime.txt`, `Dockerfile.prod`, the disabled workflows.

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

> **Update 2026-10-01: done.** Re-applied to `master` by cherry-pick (conflict on the deleted
> root `requirements.phase1.txt` resolved by keeping it deleted). **The `openai` cap was
> corrected to `<4.0.0`**: the production cron container actually runs openai **3.21.0**
> (google-api-python-client 2.200.0), so `<2.0.0` would have silently downgraded it at the
> next image rebuild. Branch archived as tag `archive/chore-cap-major-version-pins`.

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

### 2026-10-02 (evening): live voice test + test script
- Built `execution/ghl_test_call.py` (dry run by default; `--send` writes ONLY `interview_notification` on one exact-match contact after the
  DND/opt-out check; `--readback` prints that contact's Voice AI call logs). Added `GhlClient.search_contact_by_email` (exact match) and the
  `GHL_FIELD_INTERVIEW_NOTIFICATION` env alias. Tests: `tests/execution/test_ghl_test_call.py`.
- Ran it live on Kes's own contact: the GHL workflow fired, the agent called, read the facts correctly, "yes" was captured. Escalation still
  OFF; no GHL credentials on the server. `GHL_VOICE_AGENT_ID` not needed for triggering; only for filtering call logs. Also removed the
  "adapted from the receptionist" explanation from the prompt doc.
- Follow-up: test voicemail, wrong person and STOP; fix greeting so it asks "Am I speaking with ...?".
