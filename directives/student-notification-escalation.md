# Directive: Student Notification, Acknowledgement and Escalation

**Status: approved design, NOT built.** Approved by Ali (email 2026-10-02) and Kes. Do not start
building until the "Before building" checklist at the bottom is done (Ali's condition).

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

## Before building (Ali's condition: do not build until done)
- [ ] Kes confirms with Rob what Rob does today (WhatsApp / own email) so nothing he relies on disappears
- [ ] Twilio account details, and a check that the number supports voice
- [ ] Cora's current daily SMS/call usage on the shared number
- [ ] Student opt-in for texts and calls confirmed
- [ ] Decide: alert Rob when a draft is waiting (proposed by Claude, not requested by Ali); alert Ali
      if a draft sits unapproved (proposed, Ali has not said yes)

## Related
`directives/interview-processing.md`, `execution/send_notification.py`, `execution/alert.py`,
`directives/pipeline-health-check.md` (add checks for stuck/unacknowledged notices when built).
