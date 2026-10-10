"""
Daily pipeline health check.

Silent failures are what hid the missing sub-classifier, the empty review queue
and the permanent deletions for days. This script checks the invariants that
would have caught each of them and emails ALERT_EMAIL_TO only when one is broken.
It is read-only: it queries the database and reads the cron log, nothing else.

Checks (window: last 24 hours):
  CRITICAL  permanent deletion       any "permanently deleted N" line in the cron log
  CRITICAL  review-queue gap         classifications that should be queued but have no approval row
  CRITICAL  run health               last run too old, or a run ended in partial_failure
  CRITICAL  notification sends       failed drafts, or drafts stuck in 'approved'
  CRITICAL  escalation attempts      call/text/email attempts that failed (only once escalation is switched on)
  WARNING   sub-classifier fallback  share of events labelled by the fallback, not the sub-classifier
  WARNING   student matching         share of events with no student attached

Usage (inside the cron container, as appuser):
    python execution/health_check.py            # print report; email if unhealthy, plus a weekly Monday all-clear
    python execution/health_check.py --always   # also email when healthy
"""

import argparse
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
for p in (_ROOT / "execution", _ROOT, _ROOT / "services" / "dashboard" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

logger = logging.getLogger("health_check")

CRON_LOG = _ROOT / "logs" / "cron.log"

# The pipeline stopped deleting mail at the 2026-10-01 13:50 UTC deploy. Log lines
# from before that are history, not a regression.
NO_DELETE_SINCE = datetime(2026, 10, 1, 14, 0, 0)

# The approvals queue went live at the 2026-10-01 13:55 UTC deploy; classifications
# made before it were never going to be queued.
QUEUE_ACTIVE_SINCE = datetime(2026, 10, 1, 13, 55, 0)

# A healthy check stays silent, so a dead check would look the same as a healthy one.
# One "all clear" email a week (Monday) proves the check itself is still running.
WEEKLY_ALL_CLEAR_WEEKDAY = 0     # Monday

MAX_RUN_AGE_HOURS = 3.0         # runs are every 2 hours
MIN_EVENTS_FOR_RATES = 3         # a rate over 1-2 events is noise
MAX_FALLBACK_RATE = 0.30
# Events of the retired interview categories (Confirmation, Schedule, Final) skip the sub-classifier BY DESIGN and carry these fallback labels, so they
# are not "the sub-classifier failing". They disappear once CATEGORY_REMAP_MODE=live re-files those categories by interview type.
RETIRED_CATEGORY_LABELS = {"confirmed", "interview_schedule", "final_round"}
MAX_NO_STUDENT_RATE = 0.50
STUCK_APPROVED_MINUTES = 60

_DELETE_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .*permanently deleted (\d+) ")


@dataclass
class Finding:
    severity: str   # "CRITICAL" or "WARNING"
    check: str
    message: str


def count_permanent_deletes(log_text: str, since: datetime) -> int:
    """Total emails the cron log says were permanently deleted at or after `since`."""
    total = 0
    for line in log_text.splitlines():
        m = _DELETE_LINE.match(line)
        if not m:
            continue
        stamp = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        if stamp >= since:
            total += int(m.group(2))
    return total


def evaluate(m: Dict[str, Any]) -> List[Finding]:
    """Turn collected metrics into findings. Pure logic, no I/O."""
    out: List[Finding] = []

    if m["permanent_deletes"] > 0:
        out.append(Finding("CRITICAL", "permanent deletion",
                           f"{m['permanent_deletes']} email(s) were permanently deleted in the last 24h. "
                           f"The pipeline is supposed to quarantine, never delete."))

    if m["approvals_missing"] > 0:
        out.append(Finding("CRITICAL", "review-queue gap",
                           f"{m['approvals_missing']} classification(s) under the review threshold have no "
                           f"approvals row, so no human will see them."))

    age = m["last_run_age_hours"]
    if age is None:
        out.append(Finding("CRITICAL", "run health", "No processing run has ever been recorded."))
    elif age > MAX_RUN_AGE_HOURS:
        out.append(Finding("CRITICAL", "run health",
                           f"The last run was {age:.1f}h ago (runs are every 2h). The scheduler may be down."))
    if m["runs_partial_failure"] > 0:
        out.append(Finding("CRITICAL", "run health",
                           f"{m['runs_partial_failure']} run(s) in the last 24h ended in partial_failure."))

    if m["drafts_failed"] > 0:
        out.append(Finding("CRITICAL", "notification sends",
                           f"{m['drafts_failed']} notification draft(s) failed to send."))
    if m["drafts_stuck"] > 0 and not m.get("shadow"):
        # In shadow mode nothing is delivered on purpose, so an approved draft that never reaches "sent" is expected (see the numbers line).
        out.append(Finding("CRITICAL", "notification sends",
                           f"{m['drafts_stuck']} draft(s) approved over {STUCK_APPROVED_MINUTES} minutes ago but never sent."))

    if m.get("attempts_failed", 0) > 0:
        out.append(Finding("CRITICAL", "escalation attempts",
                           f"{m['attempts_failed']} student notification attempt(s) failed in the last 24h "
                           f"(call, text or email). A student may not know about their interview."))

    n = m["events"]
    if n >= MIN_EVENTS_FOR_RATES:
        fb = m["events_fallback"] / n
        if fb > MAX_FALLBACK_RATE:
            out.append(Finding("WARNING", "sub-classifier fallback",
                               f"{m['events_fallback']} of {n} new interview events ({fb:.0%}) used the fallback "
                               f"label, so the sub-classifier may be failing."))
        ns = m["events_no_student"] / n
        if ns > MAX_NO_STUDENT_RATE:
            out.append(Finding("WARNING", "student matching",
                               f"{m['events_no_student']} of {n} new interview events ({ns:.0%}) have no student "
                               f"attached, so header parsing may be failing."))
    return out


def _shadow_mode() -> bool:
    """True while the notification flow is on but every send is only logged (the three GHL write switches are not all live)."""
    import os
    if os.getenv("NOTIFY_ESCALATION_ENABLED", "").strip().lower() not in ("1", "true", "yes"):
        return False
    try:
        import ghl_client
        return not ghl_client.GhlConfig.from_env().is_live
    except Exception:
        return True


def collect_metrics(db, log_text: str, now: datetime) -> Dict[str, Any]:
    """Read the numbers `evaluate` needs from the database and the cron log."""
    from models import (Approval, Classification, InterviewEvent, NotificationAttempt,
                        NotificationDraft, ProcessRun)
    from process_inbox_auto import needs_human_review

    since = now - timedelta(hours=24)

    last = db.query(ProcessRun).order_by(ProcessRun.run_timestamp.desc()).first()
    last_age = None if last is None else (now - last.run_timestamp).total_seconds() / 3600
    partial = db.query(ProcessRun).filter(
        ProcessRun.run_timestamp >= since, ProcessRun.status == "partial_failure").count()

    queued_email_ids = {row[0] for row in db.query(Approval.email_id).all()}
    recent = db.query(Classification).filter(
        Classification.classification_timestamp >= max(since, QUEUE_ACTIVE_SINCE)).all()
    missing = sum(
        1 for c in recent
        if needs_human_review(c.category or "", float(c.confidence or 0.0))
        and c.email_id not in queued_email_ids
    )

    events = db.query(InterviewEvent).filter(InterviewEvent.created_at >= since).all()
    fallback_all = [e for e in events if (e.raw_extraction or {}).get("sub_type_source") == "category_fallback"]
    fallback = sum(1 for e in fallback_all if (e.sub_type or "") not in RETIRED_CATEGORY_LABELS)
    retired_fallback = len(fallback_all) - fallback
    no_student = sum(1 for e in events if e.student_id is None)

    failed = db.query(NotificationDraft).filter(
        NotificationDraft.email_status == "failed", NotificationDraft.created_at >= since).count()
    stuck_cutoff = now - timedelta(minutes=STUCK_APPROVED_MINUTES)
    stuck = db.query(NotificationDraft).filter(
        NotificationDraft.email_status == "approved",
        NotificationDraft.reviewed_at != None,  # noqa: E711
        NotificationDraft.reviewed_at < stuck_cutoff).count()

    attempts_failed = db.query(NotificationAttempt).filter(
        NotificationAttempt.status == "failed", NotificationAttempt.created_at >= since).count()

    return {
        "shadow": _shadow_mode(),
        "events_retired_fallback": retired_fallback,
        "attempts_failed": attempts_failed,
        "permanent_deletes": count_permanent_deletes(log_text, max(since, NO_DELETE_SINCE)),
        "approvals_missing": missing,
        "last_run_age_hours": last_age,
        "runs_partial_failure": partial,
        "drafts_failed": failed,
        "drafts_stuck": stuck,
        "events": len(events),
        "events_fallback": fallback,
        "events_no_student": no_student,
    }


def format_report(findings: List[Finding], m: Dict[str, Any], now: datetime) -> str:
    """Plain-text report: verdict first, then the numbers behind it."""
    if findings:
        head = f"UNHEALTHY: {len(findings)} problem(s) found"
        body = "\n".join(f"  [{f.severity}] {f.check}: {f.message}" for f in findings)
    else:
        head, body = "HEALTHY: all checks passed", "  Nothing needs attention."
    age = m["last_run_age_hours"]
    numbers = (
        f"  last run: {'never' if age is None else f'{age:.1f}h ago'}; "
        f"new interview events (24h): {m['events']} "
        f"(fallback {m['events_fallback']}, no student {m['events_no_student']}); "
        f"deletes: {m['permanent_deletes']}; queue gaps: {m['approvals_missing']}; "
        f"failed drafts: {m['drafts_failed']}"
    )
    if m.get("events_retired_fallback"):
        numbers += (f"\n  {m['events_retired_fallback']} new event(s) from the retired interview categories used the generic label "
                    f"(not counted as a sub-classifier failure)")
    if m.get("shadow"):
        numbers += (f"\n  SHADOW MODE: nothing is delivered to students by design; {m.get('drafts_stuck', 0)} approved draft(s) are not 'sent' "
                    f"for that reason (not counted as a problem)")
    return f"{head}  ({now:%Y-%m-%d %H:%M} UTC)\n\n{body}\n\nNumbers:\n{numbers}\n"


def should_email(findings: List[Finding], now: datetime, always: bool = False) -> bool:
    """Email on any problem, on request, and once a week even when healthy."""
    return bool(findings) or always or now.weekday() == WEEKLY_ALL_CLEAR_WEEKDAY


def run(always_email: bool = False, now: Optional[datetime] = None) -> List[Finding]:
    from process_inbox_auto import get_db_session

    now = now or datetime.utcnow()
    db = get_db_session()
    if db is None:
        raise SystemExit("No database session")
    log_text = CRON_LOG.read_text(encoding="utf-8", errors="ignore") if CRON_LOG.exists() else ""
    metrics = collect_metrics(db, log_text, now)
    findings = evaluate(metrics)
    report = format_report(findings, metrics, now)
    print(report)

    if should_email(findings, now, always_email):
        from alert import send_failure_alert
        subject = "Health check: problems found" if findings else "Health check: all clear"
        sent = send_failure_alert(subject, report)
        logger.info("Alert email sent" if sent else "Alert email not sent (see logs/alerts.log)")
    return findings


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily InboxGenius pipeline health check")
    parser.add_argument("--always", action="store_true", help="email the report even when healthy")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run(always_email=args.always)


if __name__ == "__main__":
    main()
