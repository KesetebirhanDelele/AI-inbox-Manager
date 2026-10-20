"""
Which notification drafts are OPEN CARDS: the ones the Review screen actually shows for a decision.

The approver alert and the 2-hour backup alert both use this, so nobody is told about a card they cannot see: a draft of a follow-up
(a repeat of an interview the student was already told about), of a student the approver rejected, or of old mail is hidden in Review and is skipped here.
Mirrors the filters of GET /api/notifications/review-queue (services/dashboard/api/routers/notifications.py).
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "execution", _ROOT / "services" / "dashboard" / "api"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

REVIEW_MAX_AGE_DAYS = 14        # same number as the review queue: older mail is never a decision for today


def open_review_drafts(db, now: Optional[datetime] = None) -> List:
    """Drafts waiting for a decision (status "draft") that Review shows, oldest first."""
    import models as M
    now = now or datetime.utcnow()
    follow_ups = {row.event_id for row in db.query(M.InterviewFollowUp.event_id).all()}
    rejected_students = {row.student_id for row in db.query(M.StudentVerification.student_id).filter(M.StudentVerification.status == "rejected").all()}
    cutoff = now - timedelta(days=REVIEW_MAX_AGE_DAYS)
    rows = (db.query(M.NotificationDraft, M.InterviewEvent, M.Email)
            .join(M.InterviewEvent, M.NotificationDraft.interview_event_id == M.InterviewEvent.id)
            .outerjoin(M.Email, M.InterviewEvent.email_id == M.Email.id)
            .filter(M.NotificationDraft.email_status == "draft")
            .order_by(M.NotificationDraft.id).all())
    out = []
    for draft, event, email in rows:
        if event.id in follow_ups or event.student_id in rejected_students:
            continue
        if email is not None and email.received_date and email.received_date < cutoff:
            continue
        out.append(draft)
    return out
