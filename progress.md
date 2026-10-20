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

## RESUME HERE (state at the end of Monday 2026-10-12; read this first after a compact)

**One-line state:** InboxGenius is live on Hetzner (`master` == `origin` == server; check with `git rev-parse --short master` and `/opt/ai-inbox-manager/.deployed_commit`). Email classification, folders, the review screens, the Dashboard and Reports are all LIVE. The student-notification flow (call + text + email via GHL, follow-ups until the student confirms) is BUILT, deployed and ON IN SHADOW: escalation enabled, channels `ghl`, NO `GHL_WRITE_*` switch set, so the app only LOGS what it would send and nothing reaches a student through it. The old one-email Approve is OFF. On 2026-10-12 Kes ran a one-contact LIVE mock test (call, text, email) on three staff contacts through `execution/ghl_test_call.py` (it turns the live switches on for that one process only): the texts were delivered and one call was placed; see "Where we are in the testing". Detail: the dated log right below this block, `directives/student-notification-escalation.md`, `docs/test-plan-student-notifications.md`, `docs/voice-agent-outbound-interview-prompt.md`, `docs/use-cases.html` (artifact https://claude.ai/artifact/FRzyZVP1uBnsvMPEViEZiw, updated 2026-10-12 with a 4-minute walkthrough tab).

### State of production (2026-10-12 night)
| Area | State |
|---|---|
| Mailbox folders | Follow Ali's "Email Management - Labels" workbook (22 folders) + Needs Review / Quarantine / Spam Review. "More Information Request" keeps its name (3,000+ mails). Gmail "Other" mail goes to Spam Review then Quarantine; nothing is ever deleted (the manual Delete action was removed). Old mail in Interview Confirmation / Final / First Interview Scheduled folders was not moved |
| Classification (LIVE) | Sender and body rules run before the AI and file clear non-job mail as Other (newsletters, course marketing, account mail, a student's note to self, bare links, Colaberry's own campaign, a care-job mail unrelated to the training); more job boards and bare job links are Job Alerts; a job-alert subscription confirmation is a Job Alert; HTML placed in the text part is now read as text (1,161 old stored bodies are still raw HTML); retired categories are re-filed by interview type (`CATEGORY_REMAP_MODE=live` since 10 Oct); an Assessment stays an Assessment and one assessment announced twice gives one notice; "Other" at 50% or more is no longer queued for review |
| Dashboard / Reports | Settled, no further interface changes (Kes). Dashboard = what needs you today (Upcoming Interviews with From/To, default today to +7 days). Reports tabs: Overview (weekly summary with From/To, default current week Mon-Sun), Interviews, Pipeline, Students, Companies, System. Red shadow banner on every page except Review |
| Review screen | Tabs: Student notifications, **Verify students (N)**, Classification review (now 0 pending; shows the email text; real folder list incl. "Other (not job related)"; moves find the mail by Message-ID). Verify box: Confirm this student, or **Not a student: reject** (live since 12 Oct; closes their unsent notices and follow-ups, hides them). Approve refuses: no student, no contact, unverified student, a past interview, the pilot limit (3), the one-email path (off) |
| Students and GHL | A student GHL cannot find is now flagged for verification (basis `no_ghl_contact`) with likely GHL matches by name; GHL lookups match a primary OR an additional email (duplicate-contact search); `execution/ghl_add_additional_email.py` adds an additional email only after a named person confirms (never the primary; dry run by default; not yet run live) |
| Notification messages | Audit-safe wording (`execution/notification_messages.py`, `content_audit.py`): text starts `[Interview Notification]`, 320 characters or fewer; email first line the same; NO job title, NO link, NO phone number; confirmation = reply YES (text or email) or yes on the call; an assessment has its own wording; a send-time gate refuses any flagged word, link or missing tag |
| Notification flow (shadow) | `NOTIFY_ESCALATION_ENABLED=true`, channels `ghl`, `GHL_WRITE_*` unset; 5-minute host cron; read-only conversations key on the server; plan stops at the interview; one student's notices at most every `NOTIFY_LEAD_SPACING_MINUTES` (3; about 5 in practice because of the cron); two sequences exist (Fikru Cheklie ended as interview_passed, Kwadjossan Isaac active) |
| Alerts | Stale-draft alert OFF. Callback alerts ON. Role alerts (approver, callback owner, escalation) are NOT copied to c_interviews any more. Health check knows shadow mode |
| Roles | escalation = jackie@colaberry.com; callback owner = robelyn@colaberry.com; **approver is TEMPORARILY kes@colaberry.com**: RESTORE robelyn@colaberry.com after the rehearsal. Jackie and Rob both replied on 12 Oct that they understand their roles (Jackie: backup for overdue callbacks; Rob: will review the "Verify Student" emails against the Google Sheets and send names, emails, phones) |
| Tests | 1,028 root + 242 dashboard pass. Tests cannot send email (conftest guard); `execution/simulate_notifications.py` guards the cadence |

### Where we are in the testing (updated 2026-10-12 night)
| Test | Status |
|---|---|
| Automated tests | 1,028 root + 242 dashboard pass |
| Local simulation | DONE (13 made-up students, 29 checks) |
| **Live mock test, 12 Oct (Kes, one-contact tool)** | Written to GHL at 14:52 to 14:58 UTC, one person at a time 3 minutes apart: Kes (text), Taiwo Oludimimu (call, text, email), Jackie (email). **Worked:** both texts DELIVERED within seconds; the call was placed and completed (38 s) about 2 min 45 s after the write; Kes replied "Yes" at 15:24 UTC and a GHL automation (not our app) answered "Thank you for confirming! Good luck with your interview." **Not confirmed:** emails are logged as sent but GHL shows no delivery status, nobody has confirmed receipt. **Found:** Taiwo's call reached a voicemail greeting and our parser marked it "reached a person" (fix proposed, not built); Kes's own Call and Email Do-Not-Disturb was on (cleared 15:53 UTC) so his call and email were not sent; those mock messages used the OLD wording (before the audit rewrite). No follow-ups were triggered (the tool starts no plan) |
| Content audit | The first messages were flagged by another automated system; wording rewritten the same day (see state table). Not yet re-tested live in the new wording |
| Voice call, outbound agent | Proven on 2 Oct and again placed on 12 Oct; NOT done: re-test with the new opening, "yes" read-back, wrong person, voicemail handling, STOP |
| Test callback to the AI receptionist | NOT done |
| Server shadow rehearsal | Fikru Cheklie's sequence ran (no GHL contact matched his email, attempts failed, ended when his interview time passed); Kwadjossan Isaac's notice was approved and his contact could not be found (record and GHL differ in email and phone), now flagged under Verify students; the additional email was added by Kes in GHL and the lookup finds him |
| Staff test with sequences (3 Colaberry staff) | NOT done as designed (each staff member needs a student record + interview event, shadow first, live only after Kes validates the log and approves the three switches). The mock test above was a partial live check |
| Pilot (3 real students, then lift the limit) | Not started |

### Still to BUILD or change (nothing below is built)
1. **Voicemail detection:** a voicemail greeting is read as a person reached (phrases like "leave a message", "after the tone"): proposed, Kes has not answered.
2. **Check what the GHL "Thank you for confirming" automation does** (and that it never answers STOP with anything else): Kes/Ali, in GHL.
3. **Re-test the new wording live** (own contact first, then staff) once Kes's Do-Not-Disturb is off (it is) and he says go; first email delivery still to be confirmed with the recipients.
4. **Ask the audit owner** whether messages that begin `[Interview Notification]` may name the job title (a small change if yes); the call (not scanned) may name it today.
5. **The "offer to resend by text" on the call** was dropped (the agent cannot send a text); needs a GHL action if wanted. **A real "add additional email" write** has never been run live (shape of the PUT unverified; it reads back to check).
6. **Check the real concurrency limits** of the Twilio account and GHL Voice AI, and whether Cora campaigns could run during tests (the 3-minute spacing only covers our own sends).
7. Open decisions: broader relevance rule (only data and technology jobs create a student notice? today only care jobs are excluded); pause follow-ups after a "needs help" reply; hold emails at night; shorter ladder for assessments; whether Kenya (student 8, two Highmark Health Client Screen notices) is rejected; "Told by hand" button (revisit about 20 Oct); lock down `execution/process_interviews.py`; label gap and automatic removal of the "Verify Student" label.
8. Longer term: roster from `config/students.py` into the database; a Google-Sheet roster lookup; phone numbers (only 4 of 19 students have one); compare `email_templates.py` with the Google Doc templates; a backup escalation holder.

### WAITING on answers or actions
- **Kes:** (a) **Kenya (student 8) and the other students to verify: Kes is checking with Rob and will report back (2026-10-12 night). Claude must not reject, reopen or change any student, and must not touch Kenya's two open Highmark Health Client Screen notices, until Kes says what Rob confirmed.** Kes still has to confirm that "Kenya" is the "Kenya Means" he meant, and whether to reopen verification or reject; (b) verify Kwadjossan Isaac (phone ends 9244 here, 9243 in GHL); (c) confirm with Taiwo and Jackie whether the mock text/emails arrived; (d) the GHL "Thank you for confirming" automation; (e) approval of the three `GHL_WRITE_*` switches only AFTER the shadow log is validated; (f) restore Rob as approver after the rehearsal; (g) "Called back" on the Oct 5 card; (h) decisions in item 7 above.
- **Ali:** the update email (draft in Kes's Gmail, to ali@colaberry.com) asks about: re-testing, the audit exemption, Twilio and Voice AI limits, the GHL auto-reply, who may undo a STOP, a backup escalation holder. Earlier questions (disclosure wording, authoritative student/phone list, pilot students, deleting about 200 stub emails) were "considered resolved" by Kes but Claude never saw the answers: do NOT delete the 208 stub emails or change the pilot students without Kes confirming.
- **Rob:** review the "Verify Student" emails and send names, emails and phones (acknowledged 12 Oct). **Jackie:** backup for overdue callbacks (acknowledged 12 Oct).

### What remains (in order)
1. Kes confirms with Rob who the students to verify really are (Kenya, Kwadjossan Isaac, and the others on the "Verify Student" label) and tells Claude; then Kenya and Kwadjossan are cleaned up in Verify students (Confirm, correct the details, or Not a student: reject). Kes decides the other open points above.
2. **Next live test, own contact first:** new wording, text then email then call, one at a time; confirm receipt with the recipients; read back with `python execution/ghl_test_call.py --email <contact> --readback`.
3. **Staff test with sequences** (needs student records and interview events; shadow first, read `notify_tick.log`; then Kes approves the three switches; GHL allows ONE call per number per day).
4. Wrong person, voicemail and STOP tests on separate days; test callback to the AI receptionist; then the small live pilot (3 real students) only after Ali's go.
5. Cleanup: restore Rob as approver; delete the shadow sequences (they count against the pilot limit of 3); AI reading of replies stays in shadow until 2026-10-16.

### How to work here (hard-won)
- Branch from `master` -> tests (`python -m pytest tests -q --no-cov`, `python -m pytest services/dashboard/tests -q --no-cov`) -> fast-forward merge -> `git push origin master` -> delete the branch -> **deploy FROM master**
  -> sync check (tree clean, master == origin, `.deployed_commit` == master). **`scripts/deploy_hetzner.sh` deploys the CURRENT checkout**: it once deployed a feature branch (2026-10-09); always `git checkout master` first.
  Frontend changes need `--build-web`; the deploy refuses minutes 00-11 of an even UTC hour.
- Settings reach the containers only through the repo `.env` loaded with `load_dotenv` (`printenv` in a container is misleading: the API HAS the SMTP login). After changing an import path, grep every `patch(...)` target for the old path.
  A test that reaches an unmocked send emails for real (it did, 4 times): the conftest guard now fails such a test.
- Prove things yourself: local stack (`docker compose up -d --build api frontend` in `services/dashboard`, admin/admin123) + Playwright; query production with aggregates (no student data in output); never print secrets. Production writes and mailbox changes need
  Kes's explicit go and are sometimes blocked by the permission system: say what was blocked, never work around it. Shell heredocs with backslashes mangle `\n`: use the Write/Edit tools for such files.
- A health-check run EMAILS Kes unless `ALERT_EMAIL_TO=` is blanked. A dry run must never edit `config/students.py`. Roles, not people: addresses come from the Settings page; never write a person's name or address into code.

---

## 2026-10-09 to 2026-10-10 log (newest first)

### 2026-10-14: the Review list shows only notices that still need a decision

Kes: three cards (Fikru Cheklie, concluded; Kwadjossan Isaac and Sehrish, approved with follow-up plans running) sat in Student notifications although already decided. `GET /api/notifications/review-queue` now skips `approved` drafts unless `include_done=true` ("Show finished"), like sent and rejected ones. Nothing was rejected or closed: the approved plans keep running (shadow). Files: `services/dashboard/api/routers/notifications.py`; tests `test_review_flags.py` (new) and `test_reject_student.py` (looks under Show finished). Backend only, no web rebuild.

### 2026-10-13 (evening): skill for giving an app read-only access to a live Google Sheet

New guide `docs/google-sheet-service-account.md` (and the same text as the local Claude skill `.claude/skills/google-sheet-service-account/SKILL.md`; `.claude/` is gitignored, so the docs file is the tracked copy): the exact recipe used for the InboxGenius roster (Cloud project with no billing, Sheets API, service account, JSON key, Apps Script values-only copy of chosen columns by header name so the master and formulas stay private, sharing as Viewer, key placement and gitignore, `.env` names, read-only verification, test isolation, cost, rotation). Docs only; no code change.

### 2026-10-13 (later): every open interview notice is flagged "not on roster" and/or "not in GHL"; nothing is silently dropped

Kes's rule: anyone on the roster (personal and/or application email) is notified; anyone not on it is flagged; a student GHL cannot find is flagged (the sheet may be out of date); NO silent non-notification: a person still declines. So there is no automatic reject or skipped notice. `execution/student_flags.py` gives each open notice `flags` = roster (listed | name_only | unlisted | unknown) and ghl (found | not_found | check | unknown, a read-only GHL lookup, cached 30 min), and puts a plain warning at the top of the notice (never a blocker). `find_ghl_contact` now also tries the roster row's emails (the emails must agree, as before). Roster/GHL unreachable = "unknown" and the screen works as before. A blank or tiny roster (<5 rows) is ignored. Tests never reach the real sheet or GHL (autouse fixture in both conftests). Also today (Kes's go): `execution/reject_unlisted_students.py` rejected the 10 PENDING (unverified) students not on the roster (Omdata Pro, Omolola, Nabour, Shahadalijawad, Mohamedbelgacha, Priyan, Olukayode, Eojeniyioftx, Stewartmartinique, Tibebe); 8 others not on the roster were left alone (no pending verification): Pandey, Shylaja, Emmanuel, Alisha, Sehrish, Fabrice, Alberta, Fikru Cheklie. Milad (name on roster, no email there) is still unverified. Files: `execution/student_flags.py`, `student_roster.py`, `notify_channels.py`, `routers/notifications.py`, both `conftest.py`, tests `test_student_flags.py`, `test_review_flags.py`.

### 2026-10-13: live student roster (Google Sheet) read by the app, dry-run comparison only

Kes keeps a master sheet of students. A values-only `roster` tab (Agent, Name, STATUS, New Email Address, Personal Email Address; only Active and In Progress rows) is filled hourly by an Apps Script, so the app never sees the master, any formula or other columns. The app reads it live with a read-only service account (`inboxgenius` Google Cloud project, no billing linked, Sheets API only; key at the gitignored `config/service-account-key.json`; sheet shared as Viewer). New: `execution/student_roster.py` (parse by header name, match by email then name, compare) and `execution/student_roster_check.py` (dry-run report, emails masked, nothing written to students, GHL or the sheet); tests `tests/execution/test_student_roster.py`; `.env.example` (`STUDENT_ROSTER_SHEET_ID`, `INBOXGENIUS_SERVICE_ACCOUNT`). Next (not built): show roster status in Verify students and use "same name, different email" to propose an additional GHL email, each only after a person confirms.

### 2026-10-13: health check no longer alerts on a failure a later step already fixed

The 07:30 UTC health email said 4 student notification attempts failed (call, text, email, one follow-up), all on one plan (student 25, Kwadjossan Isaac, 12 Oct 19:45 UTC): "no GHL contact matches". This was a real lookup miss (not shadow mode; the lookup is a live read). Kes then added the additional email in GHL and every later step on that plan found the contact (`dry_run`). The check kept counting the old failures for 24h. Now `collect_metrics` counts a failed attempt only if no LATER attempt (higher id; `created_at` is one timestamp per plan) on the same plan is `sent` or `dry_run`. Files: `execution/health_check.py`, `tests/execution/test_health_check.py` (new test: recovered / not recovered / success-before-failure). No student data changed.

### 2026-10-12 (late): Kes will check the students with Rob

Kes: "I will verify with Rob and let you know." No student data was changed after that message: Kenya (student 8) stays verified with his two open Client Screen notices (Highmark Health), Kwadjossan Isaac stays flagged unverified, and nothing was rejected. Rob already agreed (reply of 2026-10-12) to review the "Verify Student" emails against the Google Sheets and send names, personal emails and phones. When Kes reports back, the Verify students tab is the place to act: correct the details and confirm, or use "Not a student: reject". Both the update email to Ali and the earlier role emails were drafts in Kes's Gmail; Claude never sends.

### 2026-10-12 (Monday) DAY SUMMARY: what was done, what the test showed

**Interface:** Dashboard (act today) and Reports (look back, tabs, From/To date filters) settled; Classification review fixed (email shown, real folders incl. Other, moves by Message-ID, Delete removed, list 126 to 0); reject-a-student added to Verify.
**Classification:** many "not job" rules (newsletters, account mail, notes to self, Colaberry campaign, care jobs), HTML-in-text fix, job-alert subscription rule, assessments stay assessments with one notice, retired categories live.
**Notifications:** audit-safe wording with a send-time gate (no job title, no link, no phone number, YES to confirm), spacing between students, unreachable students surface for verification with GHL near matches, role alerts no longer BCC c_interviews, GHL lookups match additional emails, one-contact mock test tool (hours, audit, Mock wording).
**Test results (mock, live, 3 staff):** texts delivered to Kes and Taiwo; call placed to Taiwo (voicemail); Kes's "Yes" was read and GHL answered with its own thank-you; emails logged but delivery unconfirmed; Jackie has no phone; Kes's call and email were blocked by his Do-Not-Disturb until 15:53 UTC; wording used was pre-audit. No sequence, no follow-up and no production switch was touched; production stayed in shadow.
**Mistakes this day, all fixed before they mattered:** a first deploy whose web build failed while the script said "Deployed"; a merge made with a failing test (fixed before deploy); a test file with a syntax error (fixed before deploy); the first care-job rule missed mail that starts with a long tracking link; the first GHL name ranking listed the wrong people; the additional-email search used GHL's free-text search, which only sees primary emails.
**Counts at the end of the day:** 1,028 root + 242 dashboard tests; `master` == `origin` == server.

### 2026-10-12: a student can be REJECTED, not only verified (Kes: "Kenya Means ... I don't see him in GHL ... there was no other option")

The orange Verify box had only "Confirm this student", so Kes clicked it on Kenya Means hoping for more options. Added **"Not a student: reject"** (with an inline "Yes, reject this student / Cancel" confirmation) to the Verify box: `POST /api/notifications/students/{id}/reject-verification` marks the verification `rejected`, rejects every notice for them that has not gone out (reason recorded), closes their active follow-up plans, and hides them from the queue; nothing is deleted or sent. A student who already has a notice that went out is refused (409). Backend tests added (`services/dashboard/tests/test_reject_student.py`); the button itself was type-checked and built but NOT seen in a browser (the local database had no unverified student and the local API container lost its database host when restarted). Kenya Means had been confirmed by mistake: rejected afterwards (see the result in chat).

### 2026-10-12: GHL lookups match a primary OR an additional email; adding one needs a person's confirmation (Kes)

GHL contacts have "Email (Primary)" and "Email (Additional)". Kes: he can add the additional email by hand; the app must never replace the primary, must find a student by either address, and may add an email only once a human has confirmed it. **Built:** `ghl_client.contact_emails()` (primary first, then any additional emails; read tolerantly: a list of strings or of {email/value/address} objects under `additionalEmails`, `additional_emails` or `emails`) and `search_contact_by_email` now matches either; two contacts sharing an address are still refused. `GhlClient.add_additional_email(contact_id, email, confirmed_by)`: refuses without a named confirmer, refuses when another contact owns the address, shadow-gated like every GHL write, sends ONLY `{"additionalEmails": [...]}` (never the primary), then reads the contact back and fails loudly if the primary changed or the address was not stored. Run by hand with `execution/ghl_add_additional_email.py --contact-id ... --email ... --confirmed-by "<name>"` (dry run by default, `--apply` to write; the live switches are on for that process only). **Verified live (Kes added `kwadjossanisaackpakpavi@gmail.com` by hand to the contact whose primary is `isaackpakpavi@gmail.com`):** the contact carries `additionalEmails: [{"email": ...}]` (our reader handles it) but GHL's free-text search (`GET /contacts/?query=`) finds contacts by PRIMARY email only (0 results for the additional address); `GET /contacts/search/duplicate?email=` matches primary and additional exactly and returns the contact (or none), so `search_contact_by_email` now tries that first and keeps the free-text search as the fallback and as the ambiguity check (a second contact with the address as its primary is still refused). Still unverified: a PUT of `additionalEmails` (our add tool has not been run live; it checks by reading back). Nothing was added to any contact by the app.

### 2026-10-12: a student GHL cannot find now surfaces for verification; staff alerts are not BCC'd to c_interviews (Kes, Kwadjossan Isaac)

Kes approved the notice for Kwadjossan Isaac (student 25) and got the "Cannot reach" alert. **Finding:** our record has personal/assigned Gmail `kwadjossanisaackpakpavi@gmail.com` and phone ending 9244; GHL has the same person as "kwadjossan issac kpakpavi" with email `isaackpakpavi@gmail.com` and phone ending 9243 (a one-digit difference in the phone, and a different email), so neither the email nor the phone matched. He never appeared under Verify students because that list only holds students the system had to GUESS; this one came from the roster (so no verification record) and the roster details were wrong. **Changes:** (1) `RoleAlerts` sends with `bcc=""`, so alerts to the approver, callback owner and escalation contact are no longer copied to c_interviews (student-facing mail is unchanged); (2) when a send fails because no GHL contact matches, the student is now flagged (`StudentVerification` basis `no_ghl_contact`, evidence = the reason) so they appear under Review > Verify students with the form to correct details, and the Verify box says why; a student who already has a record (verified) is never downgraded; (3) the "not found" message now lists near matches by name from GHL (name, email, last 4 of the phone) via a new read-only `GhlClient.search_contacts_by_name`; (4) the alert says the student is now under Verify students. Tests added. Data fix for student 25 is waiting on Kes (which email and phone are right).

### 2026-10-12: assessments are not interviews; one notice per assessment (Kes, Rutendo Bwerazuva / Martin Sprocket and Gear)

Two emails for the same student and company (the applicant system "Pending Assessment(s)" with text, and the test vendor Criteria "Assessment Invitation" with NO stored text) were both correctly classified **Assessment** 95%, but then the interview sub-classifier relabelled them "Interview Request" and "Technical Interview", so two interview-style notice cards appeared. Fixes: (1) `_build_sub_classification` forces the event type "Assessment" when the primary category is Assessment; (2) `assessment_duplicate_action` in `process_interview_email`: an assessment announced again within 3 days for the same student and company (company names compared after normalising "&", "Inc", etc.) is skipped, unless the held notice came from an email with no readable text and this one has text, in which case the held draft is rejected and this one is used; (3) `draft_notification` selects the assessment template, and `notification_messages` has assessment wording ("an online assessment ... a test, not an interview ... the invitation email from the employer", no link, no job title; subject "Your assessment notice"); voice prompt line added. One-off `execution/fix_assessment_notices.py` (dry run by default) retypes and rewrites unsent assessment notices and rejects duplicates (keeps the one with text, else the earliest). Kes said the one with text (martinrecruiting) is the one to notify, which is what the rule keeps. Not changed: whether an assessment notice should follow the same 15-notice ladder (it does today, with no interview date).

### 2026-10-12: care-job interview mail is "not relevant" (Kes: a Certified Nursing Assistant call request "has nothing to do with data science")

A home-care firm (Visiting Angels) asked a student, Mirriam, for a call about a Certified Nursing Assistant posting and it became a student notice card. New rule in `pre_classify_by_sender`: when the subject or the first 500 characters name a care or clinical-support job (nursing assistant, CNA, caregiver, home health aide, medical assistant, LPN, RN ...) AND mention no data or technology work (data, analyst, SQL, software, engineer, informatics, ...), the mail is `Other`: no interview event, no student notice. A healthcare DATA role is not caught (tested). New one-off `execution/file_not_relevant_interviews.py` (dry run by default): rejects the unsent draft of any interview whose email the rules now call Other, moves the mail to Spam Review by Message-ID, records an Other classification; the event itself is kept (still visible in Reports > Interviews). **Second fix, same day:** the real Visiting Angels mail (from a recruiting platform) begins with a long tracking link, which pushed the wording past the 500 characters the rules read, so the first version missed it (the one-off found 0). The care-job rule now reads the text with web addresses removed and a 1,500-character window (tested with a 700-character link first). Note this is Kes's relevance call for care jobs only; other off-topic jobs (retail, warehouse...) are NOT covered and need their own decision.

### 2026-10-12 (later): no links, no phone number; confirmation is YES only (Kes)

Kes's answers to the audit rewrite: confirm by "Yes" to the text or the email, or "yes" on the call, so the "or call <number>" part is gone and `NOTIFY_CONTACT_NUMBER` is removed; **no links in any message**: the join link and the email's one-tap "I got this" link are removed (a video interview says to use the link in the employer's own invitation email), and the audit gate now refuses any link; the "offer to resend by text" idea is dropped from the voice prompt (the agent only says the details were also sent by text and email). `rewrite_pending_drafts.py` also rewrites an earlier new-style draft that carries a link. Use-case page story 14.2 updated. Kes asked whether the audit's flagged terms (data analyst, sql, power bi, tableau, full stack, ...) can appear since interviews are for such positions: they ARE on the audit's list as given, so a message with one would be flagged; we cannot change the audit; the messages therefore say "the position you applied for" and the call (not scanned) may name the position. Option, if the audit owner agrees to exempt messages that begin "[Interview Notification]": add the title back (a small change).

### 2026-10-12: notifications rewritten so an automated content audit does not flag them (Kes pasted the audit's rules)

The first texts and emails were flagged. New `execution/content_audit.py` (the audit's flagged words and phrases, text-only marketing words and "$", `[Interview Notification]` start rules, 320-character limit) and `execution/notification_messages.py` (the wording: no job title ever, "the position you applied for", the employer's name replaced by "the employer" if it contains a flagged word). Text and email are built from the interview facts; `draft_notification` now stores the audit-safe email on the draft (plain subject "Your interview on <date>"); `notify_channels` builds the text and, for an older template draft, the email from the facts at send time, and a send-time gate (`audit_problem`, in the GHL, SMTP and dry-run channels) fails any message that would be flagged instead of sending it. Test tool messages follow the same rules and keep the "Mock interview notification" line. Voice prompt doc updated (agent name and who it calls for, date and time confirmed back, details also sent by text and email, no outcome claims). New one-off `execution/rewrite_pending_drafts.py` rewrites unsent drafts so the card shows what will be sent. New setting `NOTIFY_CONTACT_NUMBER` (the number for replies; unset = "reply YES").
**Open for Kes:** the contact number to use; whether a text may carry a link (the app's own text gate refuses links because carriers block them, so a video interview says "the join link is in your email"); "offer to resend by text" on the call needs a GHL action. The old reschedule-request nuance is kept for cancellations ("ask for a new time").

### 2026-10-12: one-contact test tool made ready for the staff mock test (Kes: "Run the test with actual call, SMS, email... starts with mock interview notification")

`execution/ghl_test_call.py`: every test message (call value, text, email subject and body) now STARTS with "Mock interview notification"; an email test no longer needs a phone (Jackie's GHL contact has none), while a call or text still does; `--send` of a call or text is refused outside the contact's own hours (calls 8 AM to 8 PM, texts 8 AM to 9 PM, zone from the phone area code, the app's own rule). Tests added. Contacts resolved read-only in GHL (exact match on email, one contact each): Kes Del = kesetebirhan@gmail.com (phone on file); Taiwo Oludimimu has TWO contacts, the one with a phone is taiwo@colaberry.com (the other, taiwo.abisola@gmail.com, has no phone); jackie@colaberry.com has no phone, email only. The tool writes one contact's field for one channel and never changes `.env`, so production stays in shadow mode.

### 2026-10-12: spacing between students so notices do not trip Twilio's concurrency limit (Kes)

`escalation_engine.tick` now holds a student's due attempts while ANY other student was contacted (sent, or logged in shadow mode) less than `NOTIFY_LEAD_SPACING_MINUTES` ago (default 3; 0 = off). One student's call, text and email still go out together; held attempts stay pending and the next tick sends them; the student waiting longest goes first. The tick output shows `spaced=N`. Because the host cron runs every 5 minutes, students in a burst go out about 5 minutes apart (a 1-minute cron would give 3). Tests: second student held then released at 3 minutes, oldest first, shadow sends count, 0 switches it off, env parsing. Documented in the directive.
**Limits (told to Kes):** spaces our sends only; Cora and the receptionist's inbound calls share the same line; a call can outlast 3 minutes; the real Twilio and GHL Voice AI concurrency numbers are unverified. Follow-up proposed, not built: do not start a call while the previous call is still open in the GHL call log.

### 2026-10-11: use-case page brought up to date and a walkthrough tab added (artifact FRzyZVP1uBnsvMPEViEZiw, `docs/use-cases.html`)

Status now dated 11 Oct (commit b525ca7). Updated: shadow mode on the server (UC12, 13, 17 now say "Shadow", plus the Fikru no-GHL-contact finding and the Mon 12 Oct staff test); the plan stops at the interview (13.6, 13.7); retired categories live (3.9); new classification rules and the HTML-body fix (1.8 to 1.11); UC6 rewritten for the cleaned-up Classification review (email shown, real folder list with Other, no Delete, moves by Message-ID, list at 0); UC8 rewritten for Dashboard (today) and Reports tabs with From/To date filters and the shadow banner; health check knows shadow mode; callback alerts carry context (19.2); Verify students tab and the "Verify Student" Gmail label (UC20); Review has three tabs. New **Walkthrough tab**: 7 steps, 4:20 in all, each with what to say and what to show, a timer, arrow-key navigation; statuses are honest (Shadow mode, Built not yet proven). Open item shown on the page: the westcoastllc "kindly join below zoom link" mail in Quarantine awaiting Kes (6.6). Docs only, no code.

### 2026-10-11: date filters on Upcoming Interviews and the Reports summary (Kes: "I like the current interface and we will not be changing it anymore")

Decision: the current interface stays; the Dashboard/Reports/Review consolidation proposed in the screen-plan artifact is DROPPED (nothing from it is pending).
- **Dashboard, Upcoming Interviews:** From and To date pickers in the card header. Default: today to one week ahead (Central time), titled "(next 7 days)"; a changed range shows the dates, "N more after <date>" counts what lies beyond, and "Reset to next 7 days" appears. API `GET /api/interviews/upcoming` takes an optional `start_date` (default today) so the range can reach back; the end date is applied on the screen.
- **Reports, Overview weekly summary:** From and To pickers under "Week of ...". Default: the current week, Monday to Sunday in Central time (it used to be a rolling last 7 days). API `GET /api/stats/weekly-summary` takes `start_date` and `end_date` (inclusive, Central-time days converted for the database); an end before the start, or a range over a year, is refused with a plain 400 message shown on the screen. "Reset to this week" returns to the default. Only that summary follows the dates; the category chart (30 days) and 7-day trend are unchanged.
- Tests: `services/dashboard/tests/test_date_filters.py` (default week, range counting, the end day included through its last hour, bad ranges, look-back). Checked in a real browser locally.

### 2026-10-11: more not-job rules; Classification review is empty

Kes picked out five more: (1) Ali's "Questions About Colaberry?" Mailchimp campaign, (2) the Mobius Engine reply (a firm selling interview volume; closed as "keep in inbox" by mistake), (3) Kenya Bogans's "Audio" (a phone attachment path mailed to self), (4) the Southlake career-networking invitation, (5) Helen Asfaw's bare link with no subject. New narrow rules in `pre_classify_by_sender` (all `Other`): no subject plus body that is only a URL, or a body starting `file:///`; sender exactly `ali@colaberry.com` plus "view this email in your browser" (other Colaberry senders, e.g. cai@ "Logging Interviews", are NOT covered, tested); domain `mobiusengine.ai`; sender exactly `charliezinger@aol.com`. Tests cover the look-alike and real-mail cases. Applied on production: the 3 open items closed; approval 24 (Mobius) corrected from keep_inbox to Other in the record (Gmail had it parked all along). **Classification review now has 0 pending.**
**Found while checking (needs Kes):** approval 67, "RE: Rights to Represent for Power Bi Lead" from vishal.c@westcoastllc.com, body "Hi Sehrish, Kindly join below zoom link: Join Zoom Meeting...", is in Gmail's **Quarantine** (labels: Important, Quarantine), has NO interview event and no student notice, and was closed as "keep in inbox". The AI read it as Interview Request 95%. If it is a real meeting for Sehrish, nobody has been told.

### 2026-10-10 (night): Classification review re-read and reclassified; "Other" at 50% or more no longer queued (Kes: "Yes proceed, analyse and reclassify")

- **Finding:** "Other" mail is already parked physically (Spam Review, then Quarantine) whatever its confidence; the review queue only gave a person a chance to look. Kes agreed to stop queueing the confident ones.
- **Policy (`needs_human_review`):** "Other" at 50% or more is no longer queued (was: only exactly 0%); a weak "Other" under 50% still goes to a person; every other category still queues under 70%.
- **New `execution/reclassify_review_items.py` (dry-run default, `--apply`):** re-reads each pending item with the CLEANED body, runs the live path (rules, then the AI), and files a confident non-interview answer (Job Alert, Job Invite, LinkedIn/Application/Gmail Notification, Basecamp, Forwarded Email at 70% or more), closes "Other" (50% or more, or the model's 0% junk answer), and leaves the rest. It never touches mail written by a person: personal-mailbox senders, Colaberry addresses, and any "Re:/Fw:/Fwd:" subject stay for a human. New answers are stored as new classification rows (`review-reclassify`); old rows are kept.
- **Result on production (54 open):** 41 closed as Other (already in Spam Review/Quarantine), 4 filed (2 Job Alerts, 2 Job Invites, in Gmail), **9 left for Kes**: a recruiter RTR reading Interview Request 95% (westcoastllc), a recruiter reply read as Job Invite (mobiusengine), internal Colaberry mail (Logging Interviews; Ali's "Questions About Colaberry?"), a university reply about transcripts, and four from personal mailboxes (Audio; Caleb Ephrem; No Subject; Southlake networking).
- Tests: 913+ pass (new file for the script, policy cases updated).

### 2026-10-10 (later): the real reason the NOV mail was missed: HTML inside the text part

After deploying the job-alert-consent rule the dry run still did not match the NOV mail. Cause: some senders (Oracle recruiting, OpenAI: 1,161 of 9,844 stored bodies) put the whole HTML page in the **text/plain** part, and `extract_email_body` only cleaned HTML when it came as text/html. So the classifier's 1,500 characters (and the rules' 500) were the HTML head and CSS, never the message. Fixes: `extract_email_body` now cleans any body that looks like HTML (stray "<" in real text is left alone, tested); `file_review_items.plan` cleans stored bodies before applying the rules; the dashboard email detail already cleaned for display. New mail benefits from the next run; the 1,161 old stored bodies are left as they are (not rewritten).

### 2026-10-10: OpenAI account mail is Other; job-alert subscription confirmations are Job Alerts (Kes: "should have been moved to other already")

- **Why they were in review at all:** the AI answered "Other" at only 50 to 65% confidence, and an "Other" below 70% (but above 0) is queued for a person by design (`needs_human_review`); only exact 0.0 "Other" files itself. Rules skip that step, so `noreply@email.openai.com` (exact address) now returns `Other` before the AI is asked.
- **Does Inbox Genius read the body? Yes:** the classifier gets the subject and the first 1,500 characters of the body, and the deterministic rules see the first 500. The NOV "Confirm Your Options" mail was missed because the Job Alert definition only described digests, so the model had no class for "confirm that you agree to receive Job Alerts". Fixed twice: a prompt line (job-alert subscriptions, "confirm your options", opt-ins are Job Alerts) and a narrow rule (body says job alert(s) AND confirm/opt-in/subscribe/agree to receive AND no interview wording). Not a sender rule on purpose: the same Oracle Recruiting sender also sends real interview mail (tested that the rule leaves it alone).
- **Open decision for Kes:** "Other" at 50 to 69% confidence still goes to a person. Auto-filing it (to Spam Review, then Quarantine, reversible) would empty most of the review list but trades away the safety net for a real mail the AI mislabelled. Not changed.

### 2026-10-10: Kes's test mail removed from Classification review (data only, no code)

Kes had already deleted his test emails (sent from kes@colaberry.com) from the inbox. The 7 still open in Classification review were closed as `rejected` (reviewed_by "kes (test mail removed)", note says why); Gmail untouched. No student-notification cards were involved (0). 28 emails ever came from that address; only the 7 open review items were changed. Review list then held 57 pending.

### 2026-10-10: info@school.colaberry.com goes to Other (Kes: "move all coming from info@school.colaberry.com to other folder")

Production check: 6 emails ever from that address ("New Project Request" / "Final Project Request"), all already in Spam Review, 0 interview events, 5 still open in Classification review. `pre_classify_by_sender` now returns `Other` for that EXACT address (not the whole school.colaberry.com domain, tested), and `file_review_items.py --apply` closed the 5 open review items (already at their destination, so no Gmail change).

### 2026-10-10: manual moves find the mail by Message-ID (Kes: "Moving didn't work")

The first fix (look in the email's own folder) was not enough. API log: `Move: message 760488 no longer in 'Spam Review'`: the database said Spam Review but the pipeline had already moved it on to Quarantine, and the stored UID is per folder and goes stale. New `fetch_emails.relabel_by_message_id` (used by `move_email` when the email has a Message-ID; old path kept as fallback): finds the message in All Mail by Message-ID, adds the target label, removes our other folder labels (the folders in use in the database), and takes a remaining Inbox copy out with the UID-scoped expunge. Nothing is deleted. Tests: label parsing, stale-folder move, inbox copy, not-found. Lesson: the stored folder and UID are hints, never the source of truth.

### 2026-10-10: Classification review actions fixed (Kes: no "Other" in the folder list; approved Delete left the card in the list)

Production API log showed `POST /api/approvals/8/approve 500` ("Failed to delete email"): the screen swallowed the error, so the card simply stayed. Two root causes: (1) `integration/email_actions.move_email` never passed `source_folder`, so `move_emails` looked only in INBOX and every manual move of mail filed elsewhere (Spam Review, Needs Review...) failed the same way; now it passes `email.current_folder`; (2) Delete is permanent and breaks the quarantine-never-delete rule, so the API now answers 400 with a plain message for the `delete` action (approve and override) and the screen no longer offers it. The folder list was a stale hard-coded five (Interview Scheduling, Rejection...): it is now the real workbook folders in groups, with **"Other (not job related)"** first (moves to Spam Review, the pipeline's route; its second pass parks it in Quarantine). The screen now shows the server's error under the Approve button instead of failing silently. Tests: delete refused (approval stays pending, nothing deleted), move reads from the email's own folder.
**Not verified on production:** a real manual move has not been run (it would move a real email); Kes to try one and tell me.

### 2026-10-10: mail a student sends to their own account is "Other" (Kes: "it is not relevant")

A screenshot of an application confirmation arrived From the student To the student (Gmail forward). Rule added in `pre_classify_by_sender` (`_is_self_sent`): when the sender is also a recipient (To/Cc, or the Delivered-To / X-Forwarded-To style headers), the mail is a note to self and classifies as `Other` (Spam Review, then Quarantine; nothing deleted), whatever the subject says. Colaberry addresses are excluded; real employer mail never matches. Limit: the recipient headers are not stored in the database, so this applies to NEW mail only; old items such as the American National screenshot stay in Classification review for a person to pick a folder. Not built: reading images (no OCR/vision anywhere); open question to Kes whether to send student images to the AI model. Real application confirmations with text stay Application Notification (own folder), not Other.

### 2026-10-10: non-job mailers classify themselves (Kes: "classify these types automatically as they are not job related")

Skool event reminders were already a rule (`Other`). Checked the rest of the Classification review list on production: dataengineeracademy.com (65 mails ever), arcamax.com (221), irelaunch.com (17), propertymeld.com (9) are marketing/newsletters with **0 interview events ever**, so `pre_classify_by_sender` now returns `Other` for them (Spam Review, then Quarantine on the next run; nothing deleted); experteer.com (headhunter network, 14 mails) joined the job-board list (Job Alert). `file_review_items.py` now also files rule "Other" items into Spam Review. Applied on production: 3 more job alerts moved to Job Alerts; the other 46 non-job items were ALREADY in Spam Review/Quarantine (the pipeline had filed them, only their review approvals were still open), so `file_review_items.py` now just closes the approval when the email is already at its destination. (An SSH drop mid-run left the first apply half done; the script is idempotent and was rerun.) Left alone on purpose: colaberry.com / school.colaberry.com (internal, may carry real interview info), Handshake (employers can send real invitations), Gmail senders. Tests added (look-alike domain stays unmatched).

### 2026-10-10: Classification review shows the email body (Kes: "nothing comes up... I don't want to go back to the email")

Clicking a card on Review > Classification review opened only Action / Notes / Approve, with no email text. `ApprovalsContent.tsx` now shows the same collapsible `EmailBodyPanel` the student cards use (body, long emails truncated with "Show full email", classification chips), and the right-hand panel scrolls so Approve stays reachable. Production check: 119 of the 120 pending items have the body stored (9,597 of 9,824 emails overall). Checked in a browser locally; frontend only.

### 2026-10-10: Classification review list filed by rule; bare job links auto-classified (Kes: "move them... classified automatically from now on")

Kes saw bare job links (subject is only a LinkedIn URL, from a student's Gmail, 65% "Other") sitting in Review > Classification review.
- **From now on:** `pre_classify_by_sender` already turned a bare LinkedIn job link into Job Alert (folder "Job Alerts"); the old items were queued before that rule. The rule is now wider: `_BARE_JOB_LINK` also covers Indeed, Glassdoor, ZipRecruiter, Dice, Monster, CareerBuilder, SimplyHired postings (subject must START with http; "Fwd: <link>" is not matched, it can carry a message). Tests added.
- **Existing list:** new `execution/file_review_items.py` (dry-run by default, `--apply`): for every PENDING approval whose email a rule classifies as Job Alert / LinkedIn Notification / Basecamp / Gmail Notification it labels and moves the email in Gmail (reuses `label_verify_students.apply_items`, now with a `label` parameter; UID-scoped, nothing deleted), sets `current_folder`, and closes the approval (approved, move_to_folder, reviewed_by `rule-filing`). Interview results are never filed by it. Mail Gmail cannot find stays pending.
- Files: `execution/file_review_items.py`, `execution/label_verify_students.py`, `execution/process_inbox_auto.py`, `tests/execution/test_file_review_items.py`, `tests/execution/test_subclassify_and_quarantine.py`.
- Still open (Kes to decide): the "Delete" action on Classification review is permanent per its code comment, which breaks the quarantine-never-delete rule: remove it or make it move to Quarantine; "dismiss older than 14 days" for that list.

### 2026-10-10: Dashboard = act today, Reports = look back (Kes: "Option C ... do it now")

Redundancy review found the same lists and numbers on Dashboard, Reports and Interviews. Consolidated (frontend only, no API or notification change):
- **Dashboard** keeps what needs action today: Run Now, 4 tiles (Emails Today, Interview Requests, Offers Today, Last run), approvals and student-notification banners, the ONE Upcoming Interviews table, Emails Processed Today. Removed from it: This Week card, 7-day chart, category donut, engineering KPIs, runs table.
- **Reports** now has tabs (URL `?tab=`): Overview (weekly tiles, category mix with the real categories, 7-day trend, offers goal), Interviews (the old Interviews page, now embedded), Pipeline, Students, Companies, **System** (AI cost, run time, failure rate, database storage, last 25 runs).
- **Nav:** the Interviews item is gone; `/interviews` and `/interview-events` redirect to `/reports?tab=interviews`. The duplicate Upcoming table on the Interviews page is removed.
- **Shadow banner** (red) now shows on every page except Review (which has its own) while escalation is on and delivery is not live.
- Stale five-category list on the donut and category chips replaced (donut shows top 10 real categories, rest grouped).
- Dropped: the weekly "Top Companies" chart (the Companies tab covers it, all-time).
- **Follow-up fix (Kes spotted it):** the Dashboard "Interview Requests" tile showed the ALL-TIME total (52) on a today-only page. It now shows today's count (`today_interview_requests`, same Interview Request category) and is titled "Interview Requests Today". The orange "N emails waiting for approval" banner is also a running backlog (all pending low-confidence reviews), not today's work: left as is on purpose, it is real work waiting.
- **Deferred:** week/all-time switch for Pipeline and Companies (needs API change); Students "Notified/Pending" still counts the old draft flow, not escalation sequences (needs API change, do after live testing); Notifications report once real notices flow.
- Files: `DashboardPage.tsx`, `ReportsPage.tsx`, `InterviewsPage.tsx`, `Layout.tsx`, `App.tsx`. Checked in a real browser locally (all tabs, redirects, no console errors); type check and build pass.
  **Slip:** a last wording edit put a bare `>` in JSX text, so the first deploy's web build FAILED on the server while `deploy_hetzner.sh` still printed "Deployed" (the old web stayed up; api/cron updated). Fixed in the next commit and the served bundle was checked by hand. Lesson: after `--build-web`, confirm the served bundle changed; rebuild locally after the final edit.

### 2026-10-10: health check understands shadow mode; interview-type re-filing switched LIVE (Kes: "proceed for both")

Kes got "UNHEALTHY: 3 problems" at 07:30 UTC. Cause of each: (1) "1 draft approved over 60 minutes ago but never sent" = Fikru Cheklie's draft: in shadow mode nothing is delivered, so a draft never reaches "sent" (false alarm); (2) "3 attempts failed" = his three email attempts, "no GHL contact matches this student's email" (real; the first reaches the approver as a "Cannot reach" alert, planned: simulation S10); (3) "3 of 8 events used the fallback label" = three real interviews classified "Interview Confirmation" (a retired category that skips the sub-classifier by design, label "confirmed"): not the sub-classifier failing (10 of 102 events in 30 days did this).
**Fix 1 (`execution/health_check.py`, 5 new tests):** while the flow is on and delivery is not live (`_shadow_mode()`), "approved but not sent" is not a finding and the report says "SHADOW MODE: nothing is delivered ... (not counted as a problem)"; failed attempts stay CRITICAL; events labelled `confirmed` / `interview_schedule` / `final_round` are not counted in the fallback rate (shown on the numbers line instead).
**Fix 2:** server `.env` `CATEGORY_REMAP_MODE=live` (old `.env` saved): Interview Schedule becomes Interview Request; Interview Confirmation / Final Interview Scheduled become Client Screen, Technical Interview or Phone Screen by interview type, else Interview Request, so they go through the sub-classifier and get a proper template. Applies to mail classified from the next run on; `category_original` records the old label. Undo: set it back to `shadow` or `off`.
**Finding of the first live shadow approval (Fikru Cheklie, sequence 1, 2026-10-10 02:19 UTC):** GHL has NO contact matching his email, so no notice could reach him even with live switches: every real student needs a GHL contact (email and ideally phone) first. His quiet-hours-held first call/text were skipped by design (the 9 AM attempt is within 3 hours). The sequence counts as 1 of the pilot's 3 places: delete the shadow sequence(s) when the rehearsal ends. Kes was asked whether to close sequence 1 now (no answer yet).

### 2026-10-10: the approval card now says plainly when nothing will be delivered (shadow mode)

Kes saw the card for Fikru Cheklie say "Approving this will: Starts a call, a text and an email to the student, then follows up until they confirm" while production is in shadow (no `GHL_WRITE_*` switch), where nothing is delivered: a misleading sentence. `notifications.py`: `_delivery_is_live()` (all three switches live, via `GhlConfig.is_live`); `review-queue` returns `delivery_live`, and `will_happen` says "Nothing reaches the student: the system is in SHADOW mode ... Tell the student by hand if it matters" unless delivery is live. `NotificationQueue.tsx`: a red "Shadow mode" banner at the top of the list when escalation is on and delivery is not live. Tests for both modes; the old wording test now sets the three switches. Typechecked; the banner itself was not looked at in a browser (the local stack has escalation off). Needs `--build-web`.

### 2026-10-10: Fikru Cheklie verified; this log brought up to date

Kes verified Fikru Cheklie in the app (student 9, admin, 2026-10-10 00:56 UTC). His draft (100) had been closed while he was unverified, so it was set back to `draft`
(Focus GTS, Phone Screen, Mon 2026-10-12 11:00 EDT, no phone on file, personal email and Gmail present). Production is in shadow, so approving his card would only log: he has to be told by hand.
Five students are still unverified. **Decisions Kes made this session** (all reflected in the entries below): Gmail folders follow the workbook, "More Information Request" keeps its name; Assessment notice wording approved;
Interview Request = a direct interview offer only; Position on hold / Potential Scam / Recruiter Connect left as they are; leave the Trash emails in Trash; stale-draft alert OFF; Rob checks only email and Kes verifies in the app;
shadow rehearsal first and staff test on Monday after validation, no fake accounts, three `GHL_WRITE_*` switches only after validation, production stays in shadow; plan stops at the interview; conversations key on the server.
**Mistakes of this session, now fixed:** Approve crashed with a 500 (wrong import path); then the opposite risk: the API could read the real SMTP login so Approve could have emailed a real student (now off by default); a stale test patch emailed
student@example.com four times (guard added); the follow-up job ignored `.env`; a deploy took a feature branch instead of `master`. Summary and rules: the RESUME block at the top of this file.

### 2026-10-10: GHL conversations key on the server; production stays in shadow

Kes approved copying `GHL_CONVERSATIONS_API_KEY` from the local `.env` to the server `.env` (not printed; 67 characters on both sides; `.env.bak.<time>` saved). It is READ-only: the follow-up job can now read student replies and call logs (`poll: sequences=0 new_messages=0 stopped=0 errors=0` on the first run). Kes: "keep production in shadow mode for now": `GHL_WRITE_MODE`, `GHL_WRITE_SHADOW_LOG_ONLY` and `GHL_WRITE_NOTIFY_FIELDS` remain unset (verified: 0 lines), the one-email Approve stays off, escalation is on with channels `ghl`. Still temporary: the approver role email is Kes's (restore robelyn@colaberry.com after the rehearsal).

### 2026-10-10: the follow-up plan stops at the interview (Kes approved)

Kes asked what happens if the notice arrives Monday, the phone screen is Tuesday and the student never confirms: the plan sent 15 notices, 6 of them AFTER the interview (the plan never looked at the interview date). Now (`escalation_schedule.py`, `escalation_engine.py`, `notify_channels.py`, `notifications.py`): nothing is planned or sent at or after the interview time; follow-ups less than an hour before it are dropped; short-notice interviews (within 36 h, time known) get a final text and email 2 h before and same-channel reminders at least 2 h apart; interview already over = nothing planned and Approve refuses it; the sequence closes as `interview_passed` when the time arrives; the "no response" alert never comes after a near interview; no date = unchanged four-day plan. Example: Monday 3 PM approval, Tuesday 2 PM interview = 11 notices, all before the interview (was 15). Directive section "The plan stops at the interview". Simulation scenarios S11 to S13 (13 students, 29 checks); 8 new schedule tests, 2 approve tests. Production stays in SHADOW (no GHL write switches).
**Rehearsal note:** the three random students' drafts were not usable: Kes rejected two as job invites (8:52 PM ET) and the third (Rutendo, Oncor) is a Sept 28 interview that the new guard would refuse; draft 12 was closed.

### 2026-10-10: the follow-up job ignored the switch (it never read .env)

The live log `/opt/ai-inbox-manager/logs/notify_tick.log` said "Escalation is disabled (NOTIFY_ESCALATION_ENABLED not set)" although the flag is true in the server `.env`. Cause: `execution/notification_tick.py` asks `enabled()` before anything has loaded `.env` (cron starts it with only the container's own environment; the API and other scripts load `.env` through their imports), so the job would have done nothing in the rehearsal. **Fix:** it loads `.env` first (`NOTIFY_TICK_ENV_FILE` can point elsewhere, used only by the 2 new tests). Needs a deploy (the container mounts the repo).

### 2026-10-09 (night): simulation of the cadence with 10 made-up students (no real contact)

Kes: "start the test to monitor the cadence and different scenarios, 10 made-up students with fake phone and email". New `execution/simulate_notifications.py` (run: `python execution/simulate_notifications.py`, `--brief` for checks only): in-memory SQLite, recording dry-run channels (the real wording), a stub for the reply-reading AI, alerts captured in memory, a fake clock that runs the real `tick` every 5 minutes for 6 days. 10 scenarios (silent; YES by text; email link; yes on the call; STOP; question; "can't make it"; nothing on file; approved at 10 PM; not found in GHL) across four US time zones. 21 checks, all pass; guarded by `tests/execution/test_simulate_notifications.py`. **What it shows:** day 1 = call+text+email at approval, email at +2h, text+email at +4h; days 2 to 4 = call+text+email at 9 AM local (silent student: 4 calls, 5 texts, 6 emails, then "ended"); one call per local day; calls 8 AM to 8 PM, texts 8 AM to 9 PM local; confirmation and STOP cancel everything planned; the approver hears of STOP, replies needing help, "no response" (about +6h, once) and "ended" (once); a student with nothing on file is flagged at once and nothing is attempted.
**Findings for a decision (nothing changed):** (1) a student who says "I can't make it" or asks a question KEEPS getting calls, texts and emails for four days (the approver is told, but follow-ups continue; the reading AI only records until 2026-10-16): consider pausing after a "needs help" reply. (2) Emails are not held at night: an approval at 10 PM local sends emails at 10 PM, 12 AM and 2 AM (Ali's rule: email any time). (3) A student approved at night gets their first call and text only at 9 AM the next morning (the 8 AM held attempts are skipped on purpose because the 9 AM daily attempt is within 3 hours). (4) A student not found in GHL produces nine failed attempts but only one alert (fine), the email still goes.

### 2026-10-09 (night): shadow rehearsal switched on (Kes approved items 4 and 5)

Kes's answers: shadow rehearsal first with random real students; staff test on Monday after the shadow test is validated (staff use their own GHL contacts, no fake accounts); escalation on for the shadow test; tick cron approved; the three GHL write switches approved AFTER validation; the live tests on Kes's own contact (greeting re-test, text and email tests, test callback) "today if the shadow test works".
**Done:** server `.env` `NOTIFY_ESCALATION_ENABLED=true`, `NOTIFY_CHANNEL_EMAIL/SMS/CALL=ghl`, no `GHL_WRITE_*` (checked in the api and cron containers: shadow, live writes impossible); API restarted; host cron `/etc/cron.d/inboxgenius-notify` (every 5 min). Three random verified students with phone and email (drawn at random from the four that qualify): Sarbjit Kaur (draft 85, Nvidia), Aisha Hobbs (draft 61, CBC), Rutendo Bwerazuva (draft 12, Oncor): their old rejected drafts were set back to `draft`. Kes approves them in Review; each approval starts a sequence that the tick only LOGS. The pilot limit counts every sequence (3): when the rehearsal is validated these shadow sequences must be deleted so the live pilot has its 3 places.

### 2026-10-09 (night): the one-email Approve is now OFF by default (it could have emailed a real student)

I had told Kes Approve was blocked because the API container had no email login. WRONG: `send_notification.py` runs `load_dotenv()`, so inside the API container `SMTP_USERNAME`/`SMTP_PASSWORD` ARE set from the server `.env` (checked, booleans only); `printenv` only shows the container's own environment. So a click on Approve (old one-email path, escalation off) would have sent a real email from kes@colaberry.com (BCC the interview mailbox). It did not happen: after the 2026-10-09 deploy no draft was approved or sent (statuses: only draft and rejected). **Fix:** `_ensure_email_sending_configured` first requires `SINGLE_EMAIL_APPROVE_ENABLED` = true (unset on the server = off, clear 409 "switched off until the three-channel flow starts") and is called only when escalation is OFF (it had wrongly also gated the three-channel path). Tests: switch-off test; the tests that approve by single email set the switch.

### 2026-10-09 (night): a test was emailing student@example.com for real; tests can no longer send email

Kes found "Interview Notification / You have an interview." bounces to student@example.com (4:20, 5:26, 5:44, 6:22 PM Eastern) and copies in the interview mailbox (BCC). **Cause:** `services/dashboard/tests/test_roles.py::TestPilotLimit::test_the_limit_does_not_apply_while_escalation_is_off` approves a draft through the single-email path and patched the OLD import path `execution.send_notification.send_email`. When Approve's import was fixed (20:2x UTC), that patch stopped matching, so the test called the real `send_email` with the real SMTP login that `send_notification.py` loads from `.env`: one real email per run of the dashboard suite after that change (4 runs). Earlier runs were safe (patch and import matched). **Fix:** the test patches `send_notification.send_email`; both `conftest.py` files (`tests/`, `services/dashboard/tests/`) now have an autouse guard that blocks `smtplib.SMTP`/`SMTP_SSL` and FAILS the test if anything tries (send_email swallows every exception, so the guard records the attempt and asserts at teardown). Effects in production: the 8 copies were filed as "Other" in Spam Review, no events or drafts, no student at example.com. Lesson: after changing an import path, grep every patch target for the old one.

### 2026-10-09 (night): "Verify students" is its own tab; Review hides mail older than 14 days

Kes: the waiting cards were still in the Review list (the collapsed section from the entry below still sat on that page). Now `ReviewPage.tsx` has a third tab **Verify students (N)** that holds the cards for students not yet identified or verified (`NotificationQueue mode="verify"`); the first tab shows only what can be decided or fixed today, and its banner just says how many are waiting. Server side: the review queue skips mail received more than `REVIEW_MAX_AGE_DAYS = 14` days ago unless "Show finished" is on (that removed the 5 old no-student events from Sept 18 to 25). Test added; 225 dashboard tests. Checked in a real browser locally. Needs `--build-web`.
Also found while looking: draft 100 (Focus GTS, "Pre Screen", Monday 2026-10-12 11:00 EDT, student fcheklie@gmail.com unverified) is a real, time-sensitive interview whose student nobody can notify through the app until verified: tell the student by hand.

### 2026-10-09 (night): Review list: students waiting to be identified or verified are tucked into a collapsed section

Kes still saw 6 "entries that need verification": the 5 events with no student plus one new draft (id 100) for an unverified student. Moving their emails in Gmail does not remove their cards, so `NotificationQueue.tsx` now splits the list: cards that can be decided or fixed today stay in the main list and the banner ("N ready, M need fixing" no longer counts waiting students); students not yet identified or verified (states `needs_student`, `needs_verification`) go into a collapsed "Waiting for the student to be identified or verified (N)" section with a note that their emails are in the Gmail label "Verify Student" and nothing there is sent. Nothing is hidden for good: expanding shows the same cards. Verified in a real browser against the local stack. Needs `--build-web`.

### 2026-10-09 (night): "No student identified" emails moved to the Verify Student label

Kes asked to move the emails of the "No student identified" cards to "Verify Student" in Gmail. `execution/label_verify_students.py --no-student` (plan only without `--apply`) selects interview events whose `student_id` is empty: 5 in production (3 in INBOX, 1 Interview Confirmation, 1 Phone Screen), all older than 14 days, no drafts. Same safe method as before (label found by Message-ID in All Mail, then removed from the old folder only, `current_folder` updated). 1 new test.
**Follow-up finding (Kes asked why):** the 5 events (Sept 18 to 25) and 4 emails the backfill skipped earlier are all in Gmail's TRASH (found by Message-ID: 9 of 9; none in All Mail or Spam), so they cannot be labelled. Nobody knows who deleted them (the pipeline never deletes; most likely cleared by hand). **Kes: leave them in Trash** (Gmail empties Trash after 30 days, the oldest around 2026-10-18).

### 2026-10-09 (night): approval list cleared for next week (production database, no deletions)

Kes: clear the review list. Result: 96 drafts in total, **93 rejected, 3 pending**. Reasons are saved on each draft (`send_error`) and the reviewer is "cleanup 2026-10-09 (Claude, at Kes request)".
- 46 clear non-interviews (earlier pass), 21 old (email over a week old or interview passed), 14 non-interviews (job postings, vendor marketing, an acknowledgement, a pay-rate confirmation): ids 33,35,43,76,87,50,38,29,83,82,77,56,45,68.
- 3 told by hand or already past: 84, 86 (Orange County, Kes told the student) and 98 (TEKsystems meeting reminder).
- 4 for unverified students, possibly real (25 Tier4 reminder, 31 Addison, 64 ADP, 94 CyberKy): their original emails are already in the Gmail label "Verify Student"; the drafts are closed for now. **To bring one back:** after the student is verified and if the interview is still ahead, set the draft's `email_status` back to `draft` (or ask Claude); no card reappears by itself.
- Still pending (verified students, uncertain recruiter threads): 46 Adecco first contact, 74 e-solutions reply thread, 80 CGI reply thread.

### 2026-10-09 (end): callback emails carry the student's context (why they called, interviews, what we told them)

Kes: when the escalation contact is brought in she needs to know why the student called and the recent communication history. `execution/callbacks.py`: new `context_lines()` used by BOTH the callback owner's alert and the escalation role's overdue email (the overdue one only had name, number and wait time before): their own words, how to reach them, their last three interviews with when the email arrived, notices the app sent (channel, time, status), their replies and confirmation, earlier callbacks from the number; one block per student in the overdue email. Read-only, capped. 2 new tests. Directive section "Callbacks" updated. The email that was already sent to the escalation contact described the older, shorter alert: nothing in it is now wrong, the alert simply says more.

### 2026-10-09 (end): one-off backfill `execution/label_verify_students.py` (label and move the emails of unverified students)

Kes: "Label them in the Gmail and move them to the 'Verify Student' folder." For every pending draft whose student is unverified: apply the label (found by Message-ID in All Mail), then take the email out of the folder it was filed in (flag deleted + UID EXPUNGE in THAT folder only, the documented method of `move_emails`), then set `emails.current_folder = "Verify Student"`. Plan-only by default; `--apply` changes Gmail and the database; `--keep-in-place` labels only. Skips anything it cannot find, never deletes a message, never touches a verified student's mail. 4 tests with a fake mailbox. Note: the new pipeline label (previous entry) only labels in place; this one-off also moves, as Kes asked for the existing mail.

### 2026-10-09 (end): "Verify Student" Gmail label on the original email (Kes chose option B)

When the student for an interview email had to be guessed from the delivery Gmail (the orange "Verify who this student is" case), the pipeline now adds the Gmail label **Verify Student** to the ORIGINAL email, in place: no move, no flag, no expunge (`fetch_emails.label_emails`, run before `move_emails` so the UID is still in INBOX; Gmail creates the label). So the approver can find them in a Gmail folder instead of the dashboard. `process_interview_email` sets `classification["_needs_verification"]`; `process_inbox_auto` collects `verify_labels`. Only mail processed after this deploy is labelled: the existing flagged students' emails are NOT backfilled (needs a one-off IMAP run on the server). Tests: `test_fetch_emails.py` (2), `test_workbook_categories.py` (1).
**Same session, production database:** 46 pending drafts that are clearly not interviews were rejected (job postings and the dd.job-assist-now.com / job-matches.com mailers; reason saved on each draft, nothing deleted; ids in the scratchpad `rejected_ids.txt`). A second batch of 21 old drafts (email over a week old or interview already passed) was prepared but the production write was BLOCKED by the permission system and is NOT done; ids in `old_ids.txt`.

### 2026-10-09 (end): scan of the 93 pending approval cards; job-matches.com filed as Job Alert

Kes asked to scan the review list and remove the non-interviews. Each pending draft was scored with the dashboard's real-interview check and the new classifier prompt: 46 are clearly not interviews (job postings from staffing firms, and lead-generation mailers from dd.job-assist-now.com and job-matches.com); 5 more (micro1 "complete your interview" reminders, one Eliassen "Application Next Steps" reminder) could be real steps for a student and were held back; 29 are uncertain; 13 look genuine. The bulk reject on the production database was BLOCKED by the permission system, so nothing was removed yet; the draft ids are in the scratchpad file `rejected_ids.txt` and in the chat. Added `job-matches.com` to `JOB_BOARD_DOMAINS` (with a test) so these stop creating cards.

### 2026-10-09 (end): a Teams join link no longer counts as "click-tracking"

The real-interview check on a genuine Orange County CU invite said "Links go through a click-tracking address (teams.microsoft.com)": any link whose path had 40+ unbroken characters counted as tracking, and a Teams meeting URL always does. `execution/email_authenticity.py` now skips known meeting hosts (Teams, Zoom, Meet, Calendly, Webex, GoToMeeting, Whereby) in that test; real tracking links (for example dd.job-assist-now.com) are still flagged. Two tests added.
Kes's reading of the second email: a phone screen already happened and the recruiter offers a follow-up Teams interview with an AVP on Wed 2026-10-14 at 11am or 4pm (a next-round request, then confirmed for 11am). The student was told by hand.

### 2026-10-09 (end): Approve returned a 500 in production (wrong import) and now says why it cannot send

**Symptom (Kes, real interview card):** "Yes, approve" showed "Request failed with status code 500". **Cause:** the single-email path in `services/dashboard/api/routers/notifications.py` did `from execution.send_notification import send_email`; the API container has no `execution` package (other code puts `execution/` on `sys.path` and imports by bare name), so every Approve crashed BEFORE sending or changing anything. The tests passed because they patched the same wrong path and the repo root is on the test path. Approve had never worked in production on this path.
**Second cause found:** the API container has no `SMTP_USERNAME` / `SMTP_PASSWORD` (they are in the server `.env` but not passed into the container), so even with the import fixed no email could go out.
**Fix:** `_send_draft_email` loads `send_notification` by bare name; `_ensure_email_sending_configured` runs BEFORE the draft is marked approved and answers 409 with a plain message when there is no SMTP login (draft untouched, nothing sent, no checklist step ticked). Tests now patch `send_notification.send_email`; new test for the 409. Nothing is sent by this change.
**Open (Kes decides):** how real notices leave the app: give the API container the SMTP login (single email to the student's address, which for some students is only the job-application Gmail) or switch to the three-channel GHL flow (shadow rehearsal, then live pilot).

### 2026-10-09 (end): job-assist-now.com filed as Job Alert by rule

Kes read the Sehrish card's email: "confirm your interview availability ... a potential interview" from `info@dd.job-assist-now.com` is a lead-generation mailer (unsubscribe link and mailing address), not an interview. Added the domain to `JOB_BOARD_DOMAINS` in `execution/process_inbox_auto.py` (rules fire before the AI) with a test. The card already in the queue stays until Kes rejects it.

### 2026-10-09 (end): approval card shows when the email arrived

Kes could not tell when a message came in while verifying a card. `services/dashboard/frontend/src/components/NotificationQueue.tsx`: new first fact "Email received" (day, date, time in Central time, plus "8 days ago"); the old "When" label is now "Interview time" so the two dates cannot be confused. The API already sent `email.received_date`; no backend change.
Verified in a real browser against the local stack (Playwright with Chrome). Needs `scripts/deploy_hetzner.sh --build-web`.

### 2026-10-09 (end): stale-draft alert switched off; Gmail label clean-up under way

Kes: "keep it off for now". The host cron file was moved aside (see RUNBOOK section 16 for the one-line way back); nothing in the code changed. Jackie's email now covers only the overdue-callback alert.
Gmail label clean-up by Kes, one step at a time: Offer merged into Offers (done), Rejection into Rejections (done). Still to do: rename Interview Follow-up to "Interview follow up"; merge Interview Reschedule into Interview Rescheduled; merge the duplicate LinkedIn label; merge Interview Scheduling into Interview Request; merge Background Check into More Information Request; later re-file Interview Confirmation, Final Interview Scheduled and First Interview Scheduled by type once `CATEGORY_REMAP_MODE=live`.

### 2026-10-09 (late): use-case page and artifact updated; email to the approver drafted

`docs/use-cases.html` (and the artifact https://claude.ai/artifact/FRzyZVP1uBnsvMPEViEZiw, version 5) now cover roles (UC18), the callback flow (UC19), verifying the student (UC20), the one approval screen (UC21), the workbook folders, the Job Invite rule,
Technical Interview / follow-up / Job Machine / Client Screen events and the stale-draft alert. Gmail draft to the approver (what to verify and watch, final folder list) created, not sent.
**Decisions from Kes:** Assessment wording approved; Gmail labels Position on hold, Potential Scam, Recruiter Connect left as they are; the "More Information Request" folder keeps its name (3,000+ mails); an idea to use 3 Colaberry staff as the first pilot recipients (to confirm).
**Open (receptionist):** the new INTERVIEW CALLBACKS wording is still to be pasted into the GHL AI Receptionist (the old "shortly" text is still in the pasted prompt).

### 2026-10-09 (night): Interview Request must be a DIRECT interview offer; Job Invite vs Job Alert defined; Assessment wording approved

**Kes's rule (2026-10-09):** a recruiter's job posting is not an interview; the recruiter decides after the candidate replies with an updated resume, and only a later message that actually offers an interview counts.
**Changed:** `classify_email.py` prompt: Interview Request needs the email itself to ask for availability / offer slots / name a date; "Immediate Interview Role" job titles are Job Invite; Job Alert = automated bulk digest, Job Invite = a recruiter writing about ONE role.
`email_templates.py`: the Assessment notice now says "This is a test, not an interview", points to the sender's email for details and deadline, and asks the student to reply "done" (wording approved by Kes; Ali's own sign-off still welcome).
**Re-test on the 273 real emails:** 32 of 61 stored "Interview Request" demoted (all postings or "immediate interview" blasts; the 6 with "interview" in the subject were W2 job posts); the genuine ones stayed
(Phone Screen / Cancelled / Confirmation / Schedule: 24 of 29 kept). "RTR" (right-to-represent) and "RE:" replies from staffing firms now read Job Invite: watch them.
**Gmail filters (Kes's screenshot):** server-side Gmail filters already file LinkedIn "You applied for" and Indeed applications to Application Notification, Indeed alerts to Job Alerts, applytojob "we've received your resume" to
Received Resume, LinkedIn security mail to Account Recovery; most skip the inbox or mark read, so the pipeline never sees them. "Received Resume" is an application receipt. Labels Position on hold, Potential Scam, Recruiter Connect left as they are for now (Kes).

### 2026-10-09 (evening): workbook categories (Technical Interview, Interview Follow-up), Client Screen and Job Machine events, retired categories in shadow

**Changed:** `execution/classify_email.py`: new categories Technical Interview and Interview Follow-up (prompt definitions and disambiguation vs Assessment / Interview Request / Rejection); a confirmed interview is now filed
by its TYPE (client, technical, phone) and Job Invite explicitly covers staffing-firm outreach for one open role; `remap_retired_category` re-files the retired Interview Schedule / Confirmation / Final Interview Scheduled
(`CATEGORY_REMAP_MODE=off|shadow|live`, default **shadow**: only `category_shadow` is recorded). `execution/process_inbox_auto.py`: folders "Technical Interview" and "Interview follow up"; Technical Interview and Client Screen
now create interview events (Client Screen created none before); Job Machine mail creates an event only when the interview sub-classifier reads it as an interview, reschedule or cancellation (before: never);
Interview Follow-up creates no event and no student notice. `execution/subclassify_interview.py`: reads the new categories. `validate_classification.py`: the two new names (that list was already out of step with the classifier).
**Evidence (re-classified 273 real emails from the last 90 days with the new prompt, counts only):** 215 same label, 58 different. All 8 Phone Screens and 5 of 7 Interview Cancelled stayed (the other 2 were application notices);
17 of 61 stored "Interview Request" came back as Job Invite / Job Alert / Other and are staffing-firm job blasts ("Contract Opportunity - Power BI Developer"), so fewer false interview events; "Interview Cancelled" mislabels
of "Thank you for applying" came back as Rejection (still not Application Notification). The two new categories had no real examples in the sample, so they were tested on 9 synthetic emails: 9 of 9 right.
**Not done:** go-live decision for the prompt change (it moves about 1 in 5 stored labels); `CATEGORY_REMAP_MODE=live`; Assessment-notice wording with Ali; the audit of Job Invite (22 of 40 stayed Job Invite, 17 became Job Alert).

### 2026-10-09 (later): sender rules match subdomains (step 1 of the classification rework, first part)

**Measured on 4,000 real emails from the last 9 days (metadata only, scratch copy, nothing printed per row):** the rule layer `pre_classify_by_sender` fired on only 26% of mail because it matched
`@indeed.com` literally, so `alert.indeed.com`, `jobalert.indeed.com`, `alert.refer.io`, `my.theladders.com` and so on went to the AI (1,576 Job Alerts, 28% "Other"). Other findings: 28% of mail is "Other"
(retail, social, personal; Quarantine is mostly right); real interview mail is about 1.5% (about 60 of 4,000); 37 LinkedIn promotions were filed as "Other"; the app's own "[InboxGenius] notification draft(s)"
alerts land in Spam Review.
**Changed:** `execution/process_inbox_auto.py`: `_sender_domain` and `_domain_is` (suffix match on the real domain, so look-alikes such as `fakeindeed.com` or `indeed.com.evil.net` do not match);
LinkedIn, job boards (added refer.io, adzuna.com, jobs2web.com, jobs2careers.com, theladders.com, postjobfree.com) and Basecamp now use it. Rules now fire on 55% of the sample (was 26%): 61 stored labels
would differ (37 LinkedIn promotions Other to LinkedIn Notification; 24 job-board mails Other or Job Invite to Job Alert, as the prompt already says). Tests added in `tests/execution/test_folder_names.py`.
**Not done yet:** Technical Interview and Interview follow up categories; Job Machine events; Assessment notice; collapsing Schedule/Confirmation/Final; the self-alert rule; audit of Job Invite (161 of 4,000).

### 2026-10-09: Gmail folder names follow Ali's "Email Management - Labels" workbook (step 0 of the classification rework)

**Why:** Ali's workbook (22 folders, plus 7 action playbooks) is the authority for folders. Kes renamed/merged the Gmail labels by hand on 2026-10-09 (Offer to Offers, Rejection to
Rejections, Interview Follow-up to Interview follow up, duplicates merged), so the pipeline had to file into the same names.
**Changed:** `CATEGORY_TO_FOLDER` in `execution/process_inbox_auto.py`: Offer to "Offers", Rejection to "Rejections", Background Check to "More Information Request" (that folder keeps its name: 3,000+ mails already sit in it, Kes 2026-10-09),
Interview Schedule to "Interview Request" (the "Interview Scheduling" folder is retired). Category names inside the app are unchanged (dashboard, stats, templates unaffected); rows already in the
database keep their old `current_folder` text. New test `tests/execution/test_folder_names.py` fails if the pipeline files into a folder the workbook does not have.
**Findings (from Kes's Gmail sidebar, unread counts only):** unread mail sits mostly in Job Alerts (3,590), LinkedIn (2,913 across two labels), Job Invite (1,655), Application Notification (728),
Quarantine (563). "Needs Review" has 1 unread, so it is not the pile-up that the code reading suggested. Job Invite and Quarantine are the two folders to audit for real interviews filed as noise.
**Next (not done):** step 1 shadow rewrite (category list = workbook, fixed rules by sender/subject before the AI, add Technical Interview and Interview follow up, wire Job Machine into events,
Assessment notice on the same three channels, Background Check merged); step 3 re-file Interview Confirmation / Final Interview Scheduled / First Interview Scheduled by type; audit sample of
Job Invite and Quarantine; ask Ali about Position on hold, Potential Scam, Received Resume, Recruiter Connect (labels not in code or workbook; check Gmail filters).

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

### (older) RESUME HERE as of the end of the 2026-10-02 session (superseded by the block at the top of this file)

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

### 2026-10-15: a cancelled role is not a cancelled interview (merged to master and deployed 2026-10-15 as 5279e9a; server `.deployed_commit` matches)
- Why: Vizient's "the role has been cancelled" email was labelled Interview Cancelled (0.95) and drafted "the employer has cancelled this interview"
  for two students (drafts 120, 121). The model had no label for a role withdrawn before any interview; the prompt even listed "position filled" as an
  Interview Cancelled signal.
- `execution/classify_email.py`: new pure rule `role_cancelled_not_interview` (Interview Cancelled + role/position/requisition cancelled, closed or
  filled + the word "interview" appears nowhere) turns the category into **Rejection** in `apply_business_rules`, always on. A Rejection makes no
  interview event, so no student notice, no pilot-limit slot, no alert. Prompt: Interview Cancelled now needs an interview; role cancellations go to Rejection.
- Tests: `tests/execution/test_role_cancelled.py` (Vizient email, real interview cancellation untouched, wordings, other categories). Suite: 968 passed.
- Deferred: draft 121 (Omolola) still pending on the server, reject by hand. One email made drafts for two students (11702/11703): not investigated.

### 2026-10-16: follow-ups on an already announced interview make no new notice (branch `feat/follow-up-on-scheduled-interview`, not merged or deployed)
- Why: Sehrish's queue held 7 cards for ~3 meetings: Calendly confirmation (approved 14 Oct), then Hydrafacial replies, a second Calendly mail and a
  Wilson HR invite, two labelled "Rescheduled" although nothing moved (12:00 PST = 15:00 EST on 19 Oct). Nothing compared a new email with what the student
  was already told.
- New `execution/interview_followup.py` (pure rules, no LLM) + table `interview_follow_ups` (model `InterviewFollowUp`, migration 009; a NEW table, because
  create_all cannot add columns). `process_inbox_auto.process_interview_email` links a matching event and creates no draft. Review list: such events are
  hidden, shown under Show finished with state `follow_up` / `follow_up_of`. Frontend label added. `python execution/interview_followup.py [--apply]` cleans
  the pending queue (dry run by default).
- Tests: `tests/execution/test_interview_followup.py` (14), one in `services/dashboard/tests/test_review_flags.py`. Whole suite 1063 passed; frontend `tsc` clean.
- Deferred: cancellations with no date still make a card (cannot be matched safely); Calendly setup mail ("How do you prefer to meet?") is still treated as an
  interview; Upcoming/Interviews pages still list follow-up events.

### 2026-10-16: suggested action on each Review card (branch `feat/review-suggested-action`, not merged or deployed)
- Why: after the follow-up work Kes pointed out the CGI card (#132, a repeat of #122 which he rejected) still showed only "Looks like a real interview" and a green
  Approve. The system knew more than the card said.
- `execution/interview_followup.suggested_action` (pure rules) -> `suggestion {action, text}` on each open item of `GET /api/notifications/review-queue`;
  the card shows a coloured line (Reject / Check first / Approve) above the genuineness box. Frontend change: needs a web rebuild (`--build-web`).
- Tests: 8 new in `tests/execution/test_interview_followup.py`, 1 in `services/dashboard/tests/test_review_flags.py`.

### 2026-10-16: cancellation suggestion lists only dated notices (merged and deployed with the card change)
- Found on the live queue: Sehrish's "Canceled" card listed the undated setup notice #125 as an announced interview. `suggested_action` now lists only dated ones.

### 2026-10-18: Upcoming interviews hides rejected duplicates and follow-ups (branch `fix/upcoming-hides-rejected-duplicates`, not merged or deployed)
- Why: Kes rejected the duplicate CGI / Hydrafacial cards in Review, but the Upcoming table still showed one row per event (4x CGI Power BI Client Screen).
  Rejecting a notice only closed the notice; `GET /api/interviews/upcoming` never looked at notice status. This was the "Upcoming still lists follow-up events" deferred item.
- `services/dashboard/api/routers/interviews.py`: `/upcoming` now skips events linked in `interview_follow_ups` and events whose notices are ALL rejected. Events with no notice stay.
- Tests: 3 new in `services/dashboard/tests/test_interviews.py`; interviews + date-filter tests 29 passed.
- Needs a backend deploy. Deferred: the Reports "Interviews" tab list may use a different query; the 2 Sehrish Hydrafacial rows (Phone Screen + Rescheduled, same 15:00) only collapse if one notice is rejected.
- Same branch: dashboard "Upcoming interviews" table drops the Join link column and merges Date + Time into one "Date & Time" column (Today/Tomorrow badge, then "Oct 19, 06:48"). `DashboardPage.tsx`; needs `--build-web`.

### 2026-10-18: Upcoming collapses duplicates instead of hiding rejected ones (branch `fix/upcoming-collapse-not-hide-rejected`, not merged or deployed)
- Why: the earlier same-day change hid every event whose notices were all rejected. On the live dashboard that removed CGI (all 4 events rejected by admin),
  Rutendo's assessment and Orange County, leaving one row. A rejected notice means "do not tell the student", not "not an interview".
- `/api/interviews/upcoming` now hides only events linked in `interview_follow_ups`, and shows identical events (same student, company, date, time) once.
- Tests: 2 replaced in `services/dashboard/tests/test_interviews.py`; dashboard suite 252 passed.
- Known: Hydrafacial rows are follow-ups of event 139 (Sehrish, no company, 12:00), so they show as that one row without the company name.

### 2026-10-19: routine replies and cancelled positions (branch `fix/quoted-text-and-cancel-match`, not merged or deployed)
- Why: Sehrish's HRize/Sonata thread. "I am calling you right away" made a full interview notice (07:30 PST, video) because the time came from the quoted
  thread under the reply; nothing stripped quoted text. The "position cancelled, interview will no longer be scheduled" mail escaped `role_cancelled_not_interview`
  (it contained the word "interview") and its card said "Looks like a real interview" without saying which interview it cancelled.
- `execution/classify_email.py`: `strip_quoted_reply`, `is_routine_reply` (a "RE:" mail with short new text and no time/date/scheduling word, with something
  quoted below -> category Other, no event, no notice); `role_cancelled_not_interview` now reads only the new text and ignores "interview ... no longer be scheduled".
- `execution/interview_followup.suggested_action`: a cancellation naming the one announced interview of that company says which (approve).
- `NotificationQueue.tsx`: cancellation cards say "Is this a real cancellation?" instead of "real interview". Needs `--build-web`.
- Tests: `tests/execution/test_routine_reply.py` (8), 1 in `test_interview_followup.py`. Suite 1080 passed, dashboard 252 passed, `tsc` clean.
- Deferred: the two existing Sehrish cards (#141 Sonata, the 12:20 PM cancellation) are not touched; reject by hand. Reply rule applies only to "RE:" subjects.

### 2026-10-19: "Interview Requests Today" tile counts interviews, not emails (branch `fix/interview-count-tile`, not merged or deployed)
- Why: the tile counted emails classified "Interview Request" today, so it still said 2 after Kes rejected Sehrish's cards, and counted replies and cancellations.
- `services/dashboard/api/routers/stats.py`: `count_interview_requests` counts today's interview events, skipping follow-ups, "Interview Cancelled" and events whose
  notices are ALL rejected. Pending and approved count; an event with no notice counts. Rejecting a card lowers the tile. "total_interview_requests" (all time) is unchanged.
- Tests: `services/dashboard/tests/test_interview_tile.py` (4). Dashboard suite 256 passed. Backend-only: no web rebuild.
- Note: today's count of already-processed emails is rebuilt from interview events, so past days may also change.

### 2026-10-19: tick / cross / dash on each Upcoming interview (branch `feat/upcoming-real-mark`, not merged or deployed)
- Why: Kes could not tell real interviews from non-interviews in the Upcoming table (Sonata 07:30 was a cancelled position, still listed).
- `services/dashboard/api/routers/interviews.py`: `/upcoming` rows get `verdict`: `real` (a notice approved or sent), `not_interview` (every notice rejected, or a LATER
  "Interview Cancelled" event of the same student names the same company), `pending` (undecided). Identical events collapsed into one row keep the most certain verdict.
- `DashboardPage.tsx` + `types/index.ts`: new "Real?" column: green tick, red cross, grey dash. Needs `--build-web`.
- Tests: `services/dashboard/tests/test_upcoming_verdict.py` (4). Dashboard suite 260 passed, `tsc` clean.
- Deferred: follow-ups stay hidden (not shown with a cross); a cancellation with no company cannot cross anything out; assessments follow the same notice rule.
