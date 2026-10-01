# Directive: Daily Pipeline Health Check

## Goal
Catch silent failures in the email pipeline within a day, without anyone having to
look at a dashboard. Added 2026-10-01 after the sub-classifier, the review queue and
the spam deletion all failed or misbehaved for days unnoticed.

## Inputs
- Production database (read-only) and `logs/cron.log`
- `ALERT_EMAIL_TO` in `.env` (who gets the email)

## Outputs
- A printed report (HEALTHY or UNHEALTHY with reasons)
- An email through `alert.py` only when something is wrong (`--always` also emails when healthy)

## Checks (last 24 hours)
| Severity | Check | Fires when |
|---|---|---|
| CRITICAL | permanent deletion | the cron log shows any "permanently deleted N" after 2026-10-01 14:00 UTC |
| CRITICAL | review-queue gap | a classification under 0.70 (not "Other" at 0.0) has no `approvals` row |
| CRITICAL | run health | last run older than 3h, or any run ended `partial_failure` |
| CRITICAL | notification sends | a draft is `failed`, or `approved` for over 60 minutes without sending |
| WARNING | sub-classifier fallback | over 30% of new events used the category fallback (needs 3+ events) |
| WARNING | student matching | over 50% of new events have no student (needs 3+ events) |

## Steps
1. Run `python execution/health_check.py` in the cron container as `appuser`.
2. Production runs it daily at 07:30 UTC from a host cron file
   (`/etc/cron.d/inboxgenius-health`, see RUNBOOK §4c).
3. If it reports a problem, follow the named check, then fix the cause (self-annealing
   loop in CLAUDE.md), add a test, and note it in `progress.md`.

## Edge cases
- Rates are ignored below 3 events, so a quiet day does not raise a false alarm.
- The deletion check ignores log lines before the fix date; move `NO_DELETE_SINCE`
  only if the pipeline is deliberately changed to delete again.
- The script never writes to the database or Gmail and never sends to students.

## Related
- `execution/health_check.py`, `tests/execution/test_health_check.py`
- `execution/alert.py` (email + `logs/alerts.log` fallback)
