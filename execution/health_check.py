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
  WARNING   sub-classifier fallback  share of events labelled by the fallback, not the sub-classifier
  WARNING   student matching         share of events with no student attached

Usage (inside the cron container, as appuser):
    python execution/health_check.py            # print report, email only if unhealthy
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

MAX_RUN_AGE_HOURS = 3.0          # runs are every 2 hours
MIN_EVENTS_FOR_RATES = 3         # a rate over 1-2 events is noise
MAX_FALLBACK_RATE = 0.30
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
    if m["drafts_stuck"] > 0:
        out.append(Finding("CRITICAL", "notification sends",
                           f"{m['drafts_stuck']} draft(s) approved over {STUCK_APPROVED_MINUTES} minutes ago but never sent."))

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


def collect_metrics(db, log_text: str, now: datetime) -> Dict[str, Any]:
    """Read the numbers `evaluate` needs from the database and the cron log."""
    from models import Approval, Classification, InterviewEvent, NotificationDraft, ProcessRun
    from process_inbox_auto import needs_human_review

    since = now - timedelta(hours=24)

    last = db.query(ProcessRun).order_by(ProcessRun.run_timestamp.desc()).first()
    last_age = None if last is None else (now - last.run_timestamp).total_seconds() / 3600
    partial = db.query(ProcessRun).filter(
        ProcessRun.run_timestamp >= since, ProcessRun.status == "partial_failure").count()

    queued_email_ids = {row[0] for row in db.query(Approval.email_id).all()}
    recent = db.query(Classification).filter(Classification.classification_timestamp >= since).all()
    missing = sum(
        1 for c in recent
        if needs_human_review(c.category or "", float(c.confidence or 0.0))
        and c.email_id not in queued_email_ids
    )

    events = db.query(InterviewEvent).filter(InterviewEvent.created_at >= since).all()
    fallback = sum(1 for e in events if (e.raw_extraction or {}).get("sub_type_source") == "category_fallback")
    no_student = sum(1 for e in events if e.student_id is None)

    failed = db.query(NotificationDraft).filter(
        NotificationDraft.email_status == "failed", NotificationDraft.created_at >= since).count()
    stuck_cutoff = now - timedelta(minutes=STUCK_APPROVED_MINUTES)
    stuck = db.query(NotificationDraft).filter(
        NotificationDraft.email_status == "approved",
        NotificationDraft.reviewed_at != None,  # noqa: E711
        NotificationDraft.reviewed_at < stuck_cutoff).count()

    return {
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
    return f"{head}  ({now:%Y-%m-%d %H:%M} UTC)\n\n{body}\n\nNumbers:\n{numbers}\n"


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

    if findings or always_email:
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
