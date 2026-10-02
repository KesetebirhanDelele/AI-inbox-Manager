# Directive: Student Notification, Acknowledgement and Escalation

**Status (2026-10-02): the core is BUILT and DEPLOYED but SWITCHED OFF, and every channel is a dry run.**
Approved by Ali (email 2026-10-02) and Kes. Kes told Claude to "build it for now", ahead of Ali's condition
that Kes confirm with Rob first, so nothing real is sent: the escalation is off unless
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
| Approve starts it (when enabled); email "I got this" link; Rob's status/close; secret-protected reply endpoint | `services/dashboard/api/routers/notifications.py` |
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
1. **The call value carries the interview facts.** `interview_notification` holds what the voice agent tells the
   candidate: interview type, company, position, date, time and time zone, format, contact at the company, number of
   interviewers (only facts we have; "date and time not confirmed yet" when unknown), then the ask to say yes. Built in
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

**Calls and the AI.** GHL's transcript lists sentences per `mediaChannel` but does not say which channel is the
student. Set `GHL_CALL_STUDENT_MEDIA_CHANNEL` once confirmed from a real call. Until then a finished call is never
analysed and never stops a sequence; Rob gets one alert ("a call finished but could not be read"). When set, only the
student's sentences reach the AI. Calls that did not connect (voicemail, no answer, busy, failed) are recorded and not
read; a transcript GHL has not produced yet is retried for 15 minutes.

**Still UNVERIFIED (confirm in GHL before switching on; do not guess):**
1. Which `mediaChannel` in GHL's call transcript is the student, and whether Voice AI calls appear as `TYPE_CALL`
   messages with a status such as completed / voicemail / no-answer (the status words are my guess).
2. Whether the voice workflow reads a long single-line value correctly (the field type matters; labelled facts are
   separated by "; ").
3. Voice AI honouring Call DND and calling hours (we apply quiet hours and the opt-out check ourselves anyway).
4. The exact `phone` field format GHL returns on a contact (we compare the last 10 digits).

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
following up until they do. A person (Rob) approves the first send; nothing is auto-sent before that.

## Inputs
- An approved `NotificationDraft` (Rob clicked Approve) for a student with a phone number and email
- Student replies: SMS replies, email replies, keypad presses, email-button clicks

## Outputs
- Attempt log (every call/text/email, with status and Twilio SID)
- Acknowledgement record (which channel, when, explicit or AI-inferred)
- Alerts to Rob (no response after day 1; sequence ended)

## Schedule (T0 = Rob approves)
| When | Call | Text | Email | Rob |
|---|---|---|---|---|
| T0 | yes | yes | yes | |
| T0 + 2h | yes | | yes | |
| T0 + 4h | | yes | yes | |
| End of day 1, no acknowledgement | | | | **told** "student has not responded" (about T0 + 6h) |
| Days 2, 3, 4: once a day at 9:00 AM student-local | 1 | 1 | 1 | |
| After day 4, no acknowledgement | stops | stops | stops | told "sequence ended, no acknowledgement" |

Telling Rob does **not** stop the sequence. Only an acknowledgement, or Rob closing it, does.
"Up to three days" = days 2, 3 and 4 after day 1 (Kes, 2026-10-02).

## Quiet hours (Ali)
- 9 PM to 8 AM in the **student's own** time zone. Binds calls and texts. Email goes any time.
- Time zone: stored value, else derived from the phone area code (`phonenumbers` library), else
  `America/Chicago` only if both fail.
- An attempt that falls in quiet hours is **held and released at 8 AM** local (not dropped).
- Overlap rule (Kes chose "whichever is easier"): never send two calls, or two texts, to the same
  student within 3 hours. A held attempt that would collide with the next scheduled one is skipped.

## What counts as acknowledged (stops everything)
1. Pressing 1 on the call
2. Replying YES (also Y, yes, yep, ok, received) to the text; rule-based, no AI
3. Tapping "I got this" in the email
4. Rob marking it confirmed / closing it in the dashboard
5. AI judges the student's own reply shows they understood. **Shadow mode for 2 weeks**: it records
   its judgement and stops nothing; Ali wants the measured hit rate before it may stop anything.
   It reads only the student's replies, never our messages or Cora's. It picks from a fixed list
   (understood / needs help or cannot attend / confused / unsure); only "understood" can stop
   follow-ups, the others alert Rob. Student text is data, never instructions.
A STOP reply ends all contact. A voicemail does not count.

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
- [ ] Kes confirms with Rob what Rob does today (WhatsApp / own email) so nothing he relies on disappears
- [ ] Rob's address in `ROB_ALERT_EMAIL` (without it Rob's alerts are only written to the log)
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
- [ ] `GHL_CONVERSATIONS_API_KEY` set, and `GHL_CALL_STUDENT_MEDIA_CHANNEL` confirmed from a real call
- [ ] Decide: alert Rob when a draft is waiting (proposed by Claude, not requested by Ali); alert Ali
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
| `ROB_ALERT_EMAIL` | unset | Where Rob's alerts go; unset = logged only |
| `NOTIFY_ACK_BASE_URL` | `https://2-29-47-89.nip.io/api/notifications/ack` | Base of the email "I got this" link |
| `NOTIFY_INBOUND_SECRET` | unset | Secret for the inbound-reply endpoint; unset = endpoint closed |
| `REPLY_AI_MODE` / `REPLY_AI_SHADOW_UNTIL` | shadow / 2026-10-16 | Live needs both the setting and the date to have passed |

## Related
`directives/interview-processing.md`, `execution/send_notification.py`, `execution/alert.py`,
`directives/pipeline-health-check.md` (add checks for stuck/unacknowledged notices when built).
