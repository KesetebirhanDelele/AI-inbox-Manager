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
| Channels: `dry_run`, `smtp` (email); GHL/Synthflow NOT built | `execution/notify_channels.py` |
| Reply reading: rules (YES/STOP) + AI in shadow mode | `execution/reply_analysis.py` |
| Scheduler pass (does nothing unless enabled) | `execution/notification_tick.py` |
| New tables only (existing tables untouched) | `notification_sequences`, `notification_attempts`, `reply_analyses`; migration `003` |
| Approve starts it (when enabled); email "I got this" link; Rob's status/close; secret-protected reply endpoint | `services/dashboard/api/routers/notifications.py` |
| Tests | `tests/execution/test_escalation_*.py`, `test_reply_analysis.py`, `services/dashboard/tests/test_notification_escalation.py` |

## How Cora delivers each channel (researched 2026-10-02 in `cora-recap-engine`)
Kes asked how GHL triggers Cora's outgoing messages so we can follow the same pattern.
| Channel | How Cora does it | Source |
|---|---|---|
| Email | Write GHL custom fields: `Support Issue Ticket #2` = subject, `Message` = body. The GHL workflow **"AI Agent - Send Email"** fires when Ticket #2 changes (5 s wait). | `app/core/followup_routing.py` |
| SMS | Write GHL custom field `Support issue Ticket #4` = the text. The GHL workflow **"AI Agent - Send SMS"** fires when Ticket #4 changes. Cora first passes its own SMS gate (no links, 3+ words, 8 AM to 9 PM lead-local, daily budget capped at 999 segments, ledger table `sms_send_ledger`). | `followup_routing.py`, spec/34 |
| **Phone call** | **There is no Support Issue Ticket for calls.** Cora POSTs to a **Synthflow "Make Call" workflow webhook** (`SYNTHFLOW_LAUNCH_WORKFLOW_URL_New`, Bearer `SYNTHFLOW_API_KEY`, body `phone`, `name`, `campaign_name`, `prompt`, `metadata`). GHL's only role is that its New Lead / Cold Lead workflows call Cora's `POST /v1/webhooks/leads/{campaign}` (secret header `X-Cora-Webhook-Secret`), which then launches the Synthflow call. | `app/adapters/synthflow.py`, `call_intake.py`, `settings.py` |
| Tickets #1 and #3 | #1 = call summary, #3 = task description. Neither sends anything. | `crm_jobs.py` |

Not verified against the GHL or Synthflow dashboards (only Cora's code and docs were read). Someone with
GHL access should open Automation > Workflows and confirm there is no workflow that starts a call from a field.

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
- [ ] SMS adapter: write the GHL field (or Twilio) with our own budget counter and quiet-hours/content checks (risk 1, 4)
- [ ] Call adapter: a dedicated Synthflow agent and workflow, completion webhook to our app (risk 2, 3); confirm
      how a spoken "yes" comes back
- [ ] Cora's current daily SMS/call usage on the shared number
- [ ] Student opt-in for texts and calls confirmed
- [ ] Inbound replies: a GHL (or provider) workflow that forwards student replies to
      `POST /api/notifications/inbound/reply` with `X-Notify-Secret` (`NOTIFY_INBOUND_SECRET`)
- [ ] Decide: alert Rob when a draft is waiting (proposed by Claude, not requested by Ali); alert Ali
      if a draft sits unapproved (proposed, Ali has not said yes). Neither is built.
- [ ] Host cron for `execution/notification_tick.py` every 5 minutes (not installed)
- [ ] Shadow mode ends 2026-10-16; `REPLY_AI_MODE=live` is also required before the AI may stop anything

## Settings (all off or safe by default)
The API container only gets the variables listed under `api: environment:` in
`services/dashboard/docker-compose.prod.yml`, and the tick script reads `/repo/.env`. When switching it on,
add the `NOTIFY_*`, `ROB_ALERT_EMAIL` and `REPLY_AI_*` settings to BOTH places (and `OPENAI_API_KEY` to the API).
| Setting | Default | Meaning |
|---|---|---|
| `NOTIFY_ESCALATION_ENABLED` | off | Approve starts the escalation instead of sending one email |
| `NOTIFY_CHANNEL_EMAIL` / `_SMS` / `_CALL` | `dry_run` | `dry_run` logs only; email can be `smtp`; SMS/call adapters not built |
| `ROB_ALERT_EMAIL` | unset | Where Rob's alerts go; unset = logged only |
| `NOTIFY_ACK_BASE_URL` | `https://2-29-47-89.nip.io/api/notifications/ack` | Base of the email "I got this" link |
| `NOTIFY_INBOUND_SECRET` | unset | Secret for the inbound-reply endpoint; unset = endpoint closed |
| `REPLY_AI_MODE` / `REPLY_AI_SHADOW_UNTIL` | shadow / 2026-10-16 | Live needs both the setting and the date to have passed |

## Related
`directives/interview-processing.md`, `execution/send_notification.py`, `execution/alert.py`,
`directives/pipeline-health-check.md` (add checks for stuck/unacknowledged notices when built).
