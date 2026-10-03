# Test plan: student interview notifications (call + text + email)

Purpose: prove each piece works with Kes's OWN contact before any real student is touched. Escalation stays OFF until every
gate in section 7 is ticked. Run in order; do not skip a stage. Tool for stages 1-3: `execution/ghl_test_call.py` (dry run by
default; `--send` writes exactly one channel's field(s) on one exactly-matched contact; `.env` is never changed).

Legend: **Who** = Kes does it by hand / Claude runs it. **Evidence** = what to paste into `progress.md`.

## 0. Before anything (once)

| # | Check | How | Pass |
|---|---|---|---|
| 0.1 | Unit tests green | `python -m pytest tests -q --no-cov` and `python -m pytest services/dashboard/tests -q --no-cov` | 0 failures |
| 0.2 | Test contact is clean | Kes's GHL contact: phone set, no DND, no `do not call` tag | `ghl_test_call.py --email <kes>` dry run says "DND/opt-out check passed" |
| 0.3 | Time window | Calls only 8 AM-8 PM in the contact's zone; one call per number per day | Plan call tests for different days or accept one per day |

## 1. Voice call (outbound agent)

Command: `python execution/ghl_test_call.py --email <kes> --send` then `--readback`. One call per number per day.

| # | Scenario | What you do on the call | Expected | Evidence |
|---|---|---|---|---|
| 1.1 | Greeting fix (re-test) | Answer "yes, speaking" | Agent asks "Am I speaking with Kes?" first, then gives the details with NO "would you like to hear the details" question | Transcript |
| 1.2 | Facts correct, reference silent | Listen | Company, position, date, time zone, format right; "Reference" / TEST id never spoken | Transcript |
| 1.3 | Confirmation read by the app | Say "yes" when asked "Can you confirm you got this information?" | `--readback` shows `app reads it as: confirmed` | Readback line |
| 1.4 | Wrong person | Say "no, this is someone else" | Agent apologises, shares NO details, ends call | Transcript has no company/date |
| 1.5 | Voicemail | Let it go to voicemail (or decline) | Short message with NO interview details; note how the call appears in the log (duration, transcript) | Readback + notes |
| 1.6 | STOP request | Say "please don't call me again" | Agent apologises, ends; `--readback` shows `app reads it as: stop`; (GHL action) contact gets tag `do not call` | Readback + GHL contact tag |
| 1.7 | Question it cannot answer | Ask "can you reschedule it?" | "A team member will reach out"; no promise to change anything | Transcript |
| 1.8 | Confirm-but-problem | Say "yes but I can't make it" | NOT read as confirmed (`no rule match`); agent says it will pass it to the team | Readback line |
| 1.9 | Callback | Call the number back | Inbound receptionist (with the INTERVIEW CALLBACKS section) says a team member will call back | Transcript |

## 2. Text (SMS)

Command: `python execution/ghl_test_call.py --email <kes> --channel sms --send`.

| # | Scenario | Expected | Evidence |
|---|---|---|---|
| 2.1 | Write the text field | Text arrives on Kes's phone within a minute; no link in it; GHL conversation shows it | Screenshot, `--readback` |
| 2.2 | Reply "YES" | `--readback` lists the inbound YES; (server rehearsal 5.x proves the app acknowledges) | Readback |
| 2.3 | Reply "STOP" | GHL sets Do-Not-Disturb for SMS automatically; re-running 2.1 dry run now says STOP (DND). Remove DND after the test. | Dry-run output |
| 2.4 | Content gate | A text with a link or under 3 words is refused (covered by unit tests; no live step) | Unit tests |

## 3. Email

Command: `python execution/ghl_test_call.py --email <kes> --channel email --send`.

| # | Scenario | Expected | Evidence |
|---|---|---|---|
| 3.1 | Write subject + body fields | Email arrives from the GHL workflow; subject starts "Test: interview notification" | Inbox screenshot |
| 3.2 | Reply from Kes's inbox | `--readback` lists the reply in the last 24 hours | Readback |
| 3.3 | Unsubscribed / DND email | Dry run refuses | Dry-run output |

## 4. Reading it back (app logic, no GHL writes)

Already covered by 724 unit tests; the live part is that `--readback` prints each call's `app reads it as` line and the recent messages
for the real contact. Pass: for stages 1.3, 1.6, 1.8 the line matches the table above.

## 5. Server rehearsal (shadow: reads real GHL, writes nothing)

Preconditions: GHL credentials added to the server `.env` (Kes does this; never paste them in chat); `NOTIFY_CHANNEL_EMAIL/SMS/CALL=ghl`,
`GHL_WRITE_MODE=shadow`, `NOTIFY_ESCALATION_ENABLED=true`. Use a TEST student whose phone is Kes's.

| # | Step | Expected |
|---|---|---|
| 5.1 | Create a test interview event + draft for the test student; Rob (or Kes) clicks Approve | A sequence with 15 planned attempts appears; the first three attempts show `dry_run` |
| 5.2 | Run `python execution/notification_tick.py` by hand inside the api container | Log lines `[GHL shadow] would write fields [...]`; NO field changed in GHL; no message or call reaches Kes |
| 5.3 | Quiet hours | Rehearse at a time outside 8 AM-8 PM student-local: calls/texts are held, email still goes (dry run) |
| 5.4 | Poller | Real replies/calls on the test contact are read; a "yes" call (stage 1.3 call) acknowledges the sequence; STOP closes it and writes a `notification_opt_outs` row |
| 5.5 | Health check | `docker exec -e ALERT_EMAIL_TO= ... health_check.py` shows no failed/stuck sends |

## 6. Live pilot (Kes as the student, real switches ON for one approved notice)

Only after sections 1-5 pass and Ali approves. Switch on `GHL_WRITE_MODE=live`, `GHL_WRITE_SHADOW_LOG_ONLY=false`,
`GHL_WRITE_NOTIFY_FIELDS=true`, keep `NOTIFY_ESCALATION_ENABLED=true`, and install the 5-minute cron.

| # | Step | Expected |
|---|---|---|
| 6.1 | Approve the test notice | Call + text + email reach Kes within minutes (daytime) |
| 6.2 | Do nothing | The 4-hour reminder (text + email) arrives; Rob gets the "no response" alert about 6 hours in |
| 6.3 | Reply YES | Follow-ups stop; sequence shows acknowledged by text |
| 6.4 | Repeat with a call "yes", an email "I got this" link, and Rob's Close | Each stops the sequence |
| 6.5 | Turn the switches back OFF until Ali says go for real students | `.deployed_commit` == `master`, server env as agreed |

## 7. Go-live gate (all must be ticked)

- [ ] 1.1-1.9, 2.1-2.3, 3.1-3.3 passed and logged in `progress.md`
- [ ] `do not call` tag action works in GHL (1.6)
- [ ] Server rehearsal 5.x passed
- [ ] Rob confirmed what he does today and gave `ROB_ALERT_EMAIL`
- [ ] Students' opt-in to texts/calls confirmed
- [ ] Ali approves (shared Cora text budget: `NOTIFY_SMS_DAILY_SEGMENT_CAP` set)
- [ ] AI reading still in shadow until 2026-10-16
