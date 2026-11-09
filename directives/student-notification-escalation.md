# Directive: Student Notification, Acknowledgement and Escalation

**Status (2026-10-02): the core is BUILT and DEPLOYED but SWITCHED OFF, and every channel is a dry run.**
Approved by Ali (email 2026-10-02) and Kes. Kes told Claude to "build it for now", ahead of Ali's condition
that Kes confirm with the approver first, so nothing real is sent: the escalation is off unless
`NOTIFY_ESCALATION_ENABLED` is set, and each channel defaults to `dry_run` (logs what it would send).
Turning it on for real students needs the "Before turning it on" checklist at the bottom.

## What is built
| Piece | File |
|---|---|
| Schedule, quiet hours, time zone from area code | `execution/escalation_schedule.py`, `execution/area_code_timezones.py` |
| Engine: start, tick, acknowledge, close, replies | `execution/escalation_engine.py` |
| Channels: `dry_run`, `smtp` (email), **`ghl`** (all three, shadow-gated); text gate and budget | `execution/notify_channels.py` |
| GHL client: retries (incl. GHL's disguised 401 timeout), rate limit, field lookup by label/key, DND and opt-out-tag check, shadow gate | `execution/ghl_client.py` |
| Reply reading: rules (YES/STOP) + AI in shadow mode | `execution/reply_analysis.py` |
| Scheduler pass (does nothing unless enabled) | `execution/notification_tick.py` |
| New tables only (existing tables untouched) | `notification_sequences`, `notification_attempts`, `reply_analyses`; migration `003` |
| Approve starts it (when enabled); email "I got this" link; the approver's status/close; secret-protected reply endpoint | `services/dashboard/api/routers/notifications.py` |
| Reading replies and calls from GHL Conversations (polling, idempotent, echo filter, student-only call words) | `execution/ghl_conversations.py`, `escalation_engine.poll_replies()`, table `notification_inbound` |
| Tests | `tests/execution/test_escalation_*.py`, `test_reply_analysis.py`, `services/dashboard/tests/test_notification_escalation.py` |

## How Cora delivers each channel (researched 2026-10-02 in `cora-recap-engine`)
Kes asked how GHL triggers Cora's outgoing messages so we can follow the same pattern.
| Channel | How Cora does it | Source |
|---|---|---|
| Email | Write GHL custom fields: `Support Issue Ticket #2` = subject, `Message` = body. The GHL workflow **"AI Agent - Send Email"** fires when Ticket #2 changes (5 s wait). | `app/core/followup_routing.py` |
| SMS | Write GHL custom field `Support issue Ticket #4` = the text. The GHL workflow **"AI Agent - Send SMS"** fires when Ticket #4 changes. Cora first passes its own SMS gate (no links, 3+ words, 8 AM to 9 PM lead-local, daily budget capped at 999 segments, ledger table `sms_send_ledger`). | `followup_routing.py`, spec/34 |
| **Phone call** | **There is no Support Issue Ticket for calls.** Cora POSTs to a **Synthflow "Make Call" workflow webhook** (`SYNTHFLOW_LAUNCH_WORKFLOW_URL_New`, Bearer `SYNTHFLOW_API_KEY`, body `phone`, `name`, `campaign_name`, `prompt`, `metadata`). GHL's only role is that its New Lead / Cold Lead workflows call Cora's `POST /v1/webhooks/leads/{campaign}` (secret header `X-Cora-Webhook-Secret`), which then launches the Synthflow call. | `app/adapters/synthflow.py`, `call_intake.py`, `settings.py` |
| Tickets #1 and #3 | #1 = call summary, #3 = task description. Neither sends anything. | `crm_jobs.py` |

**Update, same day (Kes): the voice call IS field-triggered for this project.** The contact field
`interview_notification` triggers the GHL voice-agent workflow. So all three channels use the same pattern
and the `ghl` channel is built for each:

| Channel | Field(s) written | Workflow reacts to |
|---|---|---|
| Email | `Support Issue Ticket #2` (subject) + `Message:` (body) | Ticket #2 changing ("AI Agent - Send Email") |
| SMS | `Support issue Ticket #4` | Ticket #4 changing ("AI Agent - Send SMS") |
| Call | `interview_notification` | `interview_notification` changing (voice-agent workflow) |

Labels are env-configurable (`GHL_FIELD_NOTIFY_EMAIL_SUBJECT`, `_EMAIL_BODY`, `_SMS`, `_CALL`). The three Cora
labels are the defaults because they live in the same GHL location; `interview_notification` is matched by name
or key. Standards come from `.claude/skills/ghl-integration/KIT.md`: shadow by default, live only with
`GHL_WRITE_MODE=live` AND `GHL_WRITE_SHADOW_LOG_ONLY=false` AND `GHL_WRITE_NOTIFY_FIELDS=true`; writes by
field UUID; a successful write means "handed to GHL", not delivered; opt-outs checked before every send.

**Answers from Kes (2026-10-02) and what they changed:**
1. **The call value carries the interview facts, and only facts.** `interview_notification` holds, for example,
   `Attempt: first notice. Candidate first name: X. Interview details: Interview type: ...; Company: ...; Position: ...;
   Date: ...; Time: ...; Format: ...; Contact at the company: .... Reference: N.` (only facts we have; "date and time not
   confirmed yet" when unknown). The INSTRUCTIONS (greet, verify the person, deliver, ask for a yes, voicemail, stop request)
   live in the Voice AI agent's prompt: `docs/voice-agent-outbound-interview-prompt.md`. Built in
   `notify_channels.call_script()` / `interview_facts()`.
2. **A changed value re-triggers; an identical one does not.** So the 2nd, 3rd... call must read slightly differently:
   every value ends with a step tag ("Reminder 1:", "Day 2 reminder:", "Final reminder:") plus `Ref N`. Tested.
3. **Results are read from the candidate's GHL Conversations by API** (the second token, `GHL_CONVERSATIONS_API_KEY`).
4. **Replies go to GHL Conversations; all channels are handled by GHL.** So we POLL instead of waiting for a webhook:
   `execution/ghl_conversations.py` + `escalation_engine.poll_replies()`, run by `notification_tick.py` after each send
   pass. It reads inbound texts and emails (our own outbound emails logged as inbound are filtered out by the
   confirmation link and subject), and call messages with GHL's transcript. Each GHL message is handled once
   (table `notification_inbound`, unique message id). One student with two open notices is handled once for both.
   The `/inbound/reply` webhook stays as an optional extra.
5. **Every student exists as a GHL contact.** The contact is found by EXACT phone match (a near match is never used,
   two exact matches are refused) so one student's details can never go to another.

**Calls: Voice AI call logs (verified live 2026-10-02).** The voice agent is GHL's own Voice AI. Its calls are read from
`GET /voice-ai/dashboard/call-logs` (scope `voice-ai-dashboard.readonly`, works with the contacts token), filtered by
contact, `callType=LIVE` (no test calls) and optionally `GHL_VOICE_AGENT_ID` (set it to the outbound agent). Each log has
the duration, a summary, the actions triggered and a transcript of `bot:` / `human:` lines. Only the `human:` lines (the
student) ever reach the AI. A call counts as a conversation only if it lasted `NOTIFY_CALL_MIN_SECONDS` (default 10 s)
AND the student spoke; anything else is recorded and not analysed. Replaces my earlier Conversations-transcript reading
(which returns nothing on this account). `execution/ghl_conversations.py`: `human_words`, `reached_a_person`,
`fetch_new_calls`.

**GHL Voice AI outbound rules we must respect** (help.gohighlevel.com, "Voice AI Outbound Calling" and "...Compliance
Checks"): calls are placed 8 AM to 8 PM in the contact's phone-number time zone; **each phone number can be called once
per day and 14 times in 14 days**; 10 calls a minute and 5,000 a day per location; domestic numbers only; GHL does
**not** check consent or Do-Not-Disturb (we do, before every send); the From number must be one the action lists as
eligible. The same agent can serve inbound and outbound with the right prompt, but the docs do not say whether the same
number can; we recommend a separate outbound agent on the same From number.

**Verified live against the Colaberry account, read-only (2026-10-02):** all four trigger fields exist and are
large-text (`interview_notification`, `Support Issue Ticket #2`, `Support issue Ticket #4`, `Message:`); the call-log scope
works (152 live logs); the conversations token works and the contacts token is refused there; contact `phone` is E.164;
an exact-phone lookup returns the right contact; the `human:` parser never let an agent sentence into the student's words.
NOT done: no field has been written and no call placed (that needs a test contact; see "Still UNVERIFIED").

**Still UNVERIFIED:**
A. How the `interview_notification` value reaches the voice agent's prompt (the docs do not say). Needs one real test on
   a test contact. Expected: the outbound agent's prompt references the contact field.
B. That the existing number is an "eligible" From number in the Voice AI Outbound Call action.
C. Whether a call to a contact that already had a call today (any GHL Voice AI call) is blocked, which would also count
   Admissions' own calls.
D. How voicemail shows up in the call logs (no status field is documented): we treat "no human speech" as no conversation.

Earlier research, kept for reference (Cora's own code, not the GHL dashboard):

**Risks this raises for our build (do not skip):**
1. **Cora's SMS ledger only counts texts Cora itself originates.** Texts we send would be invisible to it and
   still consume the same 999 (T-Mobile) / 3,000 (all-carrier) budget. We must keep our own count, or route our
   texts through Cora's gate, before turning SMS on.
2. **Do not reuse Cora's Synthflow agent as is.** It is the "Outbound Admissions Agent", and every call it makes
   reports back to Cora, whose voicemail engine would then treat a student who did not answer as a lead and
   start calling, texting and emailing them. We need a dedicated Synthflow agent/workflow whose completion
   webhook points at our app (`/api/notifications/inbound/reply`).
3. **Synthflow agents talk; they do not read keypad presses.** "Press 1" probably becomes "say yes", and the
   confirmation comes back as a call transcript, which our reply reader can judge. To be confirmed with Synthflow.
4. Writing `Support issue Ticket #4` from our app would send an SMS from the shared number with none of
   Cora's safeguards. Anything we write there must pass our own content, quiet-hours and budget checks first.

## Goal
When a student has a new interview, make sure they actually know, today. Send the notice over
three channels (phone call, text, email), track whether the student acknowledged it, and keep
following up until they do. A person (the approver) approves the first send; nothing is auto-sent before that.

## Inputs
- An approved `NotificationDraft` (the approver clicked Approve) for a student with a phone number and email
- Student replies: SMS replies, email replies, keypad presses, email-button clicks

## Outputs
- Attempt log (every call/text/email, with status and Twilio SID)
- Acknowledgement record (which channel, when, explicit or AI-inferred)
- Alerts to the approver (no response after day 1; sequence ended)

## Schedule (T0 = the approver approves)
| When | Call | Text | Email | the approver |
|---|---|---|---|---|
| T0 | yes | yes | yes | |
| T0 + 2h | | | yes | |
| T0 + 4h | | yes | yes | |
| End of day 1, no acknowledgement | | | | **told** "student has not responded" (about T0 + 6h) |
| Days 2, 3, 4: once a day at 9:00 AM student-local | 1 | 1 | 1 | |
| After day 4, no acknowledgement | stops | stops | stops | told "sequence ended, no acknowledgement" |

There is no second call on day 1: GHL Voice AI allows **one call per phone number per day** (and 14 in 14 days; our
plan makes 4 in total). Telling the approver does **not** stop the sequence. Only an acknowledgement, or the approver closing it, does.
"Up to three days" = days 2, 3 and 4 after day 1 (Kes, 2026-10-02).

### The plan stops at the interview (2026-10-10)
The plan above is built from the approval time. When the interview's date (and time) is known (`escalation_schedule.interview_when`, zone from the interview, else the student's), it is shortened:
- An interview that has already happened plans nothing (the sequence is `interview_passed`); Approve also refuses it with a clear message.
- A follow-up that would land less than an hour before the interview, or after it, is dropped. Every attempt is also checked again when it comes due, and the sequence closes as `interview_passed` once the interview time arrives (no "never acknowledged" alert).
- Short notice (interview within 36 hours of approval, time of day known): two same-channel reminders are never closer than 2 hours, and a **final text and email go out 2 hours before the interview**. No final call (calls stay at most one a day and four in all).
- A date with no time of day counts as the end of that day: nothing after it, no timed reminder.
- The approver's "no response" alert comes at +6h, or an hour before the interview if that is sooner.
- No interview date known: the four-day plan above, unchanged. Simulation: `execution/simulate_notifications.py` (scenarios S11 to S13).

## Quiet hours (Ali)
- In the **student's own** time zone. Texts: quiet 9 PM to 8 AM (Ali). **Calls: quiet 8 PM to 8 AM**, because GHL Voice AI
  itself only places calls 8 AM to 8 PM in the contact's zone and silently reschedules the rest, so we match it rather
  than record a call as sent that GHL will place tomorrow. Email goes any time.
- Time zone: stored value, else derived from the phone area code (`phonenumbers` library), else
  `America/Chicago` only if both fail.
- An attempt that falls in quiet hours is **held and released at 8 AM** local (not dropped).
- Overlap rule (Kes chose "whichever is easier"): never send two calls, or two texts, to the same
  student within 3 hours. A held attempt that would collide with the next scheduled one is skipped.

## What counts as acknowledged (stops everything)
1. Pressing 1 on the call
2. Replying YES (also Y, yes, yep, ok, received) to the text; rule-based, no AI
3. Tapping "I got this" in the email
4. the approver marking it confirmed / closing it in the dashboard
5. AI judges the student's own reply shows they understood. **Shadow mode for 2 weeks**: it records
   its judgement and stops nothing; Ali wants the measured hit rate before it may stop anything.
   It reads only the student's replies, never our messages or Cora's. It picks from a fixed list
   (understood / needs help or cannot attend / confused / unsure); only "understood" can stop
   follow-ups, the others alert the approver. Student text is data, never instructions.
A STOP reply ends all contact. A voicemail does not count.

**Calls are read by rule first (2026-10-02, from the first live test call).** `ghl_conversations.call_outcome()` reads the transcript
in order: (1) a student line like "don't call me again" / "stop calling" / "remove me" = STOP (wins over everything); (2) the student's
first answer right after the agent's question "Can you confirm you got this information?" that starts with a plain yes and has no
"but / can't / not / no" = a confirmation, same as a YES text (explicit acknowledgement, works in shadow mode too). A yes BEFORE the
details were given ("would you like to hear the details?") never counts. Anything else goes to the normal reading (AI, shadow).
The agent prompt must keep the phrase "confirm you got" (`CONFIRM_QUESTION_MARKER`).

**Finding the student's GHL contact: email first (2026-10-03).** The interview notice identifies a student by email, so
`notify_channels.find_ghl_contact()` looks the contact up by the student's personal email, then assigned Gmail, then (fallback) phone, and
all identifiers must agree: two different contacts = refused, never guessed. A contact found ONLY by phone must have a first name that
agrees with the student's (prefix match, blank GHL name allowed). Calls and texts use the phone GHL holds on the contact, so a student
with no phone in our table can still be called if their GHL contact has one. When no contact is found, the contact has no phone (call/text)
or no email (email), or the identifiers disagree, the attempt FAILS with a detail starting `UNREACHABLE:` and **the approver is emailed once**
("Cannot reach <student>: their contact details need fixing", a student may have changed their email, update the record or GHL). A student
with nothing on file at all gets that alert on the first tick. Known limit: the quiet-hours time zone is still worked out from OUR phone
(Central fallback), not from the GHL contact's phone.

**The app remembers STOP itself (2026-10-02).** A STOP text or a spoken stop writes a row in `notification_opt_outs` (phone last 10
digits + channel: sms | call | email). `GhlChannel.send` checks it before every send, in addition to GHL Do-Not-Disturb and the
opt-out tags, so the request holds even if GHL is never updated. Per channel: a stopped call does not stop texts. Clearing an
opt-out is a manual database change (decide with the approver/Ali who may do it).

Test plan with the exact steps and pass criteria: `docs/test-plan-student-notifications.md`.

## Shared Twilio number
Texts use the number Cora already uses (972-992-1024), so they share one daily budget (Ali: all-carrier
ceiling 3,000 segments/day; T-Mobile 999). Worst case here is about 100 segments/day. Keep a daily
counter and a soft cap so Cora is never crowded out. Pressing 1 needs no special Twilio plan, but the
number must be voice-enabled.

## Database changes (approved by Kes 2026-10-02; needs an Alembic migration)
- New table of attempts (draft id, channel, scheduled time, sent time, status, Twilio SID, segments)
- Acknowledgement fields on notifications (status, channel, time, explicit vs AI-inferred)
- Time-zone column on students

## Before turning it on for real students (Ali's condition, now applied to switching on, not to building)
- [ ] Kes confirms with the approver what the approver does today (WhatsApp / own email) so nothing he relies on disappears
- [ ] the approver's address in the approver role (Settings page; `APPROVER_ALERT_EMAIL` fallback) (without it the approver's alerts are only written to the log)
- [x] SMS adapter built: GHL field write with our own daily budget (default 150 of the shared 999, set
      `NOTIFY_SMS_DAILY_SEGMENT_CAP`), content gate, quiet hours (risk 1, 4). Cora's own texts are still not
      counted: lower the cap by Cora's real usage.
- [x] Call adapter built (GHL field `interview_notification`); the Synthflow route (risks 2, 3) is not needed
- [ ] GHL credentials in `/repo/.env` (`GHL_API_KEY`, `GHL_LOCATION_ID`), the three `GHL_WRITE_*` switches
      reviewed by a human, and the "Still UNVERIFIED" list above answered
- [ ] Shadow rehearsal first: `NOTIFY_CHANNEL_*=ghl` with `GHL_WRITE_MODE=shadow` looks up the real contact and
      checks DND but writes nothing; read the `[GHL shadow]` log lines before going live
- [ ] Cora's current daily SMS/call usage on the shared number
- [ ] Student opt-in for texts and calls confirmed
- [x] Inbound replies: read by polling GHL Conversations (needs `GHL_CONVERSATIONS_API_KEY`); no forwarding workflow needed
- [x] `GHL_CONVERSATIONS_API_KEY`, `GHL_API_KEY` (with the call-log scope) and `GHL_LOCATION_ID` exist in the local `.env`; NOT yet on the server
- [ ] `GHL_VOICE_AGENT_ID` set to the new outbound agent once it exists
- [ ] Decide: alert the approver when a draft is waiting (proposed by Claude, not requested by Ali); alert Ali
      if a draft sits unapproved (proposed, Ali has not said yes). Neither is built.
- [ ] Host cron for `execution/notification_tick.py` every 5 minutes (not installed)
- [ ] Shadow mode ends 2026-10-16; `REPLY_AI_MODE=live` is also required before the AI may stop anything

## Settings (all off or safe by default)
Both the API and the tick script read `/repo/.env` (the API's `config.py` calls `load_dotenv()`, which walks up
to the repo root), so put the settings there once; restart the API after changing it. Additional settings:
`GHL_*` per the kit (`GHL_BASE_URL`, `GHL_API_KEY`, `GHL_LOCATION_ID`, `GHL_WRITE_MODE`,
`GHL_WRITE_SHADOW_LOG_ONLY`, `GHL_WRITE_NOTIFY_FIELDS`, `GHL_FIELD_NOTIFY_*`), `NOTIFY_SMS_DAILY_SEGMENT_CAP`
(default 150, hard ceiling 999) and `NOTIFY_BLOCK_TAGS` (opt-out tags; default includes "do not call").
| Setting | Default | Meaning |
|---|---|---|
| `NOTIFY_ESCALATION_ENABLED` | off | Approve starts the escalation instead of sending one email |
| `NOTIFY_CHANNEL_EMAIL` / `_SMS` / `_CALL` | `dry_run` | `dry_run` logs only; `ghl` writes the GHL field (shadow-gated); email can also be `smtp` |
| the approver role (Settings page; `APPROVER_ALERT_EMAIL` fallback) | unset | Where the approver's alerts go; unset = logged only |
| `NOTIFY_LEAD_SPACING_MINUTES` | `3` | Minimum minutes between contact with one student and contact with the NEXT student (a call, text and email together count as one contact; shadow-mode logged sends count too). `0` = off. Held attempts stay pending and go out on a later tick, oldest waiting student first. The tick runs every 5 minutes, so in practice students go out about 5 minutes apart. |
| `NOTIFY_ACK_BASE_URL` | `https://2-29-47-89.nip.io/api/notifications/ack` | Base of the email "I got this" link |
| `NOTIFY_INBOUND_SECRET` | unset | Secret for the inbound-reply endpoint; unset = endpoint closed |
| `REPLY_AI_MODE` / `REPLY_AI_SHADOW_UNTIL` | shadow / 2026-10-16 | Live needs both the setting and the date to have passed |

## Content audit (2026-10-12, Kes)

An automated audit scans the BODY of every outbound text and email (not calls, not the email subject) and flags any message containing a word or phrase from its list (data analytics, data analyst, data science, bootcamp, power bi, tableau, sql, excel, full stack, cybersecurity, business intelligence, employment/placement/hiring rate, job placement, job guarantee, ...). The first notices were flagged. Rules now enforced in code:
- The wording lives in `execution/notification_messages.py`; the audit's list and the text rules in `execution/content_audit.py` (tests: `tests/execution/test_content_audit.py`). Colaberry does not offer the position, the employer does: the messages never say Colaberry is hiring and **never name the job title** ("the position you applied for").
- Text: begins exactly `[Interview Notification]`, 320 characters or fewer, first name, employer, date, time and zone, and "Reply YES to confirm you got this." Email: first line exactly `[Interview Notification]`, same facts, a short preparation note, plain subject "Your interview on <date>", "Please confirm you received this message by replying YES to this email." **No link and no phone number in any message** (Kes, 2026-10-12): the student confirms by replying YES to the text or the email, or by saying yes on the call, and a video interview says to use the link in the employer's own invitation email. The audit gate refuses a link. The one-tap "I got this" link was removed from the email.
- An employer name that is itself on the flagged list ("Excel Staffing") is replaced by "the employer" in texts and emails (the call still names it).
- Send-time gate: `notify_channels.audit_problem` runs before any text or email is written or logged (also in shadow mode); a message that would be flagged is a FAILED attempt with the reason, never sent. An older template draft is replaced at send time by the audit-safe email; `execution/rewrite_pending_drafts.py` makes the approval card show the same text.
- The call wording is in `docs/voice-agent-outbound-interview-prompt.md` (calls are not scanned; no outcome claims). A STOP reply never gets a further reply from us.

## Spacing between students (2026-10-12, Kes)

To keep calls and texts from stacking on the shared phone line (Twilio concurrency limits), `escalation_engine.tick` lets only one student's batch go out per spacing window: when another student was contacted less than `NOTIFY_LEAD_SPACING_MINUTES` ago, a student's due attempts are held (left pending, nothing changed) and sent on a later tick. The student who has waited longest goes first. This spaces OUR sends only. It cannot see Cora's calls and texts, calls that last longer than the spacing, or inbound calls to the receptionist, all of which use the same account. The real concurrency limits of the Twilio account and of GHL Voice AI are not verified yet (see progress.md).

## Related
`directives/interview-processing.md`, `execution/send_notification.py`, `execution/alert.py`,
`directives/pipeline-health-check.md` (add checks for stuck/unacknowledged notices when built).


## Roles, not people (Ali, 2026-10-04)

Nobody is written into the code. Three ROLES are assigned on the dashboard's Settings page (table `role_assignments`; `execution/roles.py`):

| Role | Gets | Today (a setting, not code) |
|---|---|---|
| `approver` | approves notifications; follow-ups on a student (no response, a reply needing help, STOP, cannot be reached) | assigned in Settings |
| `callback_owner` | interview callbacks from students, within ONE business hour during working hours | assigned in Settings |
| `escalation_target` | one email per stale draft (unapproved after 2 business hours); also copied on emailed notices | assigned in Settings |

- **Agents first (2026-11-09, Kes):** a new card's approve/reject email goes to the student's AGENT (roster sheet Agent column; emails entered on Settings > Agents, stored as `role_assignments` rows with role `agent` and the agent name in `scope`) via `execution/agent_routing.py`. The approver gets the card straight away instead when a person must sort it out first: no student, student unverified, not matched by email on the roster, roster unreadable, not confirmed in GHL, classification confidence under 0.70, no agent on the sheet, or the agent has no email set. With no agent email set at all, every card goes to the approver exactly as before. The code that goes with an agent's link is emailed to the AGENT's mailbox.
- Stale-draft alert: `execution/stale_draft_alerts.py`, host cron every 15 minutes (`execution/crontab.stale`). A card first sent to an AGENT that is undecided after the backup time (default 2 business hours) goes to the APPROVER (the backup); a card the approver got first goes to the escalation role, never back to the approver (the approver is the one who has not acted); each
  draft once; the first run records existing drafts silently (no flood from a backlog); nothing is marked while nobody holds the role.
- Business hours (`execution/business_hours.py`): default Mon-Fri 09:00-17:00 America/Chicago, settable by environment; no holidays modelled.
- Pilot gate: until lifted on the Settings page only 3 approved notices may start a sequence (`notify_pilot_limit`, 0 = no limit); enforced when escalation is enabled.
- When recruiters take over, each person's role assignment changes; the code does not. `scope` on a role assignment is reserved for per-recruiter routing (the roster already carries an assigned assistant per student).
- Not built yet: the callback SLA timer (needs inbound call reading from GHL), a second escalation holder (Ali: escalation is only the one person; if they are away nobody is told).


## Callbacks (student calls back about an interview), 2026-10-04

- The AI receptionist only TAKES THE MESSAGE and says a team member will call back within one business hour during working hours. **The AI never calls back.**
- `execution/callbacks.py` (host cron every 5 minutes, `execution/crontab.callbacks`; needs `GHL_RECEPTIONIST_AGENT_ID`, `GHL_API_KEY`, `GHL_LOCATION_ID` in the server `.env`) reads the
  receptionist's newest calls (read-only), keeps the ones about an interview (`is_interview_callback`: the caller mentions an interview together with returning/missing a call, text or email, OR the
  receptionist used the prescribed "Interview Support will call you back" wording), finds the student (GHL contact email, else either phone number; never guessed when two match) and stores a
  `callback_requests` row (one per call).
- The `callback_owner` role is emailed; the approval screen shows "Callbacks waiting" and flags the student's cards; Interviews shows "Callback needed". The owner clicks **Called back** to clear it, or **Cancel** when the notice is wrong (kept for the record as `cancelled`). A caller who matches nobody on the roster is not an interview callback: it is stored as `ignored` and is never shown or alerted.
- Open after ONE BUSINESS HOUR (9-17 Mon-Fri Central by default): the `escalation_target` role is emailed once. Calls from before the feature was switched on are a silent baseline.
- Receptionist prompt wording (the person is not named): take the caller's name and best number, say a team member will call back within one business hour during working hours, end the call, never offer to
  call back itself. Optional GHL action "Update contact field" can write the caller's best number and availability to a contact field for Rob's convenience; our app does NOT depend on it (the call time comes from the call log).
- **What the emails contain (2026-10-09).** Both the callback owner's alert and the escalation role's overdue email carry the same context (`callbacks.context_lines`): the caller's own words (why they called), how to reach the student, their last three interviews (company, role, type, time, when the email arrived), what the app has already sent them (channel, time, status), their replies and any confirmation, and the number of earlier callbacks from that number. Read-only; capped (8 notices, shortened replies). An unmatched number says so and asks the caller to identify themselves. The overdue email lists each student in its own block so the person can call with the full picture.
- Unproven until a real callback is made: how a callback transcript reads in the call log and how reliably it is recognised (153 earlier receptionist calls had none).

## Follow-ups on an interview the student was already told about

A reminder, reply or second confirmation of the SAME interview must not become a new student notice. `execution/interview_followup.py`
(no LLM) compares each new interview event with the student's earlier events that have a pending, approved or sent notice: same moment
(date and time compared in UTC; US zones read by date, so "PST" in October means Pacific time that day) and a compatible company (an email that
names no company can match; two different named companies never do). A match is linked in `interview_follow_ups` and gets **no draft**, so
nothing reaches the student and no pilot-limit slot is used. The review list hides it (shown, labelled "Follow-up on a scheduled interview",
under Show finished). Pending cards about one interview group under the oldest.
- Never a follow-up: a cancellation, an interview at a different time (a real reschedule), no date or time, a notice the approver rejected.
- The model's "Rescheduled" label is not trusted; only a different time counts as a change.
- Every doubt shows a card. Clean today's queue with `python execution/interview_followup.py` (lists) then `--apply`.

### Suggested action on a card
Every open notice may carry `suggestion` (`interview_followup.suggested_action`, pure rules, never approves or rejects): **Reject** when it repeats a notice a
person already rejected (names that notice) or has no date, time, company or position; **Check first** for a cancellation (lists the interviews already
announced to the student, or says none) or a different time without the Rescheduled label; **Approve** for a Rescheduled notice at a different time of the
same named company. No line = no opinion; a missing line never implies approval.

